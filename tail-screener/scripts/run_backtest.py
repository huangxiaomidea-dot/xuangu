"""
尾盘选股策略历史回测 — 近1个月
用法：cd tail-screener && python scripts/run_backtest.py

策略信号条件（仅用截止当日的数据）：
  - 涨跌幅 3%~5%
  - 量比 >= 1.0（当日成交量 / 5日均量）
  - 振幅 <= 8%
  - 收盘价 > MA20
胜负判定：次日收盘涨幅 > 0 则胜
"""

import sys
import os
import time
import json
import requests
import pandas as pd
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn/",
}


def fetch_stock_list(max_stocks: int = 300) -> list:
    """从新浪获取 A 股代码列表（取前 max_stocks 只）"""
    url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    symbols = []
    page = 1
    while len(symbols) < max_stocks:
        params = {"page": page, "num": 200, "sort": "symbol", "asc": 1, "node": "hs_a"}
        try:
            resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
            data = resp.json()
            if not data:
                break
            for item in data:
                sym = str(item.get("symbol", "")).strip()
                if sym:
                    symbols.append(sym)
            if len(data) < 200:
                break
            page += 1
            time.sleep(0.1)
        except Exception as e:
            print(f"[backtest] 获取股票列表第{page}页失败: {e}")
            break
    return symbols[:max_stocks]


def fetch_hist(symbol: str, days: int = 90) -> pd.DataFrame:
    """获取单股历史日 K 线"""
    code = symbol.replace("sh", "").replace("sz", "").replace("bj", "")
    code = code.zfill(6)
    if code.startswith(("6", "9")):
        full = f"sh{code}"
    elif code.startswith(("4", "8")):
        full = f"bj{code}"
    else:
        full = f"sz{code}"
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": full, "scale": 240, "ma": "no", "datalen": days}
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        raw = resp.text.strip()
        if not raw or raw == "null":
            return pd.DataFrame()
        data = json.loads(raw)
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        df.rename(columns={"d": "日期", "o": "开盘", "c": "收盘", "h": "最高", "l": "最低", "v": "成交量"}, inplace=True)
        for col in ["开盘", "收盘", "最高", "最低", "成交量"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["日期"] = pd.to_datetime(df["日期"])
        df.sort_values("日期", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df
    except Exception:
        return pd.DataFrame()


def simulate_stock(symbol: str, df: pd.DataFrame, start_date: pd.Timestamp, end_date: pd.Timestamp) -> list:
    """
    对单只股票在 [start_date, end_date] 区间逐日模拟选股信号。
    返回信号列表：[{"date": ..., "next_ret": ..., "win": ...}]
    """
    if df.empty or len(df) < 25:
        return []

    signals = []
    dates_in_range = df[(df["日期"] >= start_date) & (df["日期"] <= end_date)]

    for idx in dates_in_range.index:
        # 只用截止当日的历史
        hist = df.loc[:idx]
        if len(hist) < 22:
            continue

        row = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) >= 2 else None
        if prev is None:
            continue

        # 涨跌幅
        pct = (row["收盘"] - prev["收盘"]) / prev["收盘"] * 100
        if not (3.0 <= pct <= 5.0):
            continue

        # 振幅
        amp = (row["最高"] - row["最低"]) / prev["收盘"] * 100
        if amp > 8.0:
            continue

        # 量比（当日量 / 5日均量）
        vol_ma5 = hist["成交量"].iloc[-6:-1].mean()
        if vol_ma5 <= 0:
            continue
        vol_ratio = row["成交量"] / vol_ma5
        if vol_ratio < 1.0:
            continue

        # 收盘 > MA20
        ma20 = hist["收盘"].iloc[-20:].mean()
        if row["收盘"] <= ma20:
            continue

        # 有次日数据才算信号
        if idx + 1 not in df.index:
            continue
        next_row = df.loc[idx + 1]
        next_ret = (next_row["收盘"] - row["收盘"]) / row["收盘"] * 100
        signals.append({
            "symbol": symbol,
            "date": row["日期"].strftime("%Y-%m-%d"),
            "pct": round(pct, 2),
            "vol_ratio": round(vol_ratio, 2),
            "amp": round(amp, 2),
            "next_ret": round(next_ret, 2),
            "win": next_ret > 0,
        })

    return signals


def main():
    print("=" * 55)
    print("=== 尾盘选股策略回测（近1个月）===")
    print(f"=== 运行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    print("=" * 55)

    end_date = pd.Timestamp(datetime.now().date())
    start_date = end_date - pd.Timedelta(days=30)
    print(f"\n回测区间：{start_date.date()} ~ {end_date.date()}")

    print("\n[1] 获取股票列表...")
    symbols = fetch_stock_list(max_stocks=300)
    print(f"    共 {len(symbols)} 只股票")

    print("\n[2] 拉取历史 K 线并模拟选股...")
    all_signals = []
    failed = 0
    for i, sym in enumerate(symbols, 1):
        if i % 50 == 0:
            print(f"    进度：{i}/{len(symbols)}，累计信号 {len(all_signals)} 条")
        df = fetch_hist(sym, days=90)
        if df.empty:
            failed += 1
        else:
            sigs = simulate_stock(sym, df, start_date, end_date)
            all_signals.extend(sigs)
        time.sleep(0.08)

    print(f"\n[3] 回测结果")
    print("-" * 55)
    if not all_signals:
        print("    未产生任何信号（可能区间内无满足条件的交易日）")
        return

    total = len(all_signals)
    wins = sum(1 for s in all_signals if s["win"])
    win_rate = wins / total * 100
    avg_ret = sum(s["next_ret"] for s in all_signals) / total
    avg_win_ret = sum(s["next_ret"] for s in all_signals if s["win"]) / wins if wins else 0
    avg_loss_ret = sum(s["next_ret"] for s in all_signals if not s["win"]) / (total - wins) if (total - wins) else 0

    print(f"    信号总数：{total}")
    print(f"    胜利次数：{wins}")
    print(f"    胜率：    {win_rate:.1f}%")
    print(f"    平均次日涨幅：{avg_ret:+.2f}%")
    print(f"    盈利均值：    {avg_win_ret:+.2f}%")
    print(f"    亏损均值：    {avg_loss_ret:+.2f}%")
    print(f"    拉取失败股票：{failed} 只")

    # 按日期汇总
    by_date: dict = {}
    for s in all_signals:
        d = s["date"]
        if d not in by_date:
            by_date[d] = {"total": 0, "wins": 0}
        by_date[d]["total"] += 1
        if s["win"]:
            by_date[d]["wins"] += 1

    print("\n    按交易日明细：")
    print(f"    {'日期':<12} {'信号':>4} {'胜':>4} {'胜率':>6}")
    for d in sorted(by_date):
        t = by_date[d]["total"]
        w = by_date[d]["wins"]
        print(f"    {d:<12} {t:>4} {w:>4} {w/t*100:>5.0f}%")

    print("\n    TOP10 信号明细（按次日涨幅排序）：")
    top_sigs = sorted(all_signals, key=lambda x: -x["next_ret"])[:10]
    print(f"    {'日期':<12} {'代码':<10} {'涨跌幅':>6} {'量比':>5} {'振幅':>5} {'次日':>6}")
    for s in top_sigs:
        print(f"    {s['date']:<12} {s['symbol']:<10} {s['pct']:>+5.1f}% {s['vol_ratio']:>4.1f}x {s['amp']:>4.1f}% {s['next_ret']:>+5.2f}%")

    if win_rate < 55:
        print("\n  ⚠️  胜率低于55%，建议审查因子权重或过滤条件")
    else:
        print("\n  ✅  胜率达标（>=55%）")

    print("\n" + "=" * 55)
    print("=== 回测完成 ===")
    print("=" * 55)


if __name__ == "__main__":
    main()
