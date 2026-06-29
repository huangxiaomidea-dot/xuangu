"""
简单历史回测模块
统计近60日内符合因子条件的股票，次日上涨的比例（胜率）
严禁使用未来数据：仅用截至当日收盘的数据判断条件，看次日涨跌
"""

import pandas as pd
import numpy as np


def backtest_check(hist_dict: dict, config: dict = None) -> float:
    """
    简单回测：对每只股票的历史K线，逐日扫描。
    若当日满足「涨幅3%~5% 且 量比>1（用成交量/5日均量模拟）」，
    则记录次日涨跌，统计次日上涨比例（胜率）。

    参数：
        hist_dict : {symbol: DataFrame}，历史日K数据
        config    : 配置字典（可选）

    返回：胜率浮点数（0~1），无样本时返回 None
    """
    if not hist_dict:
        print("[backtest] 无历史数据，跳过回测")
        return None

    # 因子阈值
    pct_min = 3.0
    pct_max = 5.0
    vol_ratio_min = 1.0
    if config:
        f = config.get("factors", {})
        pct_min = f.get("change_pct_min", pct_min)
        pct_max = f.get("change_pct_max", pct_max)
        vol_ratio_min = f.get("volume_ratio_min", vol_ratio_min)

    win = 0
    total = 0

    for sym, df in hist_dict.items():
        if df.empty or len(df) < 7:
            continue

        # 找列名
        close_col = next((c for c in ["收盘", "close", "Close"] if c in df.columns), None)
        vol_col   = next((c for c in ["成交量", "volume", "Volume"] if c in df.columns), None)
        pct_col   = next((c for c in ["涨跌幅", "pct_chg"] if c in df.columns), None)

        if close_col is None or vol_col is None:
            continue

        closes = pd.to_numeric(df[close_col], errors="coerce")
        vols   = pd.to_numeric(df[vol_col],   errors="coerce")

        # 如果有涨跌幅列直接用，否则自行计算
        if pct_col:
            pcts = pd.to_numeric(df[pct_col], errors="coerce")
        else:
            pcts = closes.pct_change() * 100

        # 从第5日开始（确保有5日均量），到倒数第2日（次日还有数据）
        for i in range(5, len(df) - 1):
            day_pct = pcts.iloc[i]
            if pd.isna(day_pct):
                continue

            # 用前5日均量模拟量比（无实时量比，近似处理）
            vol_ma5 = vols.iloc[i-5:i].mean()
            if vol_ma5 <= 0 or pd.isna(vol_ma5):
                continue
            approx_vol_ratio = vols.iloc[i] / vol_ma5

            # 判断当日是否满足因子条件（严禁用当日之后的数据）
            if (pct_min <= day_pct <= pct_max) and (approx_vol_ratio >= vol_ratio_min):
                # 次日涨跌
                next_pct = pcts.iloc[i + 1]
                if pd.isna(next_pct):
                    continue
                total += 1
                if next_pct > 0:
                    win += 1

    if total == 0:
        print("[backtest] 回测样本不足，无法统计胜率（可能近期满足条件的天数太少）")
        return None

    win_rate = win / total
    print(f"[backtest] 历史回测参考胜率：{win_rate*100:.1f}%（基于近60日 {total} 个样本）")

    if win_rate < 0.55:
        print("[backtest] ⚠️ 警告：当前因子组合历史胜率不足55%，建议暂停实盘")

    return win_rate
