"""
因子计算与概率评分模块
基于实时快照 + 历史K线，计算各因子得分，输出TOP10候选股
"""

import pandas as pd
import numpy as np
import yaml
import os


def load_config() -> dict:
    """加载配置文件"""
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def compute_scores(
    snapshot_df: pd.DataFrame,
    hist_dict: dict = None,
    top_n: int = 10,
) -> pd.DataFrame:
    """
    计算每只股票的概率评分，返回 TOP N 候选股（降序排列）。

    参数：
        snapshot_df : get_realtime_snapshot() 返回的DataFrame
        hist_dict   : {股票代码: 历史K线DataFrame}，可选
        top_n       : 返回前N名

    评分因子（满分100）：
        涨幅在3%~5%        权重15
        量比>=1.0          权重10
        换手率5%~10%       权重10
        振幅<=8%           权重10
        市值在范围内        权重15（已在fetcher过滤，此处给满分）
        股价>MA20          权重20（需hist_dict）
        成交量>VOL_MA5*0.6  权重20（需hist_dict）
    """
    if snapshot_df.empty:
        print("[factors] 快照数据为空，跳过因子计算")
        return pd.DataFrame()

    cfg = load_config()
    f = cfg["factors"]
    w = cfg["weights"]

    df = snapshot_df.copy()

    # --- 基于快照的因子 ---

    # 因子1：涨幅在 change_pct_min ~ change_pct_max
    df["f_change_pct"] = (
        (df["涨跌幅"] >= f["change_pct_min"]) &
        (df["涨跌幅"] <= f["change_pct_max"])
    ).astype(float)

    # 因子2：量比 >= volume_ratio_min
    df["f_volume_ratio"] = (df["量比"] >= f["volume_ratio_min"]).astype(float)

    # 因子3：换手率在 turnover_min ~ turnover_max
    df["f_turnover"] = (
        (df["换手率"] >= f["turnover_min"]) &
        (df["换手率"] <= f["turnover_max"])
    ).astype(float)

    # 因子4：振幅 <= amplitude_max
    df["f_amplitude"] = (df["振幅"] <= f["amplitude_max"]).astype(float)

    # 因子5：市值已在fetcher中过滤，此处直接给满分
    df["f_market_cap_fit"] = 1.0

    # --- 基于历史K线的因子（需hist_dict）---
    df["f_above_ma20"] = np.nan
    df["f_vol_gt_ma5"] = np.nan

    if hist_dict:
        for idx, row in df.iterrows():
            sym = str(row["代码"]).zfill(6)
            hist = hist_dict.get(sym)
            if hist is None or hist.empty:
                continue

            # 找收盘价列
            close_col = None
            for c in ["收盘", "close", "Close"]:
                if c in hist.columns:
                    close_col = c
                    break
            # 找成交量列
            vol_col = None
            for c in ["成交量", "volume", "Volume"]:
                if c in hist.columns:
                    vol_col = c
                    break

            if close_col is None:
                print(f"[factors] {sym} 历史数据无收盘价列，跳过MA20因子，列名: {hist.columns.tolist()}")
            else:
                closes = pd.to_numeric(hist[close_col], errors="coerce").dropna()
                if len(closes) >= 20:
                    ma20 = closes.iloc[-20:].mean()
                    current_price = row["最新价"]
                    df.at[idx, "f_above_ma20"] = 1.0 if current_price > ma20 else 0.0
                else:
                    print(f"[factors] {sym} 历史数据不足20日，跳过MA20")

            if vol_col is None:
                print(f"[factors] {sym} 历史数据无成交量列，跳过VOL_MA5因子")
            else:
                vols = pd.to_numeric(hist[vol_col], errors="coerce").dropna()
                if len(vols) >= 5:
                    vol_ma5 = vols.iloc[-5:].mean()
                    # 当日成交量从快照取（单位需一致，akshare快照成交量单位为手）
                    cur_vol_col = None
                    for c in ["成交量", "volume"]:
                        if c in df.columns:
                            cur_vol_col = c
                            break
                    if cur_vol_col:
                        cur_vol = pd.to_numeric(row.get(cur_vol_col, 0), errors="coerce")
                        ratio = f["vol_gt_ma5_ratio"]
                        df.at[idx, "f_vol_gt_ma5"] = 1.0 if cur_vol > vol_ma5 * ratio else 0.0
    else:
        print("[factors] 未提供历史K线数据，MA20和VOL_MA5因子将跳过")

    # 若无历史数据，对缺失因子用0.5中性填充，避免全0惩罚
    df["f_above_ma20"] = df["f_above_ma20"].fillna(0.5)
    df["f_vol_gt_ma5"] = df["f_vol_gt_ma5"].fillna(0.5)

    # --- 加权概率分（满分100） ---
    df["概率分"] = (
        df["f_change_pct"]      * w["change_pct"]      * 100 +
        df["f_volume_ratio"]    * w["volume_ratio"]     * 100 +
        df["f_turnover"]        * w["turnover"]         * 100 +
        df["f_amplitude"]       * w["amplitude"]        * 100 +
        df["f_above_ma20"]      * w["above_ma20"]       * 100 +
        df["f_vol_gt_ma5"]      * w["vol_gt_ma5"]       * 100 +
        df["f_market_cap_fit"]  * w["market_cap_fit"]   * 100
    ).round(1)

    # 命中因子简述（用于报告）
    def hit_desc(row):
        hits = []
        if row["f_change_pct"] == 1:
            hits.append(f"涨幅{row['涨跌幅']:.1f}%")
        if row["f_volume_ratio"] == 1:
            hits.append(f"量比{row['量比']:.1f}")
        if row["f_turnover"] == 1:
            hits.append(f"换手{row['换手率']:.1f}%")
        if row["f_amplitude"] == 1:
            hits.append(f"振幅{row['振幅']:.1f}%")
        if row["f_above_ma20"] == 1:
            hits.append("站上MA20")
        if row["f_vol_gt_ma5"] == 1:
            hits.append("量能放大")
        return "、".join(hits) if hits else "无"

    df["命中因子"] = df.apply(hit_desc, axis=1)

    # 只保留核心基本面因子全部达标的股票（涨幅+量比必须满足）
    df_qualified = df[
        (df["f_change_pct"] == 1) & (df["f_volume_ratio"] == 1)
    ].copy()

    if df_qualified.empty:
        print("[factors] 无股票同时满足涨幅+量比条件，放宽只按概率分排序")
        df_qualified = df.copy()

    top_df = df_qualified.sort_values("概率分", ascending=False).head(top_n)
    top_df = top_df.reset_index(drop=True)
    top_df.index += 1  # 排名从1开始

    return top_df
