"""
14:40 尾盘选股器 — 主入口
"""

import sys
import os
import yaml
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import fetcher, factors, backtest, reporter


def load_config():
    with open(os.path.join(ROOT, "config.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    print("=" * 50)
    print("=== 14:40 尾盘选股开始 ===")
    print(f"=== 运行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    print("=" * 50)

    try:
        cfg = load_config()
    except Exception as e:
        print(f"[main] 配置文件加载失败：{e}")
        sys.exit(1)

    print("\n[步骤1] 获取全A实时快照...")
    snapshot_df = fetcher.get_realtime_snapshot()
    if snapshot_df.empty:
        print("[main] 快照数据获取失败，程序退出")
        sys.exit(1)
    print(f"[main] 获取到 {len(snapshot_df)} 条数据")

    print("\n[步骤2] 预筛选 + 获取历史K线...")
    pre_filter = snapshot_df[
        (snapshot_df["涨跌幅"] >= cfg["factors"]["change_pct_min"]) &
        (snapshot_df["涨跌幅"] <= cfg["factors"]["change_pct_max"]) &
        (snapshot_df["量比"]   >= cfg["factors"]["volume_ratio_min"])
    ]
    print(f"[main] 快照初筛后 {len(pre_filter)} 只候选股")
    hist_dict = fetcher.batch_get_hist(pre_filter["代码"].astype(str).str.zfill(6).tolist()) if not pre_filter.empty else {}

    print("\n[步骤3] 计算因子概率分...")
    top10_df = factors.compute_scores(snapshot_df, hist_dict, top_n=10)
    if top10_df.empty:
        print("[main] 无候选股")
        reporter.generate_report(top10_df, datetime.now().strftime("%Y-%m-%d"))
        return

    display_cols = [c for c in ["代码","名称","最新价","涨跌幅","量比","换手率","振幅","概率分","命中因子"] if c in top10_df.columns]
    print(top10_df[display_cols].to_string())
    print(f"\n[main] 今日推荐 TOP3：{top10_df.head(3)['名称'].tolist()}")

    print("\n[步骤4] 历史回测...")
    backtest.backtest_check(hist_dict, cfg)

    print("\n[步骤5] 生成选股报告...")
    date_str = datetime.now().strftime("%Y-%m-%d")
    report_path = reporter.generate_report(top10_df, date_str)

    feishu_url = cfg.get("feishu_webhook", "").strip()
    if feishu_url:
        reporter.push_feishu(feishu_url, top10_df.head(3), date_str)

    print("\n" + "=" * 50)
    print("=== 完成 ===")
    print(f"=== 报告路径：{report_path} ===")
    print("=" * 50)


if __name__ == "__main__":
    main()
