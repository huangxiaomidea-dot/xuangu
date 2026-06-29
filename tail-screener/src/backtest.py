"""
历史回测模块 — 统计近60日胜率
"""

import pandas as pd


def backtest_check(hist_dict: dict, config: dict = None) -> float:
    if not hist_dict:
        print("[backtest] 无历史数据，跳过回测")
        return None

    pct_min, pct_max, vol_ratio_min = 3.0, 5.0, 1.0
    if config:
        f = config.get("factors", {})
        pct_min       = f.get("change_pct_min", pct_min)
        pct_max       = f.get("change_pct_max", pct_max)
        vol_ratio_min = f.get("volume_ratio_min", vol_ratio_min)

    win = total = 0
    for sym, df in hist_dict.items():
        if df.empty or len(df) < 7:
            continue
        close_col = next((c for c in ["收盘", "close", "Close"] if c in df.columns), None)
        vol_col   = next((c for c in ["成交量", "volume", "Volume"] if c in df.columns), None)
        pct_col   = next((c for c in ["涨跌幅", "pct_chg"] if c in df.columns), None)
        if not close_col or not vol_col:
            continue
        closes = pd.to_numeric(df[close_col], errors="coerce")
        vols   = pd.to_numeric(df[vol_col],   errors="coerce")
        pcts   = pd.to_numeric(df[pct_col], errors="coerce") if pct_col else closes.pct_change() * 100
        for i in range(5, len(df) - 1):
            day_pct = pcts.iloc[i]
            if pd.isna(day_pct):
                continue
            vol_ma5 = vols.iloc[i-5:i].mean()
            if vol_ma5 <= 0 or pd.isna(vol_ma5):
                continue
            if (pct_min <= day_pct <= pct_max) and (vols.iloc[i] / vol_ma5 >= vol_ratio_min):
                next_pct = pcts.iloc[i + 1]
                if pd.isna(next_pct):
                    continue
                total += 1
                if next_pct > 0:
                    win += 1

    if total == 0:
        print("[backtest] 回测样本不足")
        return None
    win_rate = win / total
    print(f"[backtest] 历史回测参考胜率：{win_rate*100:.1f}%（基于近60日 {total} 个样本）")
    if win_rate < 0.55:
        print("[backtest] ⚠️ 警告：当前因子组合历史胜率不足55%，建议暂停实盘")
    return win_rate
