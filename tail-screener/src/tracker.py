"""
滚动复盘模块
每次选股后记录 TOP3（含排名）为待结算记录；结算时机改为监控次日 9:30-9:40
开盘窗口，只要期间涨幅摸到 pick_price 的 +0.1% 即算成功（win）。
分别统计：① TOP3 整体成功率  ② 排名第1（首选）单独成功率
结果持久化到 notes/track_record.json
"""

import os
import json
import pandas as pd
from datetime import datetime, time as dtime

from . import fetcher

_TRACK_FILE = os.path.join(os.path.dirname(__file__), "..", "notes", "track_record.json")

WIN_THRESHOLD_PCT = 0.1  # 开盘窗口内涨幅需超过0.1%才算成功


def _load() -> list:
    if not os.path.exists(_TRACK_FILE):
        return []
    try:
        with open(_TRACK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(records: list):
    os.makedirs(os.path.dirname(_TRACK_FILE), exist_ok=True)
    with open(_TRACK_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def record_picks(top3_df: pd.DataFrame, date_str: str):
    """将今日 TOP3（含排名）记为待结算"""
    if top3_df.empty:
        return
    records = _load()
    for rank, (_, row) in enumerate(top3_df.iterrows(), start=1):
        records.append({
            "date": date_str,
            "rank": rank,
            "code": str(row.get("代码", "")).zfill(6),
            "name": row.get("名称", ""),
            "pick_price": float(row.get("最新价", 0)),
            "score": float(row.get("概率分", 0)),
            "settled": False,
            "settle_date": None,
            "settle_price": None,
            "return_pct": None,
            "win": None,
        })
    _save(records)
    print(f"[tracker] 已记录今日 {len(top3_df)} 条选股为待结算")


def _find_open_window_result(symbol: str, pick_date_str: str):
    """
    在 pick_date 之后最近一个有分钟数据的交易日，取 9:30-9:40 窗口内的
    最高价与收盘价。返回 {settle_date, high, close} 或 None（数据尚未产生）
    """
    df = fetcher.get_intraday_5min(symbol)
    if df.empty:
        return None

    pick_date = datetime.strptime(pick_date_str, "%Y-%m-%d").date()
    later = df[df["时间"].dt.date > pick_date]
    if later.empty:
        return None

    next_date = later["时间"].dt.date.min()
    window = later[
        (later["时间"].dt.date == next_date) &
        (later["时间"].dt.time >= dtime(9, 30)) &
        (later["时间"].dt.time <= dtime(9, 40))
    ]
    if window.empty:
        return None

    window = window.sort_values("时间")
    return {
        "settle_date": next_date.strftime("%Y-%m-%d"),
        "high": float(window["最高"].max()),
        "close": float(window.iloc[-1]["收盘"]),
    }


def settle_pending_open_window() -> list:
    """
    结算所有待结算记录：用次日9:30-9:40开盘窗口涨幅判断成功/失败。
    若次日分钟数据尚未产生，跳过，留待下次结算。
    返回本次新结算的记录列表
    """
    records = _load()
    if not records:
        return []

    newly_settled = []
    for rec in records:
        if rec.get("settled"):
            continue
        info = _find_open_window_result(rec["code"], rec["date"])
        if info is None:
            continue

        pick_price = rec["pick_price"]
        threshold_price = pick_price * (1 + WIN_THRESHOLD_PCT / 100)
        win = info["high"] >= threshold_price

        settle_price = info["high"] if win else info["close"]
        return_pct = round((settle_price - pick_price) / pick_price * 100, 2)

        rec["settled"] = True
        rec["settle_date"] = info["settle_date"]
        rec["settle_price"] = settle_price
        rec["return_pct"] = return_pct
        rec["win"] = win
        newly_settled.append(rec)

    if newly_settled:
        _save(records)
        print(f"[tracker] 结算 {len(newly_settled)} 条待结算记录（次日9:30-9:40开盘窗口）")
    else:
        print("[tracker] 本次无可结算记录（可能次日分钟数据尚未产生）")

    return newly_settled


def cumulative_stats(rank_filter: int = None) -> dict:
    """
    统计累计成功率。
    rank_filter=None  -> TOP3 整体（每只股票各算一次样本）
    rank_filter=1     -> 仅统计每日首选（排名第1）
    """
    records = _load()
    settled = [r for r in records if r.get("settled")]
    if rank_filter is not None:
        settled = [r for r in settled if r.get("rank") == rank_filter]

    if not settled:
        return {"total": 0, "wins": 0, "win_rate": None, "avg_return": None}

    total = len(settled)
    wins = sum(1 for r in settled if r.get("win"))
    avg_return = round(sum(r.get("return_pct", 0) for r in settled) / total, 2)
    return {
        "total": total,
        "wins": wins,
        "win_rate": round(wins / total * 100, 1),
        "avg_return": avg_return,
    }


def format_rolling_summary(newly_settled: list) -> str:
    """生成滚动复盘文本（用于报告和推送）"""
    top3_stats = cumulative_stats()
    top1_stats = cumulative_stats(rank_filter=1)
    lines = []

    if newly_settled:
        lines.append("最新结算（9:30-9:40开盘窗口涨幅>0.1%算成功）：")
        for rec in sorted(newly_settled, key=lambda r: r["rank"]):
            mark = "✅" if rec["win"] else "❌"
            tag = "【首选】" if rec["rank"] == 1 else ""
            lines.append(f"  {mark} {tag}{rec['name']}（{rec['code']}）{rec['return_pct']:+.2f}%")
    else:
        lines.append("本次无新结算记录")

    if top3_stats["total"] > 0:
        lines.append(
            f"TOP3累计成功率：{top3_stats['win_rate']}%"
            f"（{top3_stats['wins']}/{top3_stats['total']}）"
        )
    else:
        lines.append("TOP3累计成功率：暂无历史数据")

    if top1_stats["total"] > 0:
        lines.append(
            f"首选累计成功率：{top1_stats['win_rate']}%"
            f"（{top1_stats['wins']}/{top1_stats['total']}）"
        )
    else:
        lines.append("首选累计成功率：暂无历史数据")

    return "\n".join(lines)
