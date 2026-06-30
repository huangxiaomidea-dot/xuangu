"""
因子计算与概率评分模块
注：新浪接口无量比字段，量比因子需从历史K线计算
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

    # 因子1：涨幅在3%~5%
    df["f_change_pct"] = ((df["涨跌幅"] >= f["change_pct_min"]) & (df["涨跌幅"] <= f["change_pct_max"])).astype(float)

    # 因子2：量比（新浪无此字段，从历史K线算近似量比）
    df["f_volume_ratio"] = 0.5  # 默认中性分

    # 因子3：换手率（新浪有时有此字段）
    if "换手率" in df.columns and df["换手率"].notna().any():
        df["f_turnover"] = ((df["换手率"] >= f["turnover_min"]) & (df["换手率"] <= f["turnover_max"])).astype(float)
    else:
        df["f_turnover"] = 0.5

    # 因子4：振幅 <= 8%
    df["f_amplitude"] = (df["振幅"] <= f["amplitude_max"]).astype(float)

    # 因子5：市值已过滤，满分
    df["f_market_cap_fit"] = 1.0

    # 因子6/7：MA20 和 VOL_MA5（从历史K线计算）
    df["f_above_ma20"] = np.nan
    df["f_vol_gt_ma5"] = np.nan

    if hist_dict:
        for idx, row in df.iterrows():
            hist = hist_dict.get(str(row["代码"]).zfill(6))
            if hist is None or hist.empty:
                continue
            cc = next((c for c in ["收盘", "close", "Close"] if c in hist.columns), None)
            vc = next((c for c in ["成交量", "volume", "Volume"] if c in hist.columns), None)

            if cc:
                cl = pd.to_numeric(hist[cc], errors="coerce").dropna()
                if len(cl) >= 20:
                    df.at[idx, "f_above_ma20"] = 1.0 if row["最新价"] > cl.iloc[-20:].mean() else 0.0
                # 用历史K线算近似量比（当日成交量/5日均量）
                if vc and len(hist) >= 6:
                    vl = pd.to_numeric(hist[vc], errors="coerce").dropna()
                    if len(vl) >= 6:
                        vol_ma5 = vl.iloc[-6:-1].mean()
                        cur_vol  = vl.iloc[-1]
                        if vol_ma5 > 0:
                            approx_vr = cur_vol / vol_ma5
                            df.at[idx, "f_volume_ratio"] = 1.0 if approx_vr >= f["volume_ratio_min"] else 0.0
                            df.at[idx, "f_vol_gt_ma5"]   = 1.0 if cur_vol > vol_ma5 * f["vol_gt_ma5_ratio"] else 0.0

    df["f_above_ma20"]   = df["f_above_ma20"].fillna(0.5)
    df["f_vol_gt_ma5"]   = df["f_vol_gt_ma5"].fillna(0.5)
    df["f_volume_ratio"] = df["f_volume_ratio"].fillna(0.5)

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
        if row["f_volume_ratio"] == 1: hits.append("量能放量")
        if row["f_turnover"]     == 1: hits.append(f"换手{row.get('换手率',0):.1f}%")
        if row["f_amplitude"]    == 1: hits.append(f"振幅{row['振幅']:.1f}%")
        if row["f_above_ma20"]   == 1: hits.append("站上MA20")
        if row["f_vol_gt_ma5"]   == 1: hits.append("量能放大")
        return "、".join(hits) or "无"
    df["命中因子"] = df.apply(hit_desc, axis=1)

    # 涨幅必须达标才进入候选
    df_q = df[df["f_change_pct"] == 1].copy()
    if df_q.empty:
        df_q = df.copy()
    top = df_q.sort_values("概率分", ascending=False).head(top_n).reset_index(drop=True)
    top.index += 1
    return top
