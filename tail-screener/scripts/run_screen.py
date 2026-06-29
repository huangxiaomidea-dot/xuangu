"""
14:40 尾盘选股器 — 主入口
使用方法：cd tail-screener && python scripts/run_screen.py
"""

import sys
import os
import yaml
from datetime import datetime

# 将项目根目录加入路径，确保 src 模块可导入
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import fetcher, factors, backtest, reporter


def load_config() -> dict:
    config_path = os.path.join(ROOT, "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    print("=" * 50)
    print("=== 14:40 尾盘选股开始 ===")
    print(f"=== 运行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    print("=" * 50)

    # 1. 加载配置
    try:
        cfg = load_config()
    except Exception as e:
        print(f"[main] 配置文件加载失败：{e}")
        sys.exit(1)

    # 2. 获取全A实时快照
    print("\n[步骤1] 获取全A实时快照...")
    snapshot_df = fetcher.get_realtime_snapshot()
    if snapshot_df.empty:
        print("[main] 快照数据获取失败或为空，程序退出")
        sys.exit(1)
    print(f"[main] 获取到 {len(snapshot_df)} 条数据，开始计算因子...")

    # 3. 获取历史K线（TOP候选股，加速：先用快照初筛再批量拉K线）
    print("\n[步骤2] 预筛选 + 获取历史K线...")
    # 先按快照因子初筛，减少需要拉K线的股票数量
    pre_filter = snapshot_df[
        (snapshot_df["涨跌幅"] >= cfg["factors"]["change_pct_min"]) &
        (snapshot_df["涨跌幅"] <= cfg["factors"]["change_pct_max"]) &
        (snapshot_df["量比"] >= cfg["factors"]["volume_ratio_min"])
    ]
    print(f"[main] 快照初筛后 {len(pre_filter)} 只候选股，开始拉取历史K线...")

    if not pre_filter.empty:
        symbols = pre_filter["代码"].astype(str).str.zfill(6).tolist()
        hist_dict = fetcher.batch_get_hist(symbols, days=60)
    else:
        print("[main] 初筛无候选股，将对全量使用快照因子计算")
        hist_dict = {}

    # 4. 计算因子概率分，取TOP10
    print("\n[步骤3] 计算因子概率分...")
    top10_df = factors.compute_scores(snapshot_df, hist_dict, top_n=10)

    if top10_df.empty:
        print("[main] 未筛选出任何候选股，程序退出")
        date_str = datetime.now().strftime("%Y-%m-%d")
        reporter.generate_report(top10_df, date_str)
        print("\n=== 完成（无候选股） ===")
        return

    print(f"\n[main] TOP10 候选股：")
    display_cols = ["代码", "名称", "最新价", "涨跌幅", "量比", "换手率", "振幅", "概率分", "命中因子"]
    display_cols = [c for c in display_cols if c in top10_df.columns]
    print(top10_df[display_cols].to_string())

    # 5. 取TOP3
    top3_df = top10_df.head(3)
    print(f"\n[main] 今日推荐 TOP3：{top3_df['名称'].tolist()}")

    # 6. 历史回测参考胜率
    print("\n[步骤4] 历史回测...")
    backtest.backtest_check(hist_dict, cfg)

    # 7. 生成报告
    print("\n[步骤5] 生成选股报告...")
    date_str = datetime.now().strftime("%Y-%m-%d")
    report_path = reporter.generate_report(top10_df, date_str)

    # 8. 飞书推送
    feishu_url = cfg.get("feishu_webhook", "").strip()
    if feishu_url:
        print("\n[步骤6] 推送飞书通知...")
        reporter.push_feishu(feishu_url, top3_df, date_str)
    else:
        print("\n[步骤6] 未配置飞书 Webhook，跳过推送（可在 config.yaml 中填入 feishu_webhook）")

    print("\n" + "=" * 50)
    print("=== 完成 ===")
    print(f"=== 报告路径：{report_path} ===")
    print("=" * 50)


if __name__ == "__main__":
    main()
