"""
数据源：新浪财经直连 API
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
    params = {"page": page, "num": page_size, "sort": "symbol", "asc": 1, "node": "hs_a"}
    resp = requests.get(_SNAPSHOT_URL, params=params, headers=_HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def get_realtime_snapshot() -> pd.DataFrame:
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
                    print("[fetcher] 已重试3次，放弃")
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
    print(f"[fetcher] 原始数据 {len(df)} 条，字段: {df.columns.tolist()[:10]}")
    print(f"[fetcher] 样本行: {df.iloc[0].to_dict() if len(df) > 0 else '无'}")

    rename = {
        "symbol":        "代码",
        "name":          "名称",
        "trade":         "最新价",
        "changepercent": "涨跌幅",
        "volume":        "成交量",
        "amount":        "成交额",
        "high":          "最高",
        "low":           "最低",
        "open":          "开盘",
        "settlement":    "昨收",
        "mktcap":        "mktcap",
        "turnoverratio": "换手率",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    for col in ["最新价", "涨跌幅", "成交量", "最高", "最低", "开盘", "昨收", "换手率", "mktcap"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 总市值：mktcap 单位为万元 → 亿元
    if "mktcap" in df.columns:
        df["总市值亿"] = df["mktcap"] / 10000
        print(f"[fetcher] mktcap 样本均值={df['mktcap'].mean():.0f}，总市值亿均值={df['总市值亿'].mean():.1f}")
    else:
        print("[fetcher] 警告：没有 mktcap 字段")
        df["总市值亿"] = 999

    # 振幅
    if "昨收" in df.columns:
        df["振幅"] = ((df["最高"] - df["最低"]) / df["昨收"] * 100).round(2)
    else:
        df["振幅"] = 0.0

    df["量比"] = 1.0

    # 过滤步骤，逐步打印
    n0 = len(df)
    df = df[~df["名称"].str.contains("ST", na=False)]
    print(f"[fetcher] 去 ST后: {len(df)} (少了{n0-len(df)})")

    n0 = len(df)
    df = df[~df["代码"].astype(str).str.startswith(("bj", "688"))]
    print(f"[fetcher] 去北交所/科创后: {len(df)} (少了{n0-len(df)})")

    df["代码"] = df["代码"].astype(str).str.replace(r"^(sh|sz)", "", regex=True)
    n0 = len(df)
    df = df[~df["代码"].str.startswith(("4", "8"))]
    print(f"[fetcher] 去4/8头后: {len(df)} (少了{n0-len(df)})")

    n0 = len(df)
    df = df[(df["总市值亿"] >= 50) & (df["总市值亿"] <= 500)]
    print(f"[fetcher] 市值50-500亿后: {len(df)} (少了{n0-len(df)})")

    n0 = len(df)
    df = df.dropna(subset=["最新价", "涨跌幅", "换手率"])
    print(f"[fetcher] dropna后: {len(df)} (少了{n0-len(df)})")

    df = df[df["最新价"] > 0]
    df = df.reset_index(drop=True)
    print(f"[fetcher] 最终剩余 {len(df)} 只股票")
    return df


def get_hist_k(symbol: str, days: int = 60) -> pd.DataFrame:
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
                headers=_HEADERS, timeout=15,
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
