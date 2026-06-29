"""
报告生成与飞书推送模块
"""

import os
import requests
import pandas as pd
from datetime import datetime


def generate_report(top_df: pd.DataFrame, date_str: str = None) -> str:
    """
    生成 Markdown 选股报告，保存到 notes/YYYY-MM-DD.md。

    参数：
        top_df   : 含排名、代码、名称、涨跌幅、振幅、概率分、命中因子的DataFrame
        date_str : 日期字符串，默认今日

    返回：报告文件路径
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # 确保 notes/ 目录存在（相对于项目根目录）
    notes_dir = os.path.join(os.path.dirname(__file__), "..", "notes")
    os.makedirs(notes_dir, exist_ok=True)
    report_path = os.path.join(notes_dir, f"{date_str}.md")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"# 14:40 尾盘选股报告 {date_str}",
        "",
        f"> 生成时间：{now_str}  ",
        f"> 策略：涨幅3-5%、量比≥1、换手率5-10%、振幅≤8%、站上MA20、量能放大  ",
        "",
        "## TOP3 推荐",
        "",
        "| 排名 | 代码 | 名称 | 当前价 | 涨幅% | 振幅% | 概率分 | 命中因子 |",
        "| :--: | :--: | :--: | -----: | ----: | ----: | -----: | :------- |",
    ]

    if top_df.empty:
        lines.append("| - | - | 今日无满足条件的标的 | - | - | - | - | - |")
    else:
        top3 = top_df.head(3)
        for rank, (_, row) in enumerate(top3.iterrows(), start=1):
            code    = row.get("代码", "-")
            name    = row.get("名称", "-")
            price   = f"{row.get('最新价', 0):.2f}"
            pct     = f"{row.get('涨跌幅', 0):.2f}"
            amp     = f"{row.get('振幅', 0):.2f}"
            score   = f"{row.get('概率分', 0):.1f}"
            factors = row.get("命中因子", "-")
            lines.append(f"| {rank} | {code} | {name} | {price} | {pct} | {amp} | {score} | {factors} |")

    lines += [
        "",
        "## TOP10 完整列表",
        "",
        "| 排名 | 代码 | 名称 | 涨幅% | 量比 | 换手率% | 振幅% | 概率分 |",
        "| :--: | :--: | :--: | ----: | ---: | ------: | ----: | -----: |",
    ]

    if top_df.empty:
        lines.append("| - | - | 暂无数据 | - | - | - | - | - |")
    else:
        for rank, (_, row) in enumerate(top_df.iterrows(), start=1):
            code  = row.get("代码", "-")
            name  = row.get("名称", "-")
            pct   = f"{row.get('涨跌幅', 0):.2f}"
            vr    = f"{row.get('量比', 0):.2f}"
            turn  = f"{row.get('换手率', 0):.2f}"
            amp   = f"{row.get('振幅', 0):.2f}"
            score = f"{row.get('概率分', 0):.1f}"
            lines.append(f"| {rank} | {code} | {name} | {pct} | {vr} | {turn} | {amp} | {score} |")

    lines += [
        "",
        "---",
        "> **免责声明**：本报告仅供学习研究，不构成任何投资建议。股市有风险，投资需谨慎。",
    ]

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[reporter] 报告已保存：{report_path}")
    return report_path


def push_feishu(webhook_url: str, top_df: pd.DataFrame, date_str: str = None) -> bool:
    """
    推送选股结果到飞书群机器人。

    参数：
        webhook_url : 飞书 Webhook 地址
        top_df      : TOP3 DataFrame
        date_str    : 日期字符串

    返回：推送是否成功
    """
    if not webhook_url or webhook_url.strip() == "":
        print("[reporter] 未配置飞书 Webhook，跳过推送")
        return False

    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    top3 = top_df.head(3) if not top_df.empty else pd.DataFrame()

    lines = [f"📊 {date_str} 14:40 尾盘选股 TOP3\n"]
    if top3.empty:
        lines.append("今日无满足条件的标的")
    else:
        for rank, (_, row) in enumerate(top3.iterrows(), start=1):
            code  = row.get("代码", "-")
            name  = row.get("名称", "-")
            pct   = row.get("涨跌幅", 0)
            score = row.get("概率分", 0)
            hits  = row.get("命中因子", "-")
            lines.append(f"{rank}. {name}（{code}）涨幅{pct:.2f}% 概率分{score:.1f}\n   ▶ {hits}")

    text = "\n".join(lines)

    payload = {
        "msg_type": "text",
        "content": {"text": text},
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code == 200 and resp.json().get("code", -1) == 0:
            print("[reporter] 飞书推送成功")
            return True
        else:
            print(f"[reporter] 飞书推送失败：{resp.status_code} {resp.text}")
            return False
    except Exception as e:
        print(f"[reporter] 飞书推送异常：{e}")
        return False
