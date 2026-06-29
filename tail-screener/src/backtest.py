"""
历史回测模块
"""

import pandas as pd


def backtest_check(hist_dict, config=None):
    if not hist_dict:
        print("[backtest] 无历史数据，跳过")
        return None
    pct_min, pct_max, vr_min = 3.0, 5.0, 1.0
    if config:
        f = config.get("factors", {})
        pct_min, pct_max, vr_min = f.get("change_pct_min", 3.0), f.get("change_pct_max", 5.0), f.get("volume_ratio_min", 1.0)
    win = total = 0
    for sym, df in hist_dict.items():
        if df.empty or len(df) < 7: continue
        cc = next((c for c in ["收盘","close","Close"] if c in df.columns), None)
        vc = next((c for c in ["成交量","volume","Volume"] if c in df.columns), None)
        pc = next((c for c in ["涨跌幅","pct_chg"] if c in df.columns), None)
        if not cc or not vc: continue
        cl = pd.to_numeric(df[cc], errors="coerce")
        vl = pd.to_numeric(df[vc], errors="coerce")
        pt = pd.to_numeric(df[pc], errors="coerce") if pc else cl.pct_change()*100
        for i in range(5, len(df)-1):
            dp = pt.iloc[i]
            if pd.isna(dp): continue
            vm5 = vl.iloc[i-5:i].mean()
            if vm5 <= 0 or pd.isna(vm5): continue
            if pct_min <= dp <= pct_max and vl.iloc[i]/vm5 >= vr_min:
                np_ = pt.iloc[i+1]
                if pd.isna(np_): continue
                total += 1
                if np_ > 0: win += 1
    if total == 0:
        print("[backtest] 样本不足")
        return None
    wr = win/total
    print(f"[backtest] 历史回测参考胜率：{wr*100:.1f}%（{total}个样本）")
    if wr < 0.55: print("[backtest] ⚠️ 警告：胜率不足55%，建议暂停实盘")
    return wr
