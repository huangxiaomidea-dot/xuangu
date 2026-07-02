"""
因子评分模块
目标：14:40尾盘选股，预测次日开盘前5分钟上涨概率最大的股票

关键因子：
  - 收盘强度：(最新价-最低) / (最高-最低) ≥ 0.7（尾盘收在当日区间上70%）
  - 上影线短：(最高-最新价) / 最新价 < 2%（上方压力小）
  - 量比 ≥ 1.5，均线多头排列
"""

import pandas as pd
import numpy as np
import yaml
import os


def load_config() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def compute_scores(snapshot_df: pd.DataFrame, hist_dict: dict = None, top_n: int = 10) -> pd.DataFrame:
    if snapshot_df.empty:
        return pd.DataFrame()

    cfg = load_config()
    f = cfg["factors"]
    w = cfg["weights"]
    df = snapshot_df.copy()

    # 用历史K线计算真实量比
    if hist_dict:
        for idx, row in df.iterrows():
            sym = str(row["代码"]).zfill(6)
            hist = hist_dict.get(sym)
            if hist is None or hist.empty:
                continue
            vol_col = next((c for c in ["成交量", "volume"] if c in hist.columns), None)
            cur_vol_col = next((c for c in ["成交量", "volume"] if c in df.columns), None)
            if vol_col and cur_vol_col and len(hist) >= 6:
                vols = pd.to_numeric(hist[vol_col], errors="coerce").dropna()
                vol_ma5 = vols.iloc[-6:-1].mean()
                cur_vol = pd.to_numeric(row.get(cur_vol_col, 0), errors="coerce")
                if vol_ma5 > 0:
                    df.at[idx, "量比"] = round(cur_vol / vol_ma5, 2)

    # 因子1：涨幅 2%~7%
    df["f_change_pct"] = (
        (df["涨跌幅"] >= f["change_pct_min"]) &
        (df["涨跌幅"] <= f["change_pct_max"])
    ).astype(float)

    # 因子2：量比 >= 1.5
    df["f_volume_ratio"] = (df["量比"] >= f["volume_ratio_min"]).astype(float)

    # 因子3：收盘强度 = (最新价-最低) / (最高-最低) ≥ 0.7
    price_range = df["最高"] - df["最低"]
    close_strength = (df["最新价"] - df["最低"]) / price_range.replace(0, np.nan)
    df["f_close_strength"] = (close_strength >= f["close_strength_min"]).astype(float)
    df["收盘强度"] = close_strength.round(2)

    # 因子4：上影线短 = (最高-最新价) / 最新价 < 2%
    upper_shadow = (df["最高"] - df["最新价"]) / df["最新价"] * 100
    df["f_upper_shadow"] = (upper_shadow <= f["upper_shadow_max"]).astype(float)
    df["上影线%"] = upper_shadow.round(2)

    # 历史K线因子
    df["f_ma_trend"]   = np.nan
    df["f_above_ma20"] = np.nan
    df["f_vol_gt_ma5"] = np.nan

    if hist_dict:
        for idx, row in df.iterrows():
            sym = str(row["代码"]).zfill(6)
            hist = hist_dict.get(sym)
            if hist is None or hist.empty:
                continue
            close_col = next((c for c in ["收盘", "close"] if c in hist.columns), None)
            vol_col   = next((c for c in ["成交量", "volume"] if c in hist.columns), None)
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
                cur_vol_col = next((c for c in ["成交量", "volume"] if c in df.columns), None)
                if cur_vol_col and len(vols) >= 5:
                    vol_ma5 = vols.iloc[-5:].mean()
                    cur_vol = pd.to_numeric(row.get(cur_vol_col, 0), errors="coerce")
                    if vol_ma5 > 0:
                        df.at[idx, "f_vol_gt_ma5"] = 1.0 if cur_vol > vol_ma5 else 0.0

    df["f_ma_trend"]   = df["f_ma_trend"].fillna(0.5)
    df["f_above_ma20"] = df["f_above_ma20"].fillna(0.5)
    df["f_vol_gt_ma5"] = df["f_vol_gt_ma5"].fillna(0.5)

    df["概率分"] = (
        df["f_change_pct"]    * w["change_pct"]    * 100 +
        df["f_volume_ratio"]  * w["volume_ratio"]  * 100 +
        df["f_close_strength"]* w["close_strength"] * 100 +
        df["f_upper_shadow"]  * w["upper_shadow"]   * 100 +
        df["f_ma_trend"]      * w["ma_trend"]       * 100 +
        df["f_above_ma20"]    * w["above_ma20"]     * 100 +
        df["f_vol_gt_ma5"]    * w["vol_gt_ma5"]     * 100
    ).round(1)

    def hit_desc(row):
        hits = []
        if row["f_change_pct"] == 1:     hits.append(f"涨幅{row['涨跌幅']:.1f}%")
        if row["f_volume_ratio"] == 1:   hits.append(f"量比{row['量比']:.1f}")
        if row["f_close_strength"] == 1: hits.append(f"收盘强度{row['收盘强度']:.0%}")
        if row["f_upper_shadow"] == 1:   hits.append(f"上影{row['上影线%']:.1f}%")
        if row["f_above_ma20"] == 1:     hits.append("站上MA20")
        if row["f_ma_trend"] == 1:       hits.append("均线多头")
        if row["f_vol_gt_ma5"] == 1:     hits.append("量能放大")
        return "、".join(hits) if hits else "无"

    df["命中因子"] = df.apply(hit_desc, axis=1)

    # 必须同时满足：涨幅达标 + 量比达标
    df_q = df[(df["f_change_pct"] == 1) & (df["f_volume_ratio"] == 1)].copy()
    if df_q.empty:
        df_q = df[df["f_change_pct"] == 1].copy()
    if df_q.empty:
        df_q = df.copy()

    top_df = df_q.sort_values("概率分", ascending=False).head(top_n).reset_index(drop=True)
    top_df.index += 1
    return top_df
