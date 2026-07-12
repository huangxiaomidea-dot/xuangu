"""
滚动复盘模块
每次选股后记录 TOP3 为待结算记录；下次运行时用最新快照价格结算上一次的记录（涨则胜），
并累计历史胜率。结果持久化到 notes/track_record.json。
"""

import os
import json
import pandas as pd
from datetime import datetime

_TRACK_FILE = os.path.join(os.path.dirname(__file__), "..", "notes", "track_record.json")


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


def settle_pending(snapshot_df: pd.DataFrame, today_str: str) -> list:
    """
    用今日快照结算所有待结算且非今日选出的记录。
    返回：本次新结算的记录列表
    """
    records = _load()
    if not records or snapshot_df.empty:
        return []

    price_map = dict(zip(
        snapshot_df["代码"].astype(str).str.zfill(6),
        pd.to_numeric(snapshot_df["最新价"], errors="coerce")
    ))

    newly_settled = []
    for rec in records:
        if rec.get("settled"):
            continue
        if rec.get("date") == today_str:
            continue  # 当日新选股，次日才结算
        code = str(rec["code"]).zfill(6)
        cur_price = price_map.get(code)
        if cur_price is None or pd.isna(cur_price) or cur_price <= 0:
            continue
        pick_price = rec["pick_price"]
        return_pct = round((cur_price - pick_price) / pick_price * 100, 2)
        rec["settled"] = True
        rec["settle_date"] = today_str
        rec["settle_price"] = cur_price
        rec["return_pct"] = return_pct
        rec["win"] = return_pct > 0
        newly_settled.append(rec)

    if newly_settled:
        _save(records)
        print(f"[tracker] 结算 {len(newly_settled)} 条历史选股记录")

    return newly_settled


def record_picks(top3_df: pd.DataFrame, date_str: str):
    """将今日 TOP3 记为待结算"""
    if top3_df.empty:
        return
    records = _load()
    for _, row in top3_df.iterrows():
        records.append({
            "date": date_str,
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


def cumulative_stats() -> dict:
    """统计所有已结算记录的累计胜率"""
    records = _load()
    settled = [r for r in records if r.get("settled")]
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
    stats = cumulative_stats()
    lines = []

    if newly_settled:
        lines.append("昨日复盘：")
        for rec in newly_settled:
            mark = "✅" if rec["win"] else "❌"
            lines.append(f"  {mark} {rec['name']}（{rec['code']}）{rec['return_pct']:+.2f}%")
    else:
        lines.append("昨日复盘：暂无待结算记录")

    if stats["total"] > 0:
        lines.append(
            f"累计胜率：{stats['win_rate']}%（{stats['wins']}/{stats['total']}）"
            f"，平均收益 {stats['avg_return']:+.2f}%"
        )
    else:
        lines.append("累计胜率：暂无历史数据")

    return "\n".join(lines)
