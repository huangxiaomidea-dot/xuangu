"""
数据源：新浪财经直连 API（境内服务器可用，不依赖 akshare/东方财富）
新浪 mktcap 字段单位为万元，除以10000得亿元
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

_SNAPSHOT_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php"
    "/Market_Center.getHQNodeData"
)
_HIST_URL = (
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
    "/CN_MarketData.getKLineData"
)


def _fetch_snapshot_page(page: int, page_size: int = 200) -> list:
    params = {
        "page": page,
        "num": page_size,
        "sort": "symbol",
        "asc": 1,
        "node": "hs_a",
    }
    resp = requests.get(_SNAPSHOT_URL, params=params, headers=_HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def get_realtime_snapshot() -> pd.DataFrame:
    """
    获取全A股实时快照。
    新浪返回字段：symbol, name, trade(最新价), changepercent(涨跌幅%),
      volume(成交量手), amount(成交额元), high, low, open, settlement(昨收),
      mktcap(万元), pb, per, turnoverratio(换手率%)
    """
    all_rows = []
    page = 1
    while True:
        for attempt in range(3):
            try:
                rows = _fetch_snapshot_page(page)
                break
            except Exception as e:
                print(f"[fetcher] 获取快照失败（第{attempt+1}次）: {e}")
                if attempt < 2:
                    time.sleep(2)
                else:
                    print("[fetcher] 已重试3次，放弃获取快照")
                    rows = []
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < 200:
            break
        page += 1
        time.sleep(0.1)

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)

    # 列名映射
    rename = {
        "symbol":       "代码",
        "name":         "名称",
        "trade":        "最新价",
        "changepercent":"涨跌幅",
        "volume":       "成交量",
        "amount":       "成交额",
        "high":         "最高",
        "low":          "最低",
        "open":         "开盘",
        "settlement":   "昨收",
        "mktcap":       "mktcap",
        "turnoverratio":"换手率",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    # 数值转换
    for col in ["最新价", "涨跌幅", "成交量", "最高", "最低", "开盘", "昨收", "换手率", "mktcap"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 总市值：mktcap 单位为万元 → 亿元
    df["总市值亿"] = df["mktcap"] / 10000

    # 振幅 = (high - low) / settlement * 100
    df["振幅"] = ((df["最高"] - df["最低"]) / df["昨收"] * 100).round(2)

    # 量比暂时设为1.0，在 factors 里用历史K线修正
    df["量比"] = 1.0

    # 过滤
    df = df[~df["名称"].str.contains("ST", na=False)]
    df = df[~df["代码"].astype(str).str.startswith(("bj", "688"))]
    df["代码"] = df["代码"].astype(str).str.replace(r"^(sh|sz)", "", regex=True)
    df = df[~df["代码"].str.startswith(("4", "8"))]
    df = df[(df["总市值亿"] >= 50) & (df["总市值亿"] <= 500)]
    df = df.dropna(subset=["最新价", "涨跌幅", "换手率", "振幅"])
    df = df[df["最新价"] > 0]
    df = df.reset_index(drop=True)

    print(f"[fetcher] 过滤后剩余 {len(df)} 只股票")
    return df


def get_hist_k(symbol: str, days: int = 60) -> pd.DataFrame:
    """获取单只股票历史日K线（新浪接口）"""
    code = str(symbol).zfill(6)
    if code.startswith(("6", "9")):
        full = f"sh{code}"
    elif code.startswith(("4", "8")):
        full = f"bj{code}"
    else:
        full = f"sz{code}"

    for attempt in range(3):
        try:
            resp = requests.get(
                _HIST_URL,
                params={"symbol": full, "scale": 240, "ma": "no", "datalen": days},
                headers=_HEADERS,
                timeout=15,
            )
            raw = resp.text.strip()
            if not raw or raw == "null":
                return pd.DataFrame()
            data = json.loads(raw)
            if not data:
                return pd.DataFrame()
            df = pd.DataFrame(data)
            df.rename(columns={"d": "日期", "o": "开盘", "c": "收盘",
                                "h": "最高", "l": "最低", "v": "成交量"}, inplace=True)
            for col in ["开盘", "收盘", "最高", "最低", "成交量"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df["日期"] = pd.to_datetime(df["日期"])
            df = df.sort_values("日期").reset_index(drop=True)
            return df
        except Exception as e:
            if attempt < 2:
                time.sleep(1)
    return pd.DataFrame()


def batch_get_hist(symbols: list, days: int = 60) -> dict:
    """批量获取历史K线，返回 {symbol: df} 字典"""
    hist_dict = {}
    total = len(symbols)
    for i, sym in enumerate(symbols):
        if (i + 1) % 20 == 0:
            print(f"[fetcher] 历史K线 {i+1}/{total}，成功 {len(hist_dict)} 只")
        df = get_hist_k(sym, days)
        if not df.empty:
            hist_dict[sym] = df
        time.sleep(0.05)
    print(f"[fetcher] 历史K线获取完成，成功 {len(hist_dict)}/{total} 只")
    return hist_dict
