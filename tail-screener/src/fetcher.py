"""
全A股实时快照与历史K线获取模块
使用 akshare 接口，带重试机制
"""

import time
import akshare as ak
import pandas as pd


def get_realtime_snapshot() -> pd.DataFrame:
    """
    获取全A股实时快照，过滤不符合条件的股票。
    akshare 返回的常见列名：
      代码, 名称, 最新价, 涨跌幅, 涨跌额, 成交量, 成交额,
      振幅, 最高, 最低, 今开, 昨收, 量比, 换手率, 市盈率-动态,
      市净率, 总市值, 流通市值, 涨速, 5分钟涨跌, 60日涨跌幅, 年初至今涨跌幅
    """
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
                print("[fetcher] 已重试3次，放弃获取快照")
                return pd.DataFrame()

    if df.empty:
        print("[fetcher] 快照数据为空")
        return df

    # 统一列名映射，兼容 akshare 不同版本字段名
    col_map = {}
    for col in df.columns:
        if col in ("代码", "股票代码"):
            col_map[col] = "代码"
        elif col in ("名称", "股票名称"):
            col_map[col] = "名称"
        elif col in ("最新价", "现价"):
            col_map[col] = "最新价"
        elif "涨跌幅" in col and "60" not in col and "年初" not in col and "5分" not in col:
            col_map[col] = "涨跌幅"
        elif col in ("量比",):
            col_map[col] = "量比"
        elif col in ("换手率",):
            col_map[col] = "换手率"
        elif col in ("振幅",):
            col_map[col] = "振幅"
        elif col in ("总市值",):
            col_map[col] = "总市值"
    df = df.rename(columns=col_map)

    required_cols = ["代码", "名称", "最新价", "涨跌幅", "量比", "换手率", "振幅", "总市值"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        print(f"[fetcher] 缺少必要列: {missing}，当前列: {df.columns.tolist()}")
        return pd.DataFrame()

    # 1. 剔除ST、*ST
    df = df[~df["名称"].str.contains("ST", na=False)]

    # 2. 剔除科创板(688)、北交所(4/8开头)
    df = df[~df["代码"].astype(str).str.startswith(("688", "4", "8"))]

    # 3. 总市值过滤：单位为元，配置为亿，需换算
    df["总市值"] = pd.to_numeric(df["总市值"], errors="coerce")
    # akshare 总市值单位为元
    df = df[(df["总市值"] >= 50e8) & (df["总市值"] <= 500e8)]

    # 4. 数值类型转换，过滤无效数据
    for col in ["最新价", "涨跌幅", "量比", "换手率", "振幅"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["最新价", "涨跌幅", "量比", "换手率", "振幅"])

    # 5. 过滤价格异常（停牌等）
    df = df[df["最新价"] > 0]

    df = df.reset_index(drop=True)
    print(f"[fetcher] 过滤后剩余 {len(df)} 只股票")
    return df


def get_hist_k(symbol: str, days: int = 60) -> pd.DataFrame:
    """
    获取单只股票的前复权日K线数据（最近 days 行）。
    返回列含：日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率
    """
    for attempt in range(3):
        try:
            df = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")
            if df.empty:
                return df
            df = df.tail(days).reset_index(drop=True)
            return df
        except Exception as e:
            print(f"[fetcher] 获取历史K线 {symbol} 失败（第{attempt+1}次）: {e}")
            if attempt < 2:
                time.sleep(1)
    return pd.DataFrame()


def batch_get_hist(symbols: list, days: int = 60) -> dict:
    """
    批量获取历史K线，返回 {symbol: df} 字典。
    对获取失败的股票打印警告并跳过。
    """
    hist_dict = {}
    total = len(symbols)
    for i, sym in enumerate(symbols):
        if (i + 1) % 20 == 0:
            print(f"[fetcher] 已获取历史K线 {i+1}/{total}...")
        df = get_hist_k(sym, days)
        if not df.empty:
            hist_dict[sym] = df
        time.sleep(0.05)  # 避免请求过于频繁
    print(f"[fetcher] 历史K线获取完成，成功 {len(hist_dict)}/{total} 只")
    return hist_dict
