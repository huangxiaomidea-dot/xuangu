"""
数据源：新浪财经直连 API
使用 sh_a + sz_a 节点获取没深A股
"""

import time
import json
import requests
import pandas as pd

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.sina.com.cn/",
}

_SNAPSHOT_URL = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php"
                 "/Market_Center.getHQNodeData")
_HIST_URL = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
             "/CN_MarketData.getKLineData")


def _fetch_node_all(node: str, page_size: int = 100) -> list:
    """
    新浪接口实际上每次最多返回100条（不受 num 参数请求更大值影响），
    必须持续翻页直到成功请求返回空数组为止，不能用"返回数 < 请求数"来判断是否翻完
    （曾导致误判第1页为最后一页，全市场只拿到200只股票的严重bug）
    """
    all_rows = []
    page = 1
    while True:
        params = {"page": page, "num": page_size, "sort": "symbol", "asc": 1, "node": node}
        rows = None  # None=请求彻底失败；[]=请求成功但确实没数据了（翻页结束）
        for attempt in range(3):
            try:
                resp = requests.get(_SNAPSHOT_URL, params=params, headers=_HEADERS, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                rows = data if isinstance(data, list) else []
                break
            except Exception as e:
                print(f"[fetcher] {node} 第{page}页失败({attempt+1}): {e}")
                if attempt < 2:
                    time.sleep(2)

        if rows is None:
            print(f"[fetcher] {node} 第{page}页重试3次仍失败，提前终止翻页（已获取{len(all_rows)}只）")
            break
        if not rows:  # 成功请求但空数组，说明真的翻完了
            break

        all_rows.extend(rows)
        page += 1
        time.sleep(0.15)
        if page > 100:  # 安全阀，避免异常情况下死循环（沪深A股各不超过100*100=1万只）
            break
    return all_rows


def get_realtime_snapshot() -> pd.DataFrame:
    print("[fetcher] 拉取上证A股(sh_a)...")
    sh_rows = _fetch_node_all("sh_a")
    print(f"[fetcher] 上证A股: {len(sh_rows)} 条")
    print("[fetcher] 拉取深证A股(sz_a)...")
    sz_rows = _fetch_node_all("sz_a")
    print(f"[fetcher] 深证A股: {len(sz_rows)} 条")

    all_rows = sh_rows + sz_rows
    if not all_rows:
        print("[fetcher] 未获取到任何数据")
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    print(f"[fetcher] 共 {len(df)} 条原始数据")

    rename = {
        "symbol": "代码", "name": "名称", "trade": "最新价",
        "changepercent": "涨跌幅", "volume": "成交量", "amount": "成交额",
        "high": "最高", "low": "最低", "open": "开盘", "settlement": "昨收",
        "mktcap": "mktcap", "turnoverratio": "换手率",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    for col in ["最新价", "涨跌幅", "成交量", "最高", "最低", "开盘", "昨收", "换手率", "mktcap"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["总市值亿"] = df.get("mktcap", pd.Series(dtype=float)) / 10000
    df["振幅"] = ((df["最高"] - df["最低"]) / df["昨收"] * 100).round(2)
    df["量比"] = 1.0

    df = df[~df["名称"].str.contains("ST", na=False)]
    df["代码"] = df["代码"].astype(str).str.replace(r"^(sh|sz|bj)", "", regex=True)
    df = df[~df["代码"].str.startswith(("688", "4", "8", "9"))]
    df = df[(df["总市值亿"] >= 50) & (df["总市值亿"] <= 500)]
    df = df.dropna(subset=["最新价", "涨跌幅", "换手率"])
    df = df[df["最新价"] > 0]
    df = df.reset_index(drop=True)

    print(f"[fetcher] 过滤后剩余 {len(df)} 只股票")
    return df


def get_hist_k(symbol: str, days: int = 60) -> pd.DataFrame:
    """
    获取历史K线。新浪接口实际字段名为：day, open, high, low, close, volume
    （不是缩写的 d/o/h/l/c/v），必须用这个映射才能正确重命名
    """
    code = str(symbol).zfill(6)
    full = f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"
    for attempt in range(3):
        try:
            resp = requests.get(
                _HIST_URL,
                params={"symbol": full, "scale": 240, "ma": "no", "datalen": days},
                headers=_HEADERS, timeout=15,
            )
            raw = resp.text.strip()
            if not raw or raw == "null":
                return pd.DataFrame()
            data = json.loads(raw)
            if not data:
                return pd.DataFrame()
            df = pd.DataFrame(data)
            df.rename(columns={
                "day": "日期", "open": "开盘", "close": "收盘",
                "high": "最高", "low": "最低", "volume": "成交量"
            }, inplace=True)
            for col in ["开盘", "收盘", "最高", "最低", "成交量"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            df["日期"] = pd.to_datetime(df["日期"])
            return df.sort_values("日期").reset_index(drop=True)
        except Exception as e:
            print(f"[fetcher] get_hist_k({symbol}) 异常({attempt+1}): {e}")
            if attempt < 2:
                time.sleep(1)
    return pd.DataFrame()


def get_intraday_5min(symbol: str, datalen: int = 800) -> pd.DataFrame:
    """
    获取5分钟K线（用于结算次日9:30-9:35开盘窗口涨跌）。
    新浪 scale=5 返回的 day 字段是完整时间戳，如 "2026-07-13 09:35:00"
    """
    code = str(symbol).zfill(6)
    full = f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"
    for attempt in range(3):
        try:
            resp = requests.get(
                _HIST_URL,
                params={"symbol": full, "scale": 5, "ma": "no", "datalen": datalen},
                headers=_HEADERS, timeout=15,
            )
            raw = resp.text.strip()
            if not raw or raw == "null":
                return pd.DataFrame()
            data = json.loads(raw)
            if not data:
                return pd.DataFrame()
            df = pd.DataFrame(data)
            df.rename(columns={
                "day": "时间", "open": "开盘", "close": "收盘",
                "high": "最高", "low": "最低", "volume": "成交量"
            }, inplace=True)
            for col in ["开盘", "收盘", "最高", "最低", "成交量"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            df["时间"] = pd.to_datetime(df["时间"])
            return df.sort_values("时间").reset_index(drop=True)
        except Exception as e:
            print(f"[fetcher] get_intraday_5min({symbol}) 异常({attempt+1}): {e}")
            if attempt < 2:
                time.sleep(1)
    return pd.DataFrame()


def batch_get_hist(symbols: list, days: int = 60) -> dict:
    hist_dict = {}
    total = len(symbols)
    for i, sym in enumerate(symbols):
        if (i + 1) % 20 == 0:
            print(f"[fetcher] 历史K线 {i+1}/{total}，成功 {len(hist_dict)} 只")
        df = get_hist_k(sym, days)
        if not df.empty:
            hist_dict[sym] = df
        time.sleep(0.05)
    print(f"[fetcher] K线获取完成，成功 {len(hist_dict)}/{total} 只")
    return hist_dict
