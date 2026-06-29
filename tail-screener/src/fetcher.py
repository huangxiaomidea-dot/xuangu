"""
全A股实时快照与历史K线获取模块
使用 akshare 接口，带重试机制
"""

import time
import akshare as ak
import pandas as pd


def get_realtime_snapshot() -> pd.DataFrame:
    for attempt in range(3):
        try:
            df = ak.stock_zh_a_spot_em()
            print(f"[fetcher] 原始列名: {df.columns.tolist()}")
            break
        except Exception as e:
            print(f"[fetcher] 获取快照失败（第{attempt+1}次）: {e}")
            if attempt < 2:
                time.sleep(1)
            else:
                print("[fetcher] 已重试3次，放弃")
                return pd.DataFrame()

    if df.empty:
        return df

    col_map = {}
    for col in df.columns:
        if col in ("代码", "股票代码"): col_map[col] = "代码"
        elif col in ("名称", "股票名称"): col_map[col] = "名称"
        elif col in ("最新价", "现价"): col_map[col] = "最新价"
        elif "涨跌幅" in col and "60" not in col and "年初" not in col and "5分" not in col: col_map[col] = "涨跌幅"
        elif col == "量比": col_map[col] = "量比"
        elif col == "换手率": col_map[col] = "换手率"
        elif col == "振幅": col_map[col] = "振幅"
        elif col == "总市值": col_map[col] = "总市值"
    df = df.rename(columns=col_map)

    required = ["代码", "名称", "最新价", "涨跌幅", "量比", "换手率", "振幅", "总市值"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(f"[fetcher] 缺少列: {missing}")
        return pd.DataFrame()

    df = df[~df["名称"].str.contains("ST", na=False)]
    df = df[~df["代码"].astype(str).str.startswith(("688", "4", "8"))]
    df["总市值"] = pd.to_numeric(df["总市值"], errors="coerce")
    df = df[(df["总市值"] >= 50e8) & (df["总市值"] <= 500e8)]
    for col in ["最新价", "涨跌幅", "量比", "换手率", "振幅"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["最新价", "涨跌幅", "量比", "换手率", "振幅"])
    df = df[df["最新价"] > 0].reset_index(drop=True)
    print(f"[fetcher] 过滤后剩余 {len(df)} 只")
    return df


def get_hist_k(symbol: str, days: int = 60) -> pd.DataFrame:
    for attempt in range(3):
        try:
            df = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")
            return df.tail(days).reset_index(drop=True) if not df.empty else df
        except Exception as e:
            print(f"[fetcher] 历史K线 {symbol} 失败（第{attempt+1}次）: {e}")
            if attempt < 2:
                time.sleep(1)
    return pd.DataFrame()


def batch_get_hist(symbols: list, days: int = 60) -> dict:
    hist_dict = {}
    for i, sym in enumerate(symbols):
        if (i + 1) % 20 == 0:
            print(f"[fetcher] K线进度 {i+1}/{len(symbols)}...")
        df = get_hist_k(sym, days)
        if not df.empty:
            hist_dict[sym] = df
        time.sleep(0.05)
    print(f"[fetcher] K线获取完成 {len(hist_dict)}/{len(symbols)} 只")
    return hist_dict
