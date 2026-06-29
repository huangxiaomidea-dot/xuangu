"""
因子计算与概率评分模块
"""

import pandas as pd
import numpy as np
import yaml
import os


def load_config():
    with open(os.path.join(os.path.dirname(__file__), "..", "config.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def compute_scores(snapshot_df, hist_dict=None, top_n=10):
    if snapshot_df.empty:
        return pd.DataFrame()
    cfg = load_config()
    f, w = cfg["factors"], cfg["weights"]
    df = snapshot_df.copy()

    df["f_change_pct"]     = ((df["涨跌幅"] >= f["change_pct_min"]) & (df["涨跌幅"] <= f["change_pct_max"])).astype(float)
    df["f_volume_ratio"]   = (df["量比"] >= f["volume_ratio_min"]).astype(float)
    df["f_turnover"]       = ((df["换手率"] >= f["turnover_min"]) & (df["换手率"] <= f["turnover_max"])).astype(float)
    df["f_amplitude"]      = (df["振幅"] <= f["amplitude_max"]).astype(float)
    df["f_market_cap_fit"] = 1.0
    df["f_above_ma20"] = np.nan
    df["f_vol_gt_ma5"]  = np.nan

    if hist_dict:
        for idx, row in df.iterrows():
            hist = hist_dict.get(str(row["代码"]).zfill(6))
            if hist is None or hist.empty:
                continue
            cc = next((c for c in ["收盘","close","Close"] if c in hist.columns), None)
            vc = next((c for c in ["成交量","volume","Volume"] if c in hist.columns), None)
            if cc:
                cl = pd.to_numeric(hist[cc], errors="coerce").dropna()
                if len(cl) >= 20:
                    df.at[idx, "f_above_ma20"] = 1.0 if row["最新价"] > cl.iloc[-20:].mean() else 0.0
            if vc:
                vl = pd.to_numeric(hist[vc], errors="coerce").dropna()
                cvc = next((c for c in ["成交量","volume"] if c in df.columns), None)
                if len(vl) >= 5 and cvc:
                    df.at[idx, "f_vol_gt_ma5"] = 1.0 if pd.to_numeric(row.get(cvc,0), errors="coerce") > vl.iloc[-5:].mean() * f["vol_gt_ma5_ratio"] else 0.0

    df["f_above_ma20"] = df["f_above_ma20"].fillna(0.5)
    df["f_vol_gt_ma5"]  = df["f_vol_gt_ma5"].fillna(0.5)

    df["概率分"] = (
        df["f_change_pct"]     * w["change_pct"]     * 100 +
        df["f_volume_ratio"]   * w["volume_ratio"]   * 100 +
        df["f_turnover"]       * w["turnover"]       * 100 +
        df["f_amplitude"]      * w["amplitude"]      * 100 +
        df["f_above_ma20"]     * w["above_ma20"]     * 100 +
        df["f_vol_gt_ma5"]     * w["vol_gt_ma5"]     * 100 +
        df["f_market_cap_fit"] * w["market_cap_fit"] * 100
    ).round(1)

    def hit_desc(row):
        hits = []
        if row["f_change_pct"]   == 1: hits.append(f"涨幅{row['涨跌幅']:.1f}%")
        if row["f_volume_ratio"] == 1: hits.append(f"量比{row['量比']:.1f}")
        if row["f_turnover"]     == 1: hits.append(f"换手{row['换手率']:.1f}%")
        if row["f_amplitude"]    == 1: hits.append(f"振幅{row['振幅']:.1f}%")
        if row["f_above_ma20"]   == 1: hits.append("站上MA20")
        if row["f_vol_gt_ma5"]   == 1: hits.append("量能放大")
        return "、".join(hits) or "无"
    df["命中因子"] = df.apply(hit_desc, axis=1)

    df_q = df[(df["f_change_pct"]==1) & (df["f_volume_ratio"]==1)].copy()
    if df_q.empty: df_q = df.copy()
    top = df_q.sort_values("概率分", ascending=False).head(top_n).reset_index(drop=True)
    top.index += 1
    return top
