"""
20日历史回测 —— 用当前选股规则逐日复现历史TOP3，并用次日9:30-9:40开盘窗口结算
结果写入 notes/algo_backtest.json，供前端展示，可重复运行以滚动刷新（自动使用最新20个交易日）

用法：cd tail-screener && python scripts/run_algo_backtest.py
"""

import sys
import os
import json
import time
from datetime import datetime, time as dtime

import pandas as pd
import numpy as np
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import fetcher

RESULT_FILE = os.path.join(ROOT, "notes", "algo_backtest.json")
WIN_THRESHOLD_PCT = 0.1
LOOKBACK_DAYS = 20        # 回测窗口（交易日）
MA_WARMUP_DAYS = 25       # 为计算MA20等因子多拉的历史天数
SAMPLE_STOCKS = 300       # 抽样股票数（兼顾速度与代表性）


def load_config() -> dict:
    with open(os.path.join(ROOT, "config.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch_stock_list(max_stocks: int = SAMPLE_STOCKS) -> list:
    sh_rows = fetcher._fetch_node_all("sh_a")
    sz_rows = fetcher._fetch_node_all("sz_a")
    symbols = []
    for row in (sh_rows + sz_rows):
        sym = str(row.get("symbol", "")).strip()
        code = sym.replace("sh", "").replace("sz", "").replace("bj", "")
        name = str(row.get("name", ""))
        if not code or "ST" in name:
            continue
        if code.startswith(("688", "4", "8", "9")):
            continue
        symbols.append(code.zfill(6))
    return symbols[:max_stocks]


def compute_daily_factors(hist: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """
    对单只股票的日K线，逐日计算因子与概率分（仅用截至当日的数据，不看未来）。
    返回新增列后的DataFrame，索引与hist对齐。
    """
    f = cfg["factors"]
    w = cfg["weights"]

    close = hist["收盘"]
    high = hist["最高"]
    low = hist["最低"]
    vol = hist["成交量"]
    prev_close = close.shift(1)

    change_pct = (close - prev_close) / prev_close * 100
    vol_ma5 = vol.shift(1).rolling(5).mean()
    volume_ratio = vol / vol_ma5
    price_range = (high - low).replace(0, np.nan)
    close_strength = (close - low) / price_range
    upper_shadow = (high - close) / close * 100
    ma5 = close.rolling(5).mean()
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    close_5d_ago = close.shift(5)
    extend_5d = (close - close_5d_ago) / close_5d_ago * 100

    f_change_pct = ((change_pct >= f["change_pct_min"]) & (change_pct <= f["change_pct_max"])).astype(float)
    f_volume_ratio = (volume_ratio >= f["volume_ratio_min"]).astype(float)
    f_above_ma20 = (close > ma20).astype(float)
    f_ma_trend = ((ma5 > ma10) & (ma10 > ma20)).astype(float)
    f_vol_gt_ma5 = (vol > vol_ma5).astype(float)

    # 连续分级打分（与 src/factors.py 的线上打分逻辑保持一致，避免二元达标导致大量同分）
    change_mid = (f["change_pct_min"] + f["change_pct_max"]) / 2
    change_half = (f["change_pct_max"] - f["change_pct_min"]) / 2
    s_change_pct = (1 - (change_pct - change_mid).abs() / change_half).clip(0, 1)
    s_volume_ratio = (volume_ratio / (f["volume_ratio_min"] * 1.5)).clip(0, 1)
    s_close_strength = close_strength.clip(0, 1)
    s_upper_shadow = (1 - upper_shadow / f["upper_shadow_max"]).clip(0, 1)
    s_extend_5d = (1 - extend_5d.clip(lower=0) / f["extend_5d_max"]).clip(0, 1)

    score = (
        s_change_pct.fillna(0) * w["change_pct"] * 100 +
        s_volume_ratio.fillna(0) * w["volume_ratio"] * 100 +
        s_close_strength.fillna(0) * w["close_strength"] * 100 +
        s_upper_shadow.fillna(0) * w["upper_shadow"] * 100 +
        f_ma_trend.fillna(0.5) * w["ma_trend"] * 100 +
        f_above_ma20.fillna(0.5) * w["above_ma20"] * 100 +
        f_vol_gt_ma5.fillna(0.5) * w["vol_gt_ma5"] * 100 +
        s_extend_5d.fillna(0.5) * w["extend_5d"] * 100
    )

    qualified = (f_change_pct == 1) & (f_volume_ratio == 1)

    out = hist.copy()
    out["change_pct"] = change_pct
    out["score"] = score
    out["qualified"] = qualified
    return out


def find_open_window(sym: str, pick_date, minute_cache: dict):
    """用5分钟K线找次日9:30-9:40窗口的最高价与收盘价"""
    if sym not in minute_cache:
        minute_cache[sym] = fetcher.get_intraday_5min(sym, datalen=2000)
    df = minute_cache[sym]
    if df.empty:
        return None
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


def main():
    print("=" * 55)
    print("=== 20日历史回测（当前算法 + 次日9:30-9:40开盘窗口结算）===")
    print(f"=== 运行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    print("=" * 55)

    cfg = load_config()

    print(f"\n[1] 获取股票列表（样本 {SAMPLE_STOCKS} 只）...")
    symbols = fetch_stock_list()
    print(f"    共 {len(symbols)} 只")

    print("\n[2] 拉取日K线并计算逐日因子...")
    total_days_needed = LOOKBACK_DAYS + MA_WARMUP_DAYS
    stock_factor_frames = {}
    for i, sym in enumerate(symbols, 1):
        if i % 50 == 0:
            print(f"    进度：{i}/{len(symbols)}")
        hist = fetcher.get_hist_k(sym, days=total_days_needed)
        if hist.empty or len(hist) < MA_WARMUP_DAYS + 2:
            continue
        stock_factor_frames[sym] = compute_daily_factors(hist, cfg)
        time.sleep(0.05)
    print(f"    成功计算 {len(stock_factor_frames)} 只股票的因子")

    print("\n[3] 按日期聚合，逐日选出TOP3...")
    # 收集所有交易日期（取最近LOOKBACK_DAYS个）
    all_dates = sorted({d for df in stock_factor_frames.values() for d in df["日期"]})
    test_dates = all_dates[-LOOKBACK_DAYS - 1:-1]  # 留最后一天做未来数据，不用于选股（无法验证次日）
    print(f"    回测交易日：{test_dates[0].strftime('%Y-%m-%d')} ~ {test_dates[-1].strftime('%Y-%m-%d')}（{len(test_dates)}天）")

    daily_picks = []
    for d in test_dates:
        rows = []
        for sym, df in stock_factor_frames.items():
            match = df[df["日期"] == d]
            if match.empty:
                continue
            r = match.iloc[0]
            if not r["qualified"] or pd.isna(r["score"]):
                continue
            rows.append({
                "code": sym,
                "name": "",
                "pick_price": float(r["收盘"]),
                "score": float(r["score"]),
            })
        if not rows:
            continue
        rows.sort(key=lambda x: -x["score"])
        top3 = rows[:3]
        for rank, p in enumerate(top3, start=1):
            p["rank"] = rank
        daily_picks.append({"date": d.strftime("%Y-%m-%d"), "picks": top3})

    total_signals = sum(len(dp["picks"]) for dp in daily_picks)
    print(f"    共 {len(daily_picks)} 个交易日产生信号，累计 {total_signals} 条TOP3记录")

    print("\n[4] 用5分钟K线结算次日9:30-9:40开盘窗口...")
    minute_cache = {}
    settled_records = []
    for dp in daily_picks:
        pick_date = datetime.strptime(dp["date"], "%Y-%m-%d").date()
        for p in dp["picks"]:
            info = find_open_window(p["code"], pick_date, minute_cache)
            if info is None:
                continue
            threshold = p["pick_price"] * (1 + WIN_THRESHOLD_PCT / 100)
            win = info["high"] >= threshold
            settle_price = info["high"] if win else info["close"]
            return_pct = round((settle_price - p["pick_price"]) / p["pick_price"] * 100, 2)
            settled_records.append({
                "date": dp["date"],
                "rank": p["rank"],
                "code": p["code"],
                "pick_price": p["pick_price"],
                "settle_date": info["settle_date"],
                "settle_price": settle_price,
                "return_pct": return_pct,
                "win": win,
            })
        time.sleep(0.05)

    print(f"    成功结算 {len(settled_records)}/{total_signals} 条记录")

    def calc_stats(records):
        if not records:
            return {"total": 0, "wins": 0, "win_rate": None, "avg_return": None}
        total = len(records)
        wins = sum(1 for r in records if r["win"])
        avg_return = round(sum(r["return_pct"] for r in records) / total, 2)
        return {"total": total, "wins": wins, "win_rate": round(wins / total * 100, 1), "avg_return": avg_return}

    top3_stats = calc_stats(settled_records)
    top1_stats = calc_stats([r for r in settled_records if r["rank"] == 1])

    print("\n[5] 回测结果")
    print("-" * 55)
    print(f"    TOP3整体成功率：{top3_stats['win_rate']}%（{top3_stats['wins']}/{top3_stats['total']}）")
    print(f"    首选成功率：    {top1_stats['win_rate']}%（{top1_stats['wins']}/{top1_stats['total']}）")

    result = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "lookback_days": LOOKBACK_DAYS,
        "sample_stocks": len(stock_factor_frames),
        "top3_stats": top3_stats,
        "top1_stats": top1_stats,
        "records": settled_records,
    }
    os.makedirs(os.path.dirname(RESULT_FILE), exist_ok=True)
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存：{RESULT_FILE}")
    print("=" * 55)


if __name__ == "__main__":
    main()
