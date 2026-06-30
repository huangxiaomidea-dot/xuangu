"""
全A股实时快照与历史K线获取模块
数据源：新浪财经（境内服务器可用）
"""

import time
import requests
import pandas as pd

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn/",
}
_SINA_URL = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"


def _fetch_page(page: int, page_size: int = 200) -> list:
    params = {"page": page, "num": page_size, "sort": "symbol", "asc": 1, "node": "hs_a"}
    resp = requests.get(_SINA_URL, params=params, headers=_HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_realtime_snapshot() -> pd.DataFrame:
    """
    获取全A股实时快照（新浪财经接口）。
    新浪 mktcap 单位为亿元，直接与50~500对比。
    """
    all_rows = []
    for attempt in range(3):
        try:
            data = _fetch_page(1, 200)
            if not data:
                raise ValueError("返回数据为空")
            all_rows = list(data)
            print(f"[fetcher] 第1页获取 {len(data)} 条")
            break
        except Exception as e:
            print(f"[fetcher] 获取快照失败（第{attempt+1}次）: {e}")
            if attempt < 2:
                time.sleep(2)
            else:
                return pd.DataFrame()

    page = 2
    while True:
        try:
            data = _fetch_page(page, 200)
            if not data:
                break
            all_rows.extend(data)
            print(f"[fetcher] 第{page}页获取 {len(data)} 条，累计 {len(all_rows)} 条")
            if len(data) < 200:
                break
            page += 1
            time.sleep(0.1)
        except Exception as e:
            print(f"[fetcher] 第{page}页失败: {e}")
            break

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    print(f"[fetcher] 原始列名: {df.columns.tolist()}")

    # 列名映射
    df = df.rename(columns={
        "code":          "代码",
        "name":          "名称",
        "trade":         "最新价",
        "changepercent": "涨跌幅",
        "turnoverratio": "换手率",
    })

    # 总市值：mktcap 单位为亿元，直接使用
    df["总市值亿"] = pd.to_numeric(df.get("mktcap", float("nan")), errors="coerce")
    print(f"[fetcher] 总市值样本（亿）: {df['总市值亿'].describe().to_dict()}")

    # 振幅 = (最高 - 最低) / 昨收 * 100
    for c in ["high", "low", "settlement", "最新价", "涨跌幅"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["振幅"] = ((df["high"] - df["low"]) / df["settlement"].replace(0, float("nan")) * 100).round(2)

    # 换手率
    if "换手率" in df.columns:
        df["换手率"] = pd.to_numeric(df["换手率"], errors="coerce")
    else:
        df["换手率"] = float("nan")

    # 量比无字段，默认1.0，后续从历史K线更新
    df["量比"] = 1.0

    required = ["代码", "名称", "最新价", "涨跌幅", "振幅", "总市值亿"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(f"[fetcher] 缺少列: {missing}")
        return pd.DataFrame()

    # 过滤
    df = df[~df["名称"].str.contains("ST", na=False)]
    df = df[~df["代码"].astype(str).str.startswith(("688", "4", "8"))]
    # 市值范围：50亿 ~ 500亿（单位亿）
    df = df[(df["总市值亿"] >= 50) & (df["总市值亿"] <= 500)]
    df = df[df["最新价"] > 0]
    df = df.dropna(subset=["最新价", "涨跌幅", "振幅"])
    df = df.reset_index(drop=True)
    print(f"[fetcher] 过滤后剩余 {len(df)} 只")
    return df


def get_hist_k(symbol: str, days: int = 60) -> pd.DataFrame:
    code = str(symbol).zfill(6)
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": f"{prefix}{code}", "scale": 240, "ma": "no", "datalen": days}
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return pd.DataFrame()
            df = pd.DataFrame(data)
            df = df.rename(columns={"d": "日期", "o": "开盘", "c": "收盘",
                                     "h": "最高", "l": "最低", "v": "成交量"})
            for c in ["开盘", "收盘", "最高", "最低", "成交量"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            return df
        except Exception as e:
            print(f"[fetcher] K线 {symbol} 失败（第{attempt+1}次）: {e}")
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
