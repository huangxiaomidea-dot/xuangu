"""
报告生成与飞书推送模块
"""

import os
import requests
import pandas as pd
from datetime import datetime


def generate_report(top_df: pd.DataFrame, date_str: str = None) -> str:
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    notes_dir = os.path.join(os.path.dirname(__file__), "..", "notes")
    os.makedirs(notes_dir, exist_ok=True)
    report_path = os.path.join(notes_dir, f"{date_str}.md")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"# 14:40 尾盘选股报告 {date_str}", "",
        f"> 生成时间：{now_str}  ",
        f"> 策略：涨幅3-5%、量比≥1、换手率5-10%、振幅≤8%、站上MA20、量能放大  ", "",
        "## TOP3 推荐", "",
        "| 排名 | 代码 | 名称 | 当前价 | 涨幅% | 振幅% | 概率分 | 命中因子 |",
        "| :--: | :--: | :--: | -----: | ----: | ----: | -----: | :------- |",
    ]
    if top_df.empty:
        lines.append("| - | - | 今日无满足条件的标的 | - | - | - | - | - |")
    else:
        for rank, (_, row) in enumerate(top_df.head(3).iterrows(), start=1):
            lines.append(f"| {rank} | {row.get('代码','-')} | {row.get('名称','-')} | {row.get('最新价',0):.2f} | {row.get('涨跌幅',0):.2f} | {row.get('振幅',0):.2f} | {row.get('概率分',0):.1f} | {row.get('命中因子','-')} |")

    lines += ["", "## TOP10 完整列表", "",
        "| 排名 | 代码 | 名称 | 涨幅% | 量比 | 换手率% | 振幅% | 概率分 |",
        "| :--: | :--: | :--: | ----: | ---: | ------: | ----: | -----: |",
    ]
    if top_df.empty:
        lines.append("| - | - | 暂无数据 | - | - | - | - | - |")
    else:
        for rank, (_, row) in enumerate(top_df.iterrows(), start=1):
            lines.append(f"| {rank} | {row.get('代码','-')} | {row.get('名称','-')} | {row.get('涨跌幅',0):.2f} | {row.get('量比',0):.2f} | {row.get('换手率',0):.2f} | {row.get('振幅',0):.2f} | {row.get('概率分',0):.1f} |")

    lines += ["", "---", "> **免责声明**：本报告仅供学习研究，不构成任何投资建议。股市有风险，投资需谨慎。"]
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[reporter] 报告已保存：{report_path}")
    return report_path


def push_feishu(webhook_url: str, top_df: pd.DataFrame, date_str: str = None) -> bool:
    if not webhook_url or not webhook_url.strip():
        return False
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    lines = [f"📊 {date_str} 14:40 尾盘选股 TOP3\n"]
    for rank, (_, row) in enumerate(top_df.head(3).iterrows(), start=1):
        lines.append(f"{rank}. {row.get('名称','-')}（{row.get('代码','-')}）涨幅{row.get('涨跌幅',0):.2f}% 概率分{row.get('概率分',0):.1f}\n   ▶ {row.get('命中因子','-')}")
    try:
        resp = requests.post(webhook_url, json={"msg_type": "text", "content": {"text": "\n".join(lines)}}, timeout=10)
        if resp.status_code == 200 and resp.json().get("code", -1) == 0:
            print("[reporter] 飞书推送成功")
            return True
    except Exception as e:
        print(f"[reporter] 飞书推送异常：{e}")
    return False
