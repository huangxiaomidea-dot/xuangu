"""
14:40 尾盘选股器 — 主入口
"""

import sys, os, yaml
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src import fetcher, factors, backtest, reporter


def main():
    print("=" * 50)
    print("=== 14:40 尾盘选股开始 ===")
    print(f"=== 运行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    print("=" * 50)
    with open(os.path.join(ROOT, "config.yaml"), "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    print("\n[步骤1] 获取全A实时快照...")
    snap = fetcher.get_realtime_snapshot()
    if snap.empty: sys.exit(1)
    print(f"[main] 获取到 {len(snap)} 条数据")

    print("\n[步骤2] 预筛选 + 历史K线...")
    pre = snap[(snap["涨跌幅"] >= cfg["factors"]["change_pct_min"]) &
               (snap["涨跌幅"] <= cfg["factors"]["change_pct_max"]) &
               (snap["量比"]   >= cfg["factors"]["volume_ratio_min"])]
    print(f"[main] 初筛 {len(pre)} 只候选股")
    hist = fetcher.batch_get_hist(pre["代码"].astype(str).str.zfill(6).tolist()) if not pre.empty else {}

    print("\n[步骤3] 计算因子概率分...")
    top10 = factors.compute_scores(snap, hist, top_n=10)
    if top10.empty:
        reporter.generate_report(top10, datetime.now().strftime("%Y-%m-%d"))
        print("=== 完成（无候选股）==="); return

    cols = [c for c in ["代码","名称","最新价","涨跌幅","量比","换手率","振幅","概率分","命中因子"] if c in top10.columns]
    print(top10[cols].to_string())
    print(f"\n[main] TOP3：{top10.head(3)['名称'].tolist()}")

    print("\n[步骤4] 历史回测...")
    backtest.backtest_check(hist, cfg)

    print("\n[步骤5] 生成报告...")
    date_str = datetime.now().strftime("%Y-%m-%d")
    rpt = reporter.generate_report(top10, date_str)

    fw = cfg.get("feishu_webhook", "").strip()
    if fw: reporter.push_feishu(fw, top10.head(3), date_str)

    print("\n" + "=" * 50)
    print("=== 完成 ===")
    print(f"=== 报告：{rpt} ===")
    print("=" * 50)


if __name__ == "__main__":
    main()
