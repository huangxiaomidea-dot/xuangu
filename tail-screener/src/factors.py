"""
因子计算与概率评分模块
策略：均线多头排列（MA5>MA10>MA20）+ 量价双击，目标胜率 60%+
"""

import pandas as pd
import numpy as np
import yaml
import os


def load_config() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def compute_scores(
    snapshot_df: pd.DataFrame,
    hist_dict: dict = None,
    top_n: int = 10,
) -> pd.DataFrame:
    """
    评分因子（满分100）：
        涨幅 2%~7%           权重15
        量比 >= 1.5          权重20
        换手率 3%~10%        权重 5
        振幅 <= 8%           权重 5
        股价 > MA20          权重20
        MA5 > MA10 > MA20    权重20（多头排列）
        成交量 > VOL_MA5      权重15
    """
    if snapshot_df.empty:
        print("[factors] 快照数据为空，跳过因子计算")
        return pd.DataFrame()

    cfg = load_config()
    f = cfg["factors"]
    w = cfg["weights"]

    df = snapshot_df.copy()

    # 先用历史K线计算真实量比（当日成交量 / 5日均量）
    if hist_dict:
        for idx, row in df.iterrows():
            sym = str(row["代码"]).zfill(6)
            hist = hist_dict.get(sym)
            if hist is None or hist.empty:
                continue
            vol_col = next((c for c in ["成交量", "volume", "Volume"] if c in hist.columns), None)
            if vol_col and len(hist) >= 6:
                vols = pd.to_numeric(hist[vol_col], errors="coerce").dropna()
                vol_ma5 = vols.iloc[-6:-1].mean()  # 历史最近5日均量
                cur_vol_col = next((c for c in ["成交量", "volume"] if c in df.columns), None)
                if cur_vol_col and vol_ma5 > 0:
                    cur_vol = pd.to_numeric(row.get(cur_vol_col, 0), errors="coerce")
                    # 新浪实时接口成交量单位为「手」，历史K线成交量单位为「手」，直接比较
                    real_vr = cur_vol / vol_ma5
                    df.at[idx, "量比"] = round(real_vr, 2)

    # 因子1：涨幅
    df["f_change_pct"] = (
        (df["涨跌幅"] >= f["change_pct_min"]) &
        (df["涨跌幅"] <= f["change_pct_max"])
    ).astype(float)

    # 因子2：量比 >= 1.5（用真实量比）
    df["f_volume_ratio"] = (df["量比"] >= f["volume_ratio_min"]).astype(float)

    # 因子3：换手率
    df["f_turnover"] = (
        (df["换手率"] >= f["turnover_min"]) &
        (df["换手率"] <= f["turnover_max"])
    ).astype(float)

    # 因子4：振幅
    df["f_amplitude"] = (df["振幅"] <= f["amplitude_max"]).astype(float)

    # 历史K线因子
    df["f_above_ma20"] = np.nan
    df["f_ma_trend"]   = np.nan
    df["f_vol_gt_ma5"] = np.nan

    if hist_dict:
        for idx, row in df.iterrows():
            sym = str(row["代码"]).zfill(6)
            hist = hist_dict.get(sym)
            if hist is None or hist.empty:
                continue

            close_col = next((c for c in ["收盘", "close", "Close"] if c in hist.columns), None)
            vol_col   = next((c for c in ["成交量", "volume", "Volume"] if c in hist.columns), None)

            if close_col:
                closes = pd.to_numeric(hist[close_col], errors="coerce").dropna()
                if len(closes) >= 20:
                    ma5  = closes.iloc[-5:].mean()
                    ma10 = closes.iloc[-10:].mean()
                    ma20 = closes.iloc[-20:].mean()
                    cur  = row["最新价"]
                    df.at[idx, "f_above_ma20"] = 1.0 if cur > ma20 else 0.0
                    df.at[idx, "f_ma_trend"]   = 1.0 if (ma5 > ma10 > ma20) else 0.0

            if vol_col:
                vols = pd.to_numeric(hist[vol_col], errors="coerce").dropna()
                if len(vols) >= 5:
                    vol_ma5 = vols.iloc[-5:].mean()
                    cur_vol_col = next((c for c in ["成交量", "volume"] if c in df.columns), None)
                    if cur_vol_col and vol_ma5 > 0:
                        cur_vol = pd.to_numeric(row.get(cur_vol_col, 0), errors="coerce")
                        df.at[idx, "f_vol_gt_ma5"] = 1.0 if cur_vol > vol_ma5 else 0.0
    else:
        print("[factors] 未提供历史K线，MA/量能因子将中性填充")

    df["f_above_ma20"] = df["f_above_ma20"].fillna(0.5)
    df["f_ma_trend"]   = df["f_ma_trend"].fillna(0.5)
    df["f_vol_gt_ma5"] = df["f_vol_gt_ma5"].fillna(0.5)

    # 加权概率分
    df["概率分"] = (
        df["f_change_pct"]   * w["change_pct"]   * 100 +
        df["f_volume_ratio"] * w["volume_ratio"]  * 100 +
        df["f_turnover"]     * w["turnover"]      * 100 +
        df["f_amplitude"]    * w["amplitude"]     * 100 +
        df["f_above_ma20"]   * w["above_ma20"]    * 100 +
        df["f_ma_trend"]     * w["ma_trend"]      * 100 +
        df["f_vol_gt_ma5"]   * w["vol_gt_ma5"]    * 100
    ).round(1)

    def hit_desc(row):
        hits = []
        if row["f_change_pct"] == 1:   hits.append(f"涨幅{row['涨跌幅']:.1f}%")
        if row["f_volume_ratio"] == 1:  hits.append(f"量比{row['量比']:.1f}")
        if row["f_turnover"] == 1:      hits.append(f"换手{row['换手率']:.1f}%")
        if row["f_amplitude"] == 1:     hits.append(f"振幅{row['振幅']:.1f}%")
        if row["f_above_ma20"] == 1:    hits.append("站上MA20")
        if row["f_ma_trend"] == 1:      hits.append("均线多头")
        if row["f_vol_gt_ma5"] == 1:    hits.append("量能放大")
        return "、".join(hits) if hits else "无"

    df["命中因子"] = df.apply(hit_desc, axis=1)

    # 必须同时满足：涨幅达标 + 量比达标
    df_qualified = df[
        (df["f_change_pct"] == 1) & (df["f_volume_ratio"] == 1)
    ].copy()

    if df_qualified.empty:
        print("[factors] 无股票同时满足涨幅+量比，放宽仅按涨幅过滤")
        df_qualified = df[df["f_change_pct"] == 1].copy()

    if df_qualified.empty:
        print("[factors] 无涨幅达标股票，放宽全量排序")
        df_qualified = df.copy()

    top_df = df_qualified.sort_values("概率分", ascending=False).head(top_n)
    top_df = top_df.reset_index(drop=True)
    top_df.index += 1
    return top_df
