"""
报告生成、飞书推送、Server酱微信推送模块
"""

import os
import requests
import pandas as pd
from datetime import datetime

from . import tracker


def generate_report(top_df: pd.DataFrame, date_str: str = None, newly_settled: list = None) -> str:
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    notes_dir = os.path.join(os.path.dirname(__file__), "..", "notes")
    os.makedirs(notes_dir, exist_ok=True)
    report_path = os.path.join(notes_dir, f"{date_str}.md")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"# 14:40 尾盘选股报告 {date_str}",
        "",
        f"> 生成时间：{now_str}  ",
        f"> 策略：涨幅2-7%、量比≥1.5、收盘强度≥70%、上影线≤2%、均线多头  ",
        "",
        "## 🔁 滚动复盘",
        "",
    ]

    top3_stats = tracker.cumulative_stats()
    top1_stats = tracker.cumulative_stats(rank_filter=1)
    lines.append("> 结算规则：次日 9:30-9:35 开盘窗口内涨幅摸到 +0.1% 即算成功，收益按窗口收盘价计算  ")
    lines.append("")
    if newly_settled:
        lines.append("**最新结算：**")
        lines.append("")
        lines.append("| 排名 | 代码 | 名称 | 选股价 | 结算价 | 收益 | 胜负 |")
        lines.append("| :--: | :--: | :--: | ----: | ----: | ----: | :--: |")
        for rec in sorted(newly_settled, key=lambda r: r.get("rank", 9)):
            mark = "✅胜" if rec["win"] else "❌负"
            tag = "首选" if rec.get("rank") == 1 else str(rec.get("rank", "-"))
            lines.append(
                f"| {tag} | {rec['code']} | {rec['name']} | {rec['pick_price']:.2f} | "
                f"{rec['settle_price']:.2f} | {rec['return_pct']:+.2f}% | {mark} |"
            )
        lines.append("")
    else:
        lines.append("暂无待结算记录。")
        lines.append("")

    if top3_stats["total"] > 0:
        lines.append(
            f"**TOP3累计成功率：{top3_stats['win_rate']}%**（{top3_stats['wins']}/{top3_stats['total']}）"
        )
    else:
        lines.append("TOP3累计成功率：暂无历史数据")

    if top1_stats["total"] > 0:
        lines.append(
            f"**首选累计成功率：{top1_stats['win_rate']}%**（{top1_stats['wins']}/{top1_stats['total']}）"
        )
    else:
        lines.append("首选累计成功率：暂无历史数据")

    lines += [
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


def push_serverchan(send_key: str, top_df: pd.DataFrame, date_str: str = None, newly_settled: list = None) -> bool:
    """Server酱微信推送（sct.ftqq.com）"""
    if not send_key or send_key.strip() == "":
        print("[reporter] 未配置 SERVERCHAN_KEY，跳过微信推送")
        return False

    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    top3 = top_df.head(3) if not top_df.empty else pd.DataFrame()

    title = f"📊 {date_str} 尾盘选股 TOP3 出炉"

    rows = ["### 🔁 滚动复盘（次日9:30-9:35摸到+0.1%算成功）", ""]
    top3_stats = tracker.cumulative_stats()
    top1_stats = tracker.cumulative_stats(rank_filter=1)
    if newly_settled:
        for rec in sorted(newly_settled, key=lambda r: r.get("rank", 9)):
            mark = "✅" if rec["win"] else "❌"
            tag = "【首选】" if rec.get("rank") == 1 else ""
            rows.append(f"{mark} {tag}{rec['name']}（{rec['code']}） {rec['return_pct']:+.2f}%  ")
    else:
        rows.append("暂无待结算记录  ")
    if top3_stats["total"] > 0:
        rows.append(f"**TOP3累计成功率：{top3_stats['win_rate']}%**（{top3_stats['wins']}/{top3_stats['total']}）  ")
    if top1_stats["total"] > 0:
        rows.append(f"**首选累计成功率：{top1_stats['win_rate']}%**（{top1_stats['wins']}/{top1_stats['total']}）  ")
    rows.append("")
    rows.append("### 🎯 今日推荐")
    rows.append("")

    if top3.empty:
        rows.append("今日无满足条件的标的")
    else:
        for rank, (_, row) in enumerate(top3.iterrows(), start=1):
            medal = ["🥇", "🥈", "🥉"][rank - 1]
            code  = row.get("代码", "-")
            name  = row.get("名称", "-")
            pct   = row.get("涨跌幅", 0)
            score = row.get("概率分", 0)
            hits  = row.get("命中因子", "-")
            rows.append(f"{medal} **{name}**（{code}）  ")
            rows.append(f"涨幅 **{pct:.2f}%** · 概率分 **{score:.1f}**  ")
            rows.append(f"命中因子：{hits}  ")
            rows.append("")

    rows.append("> 免责声明：仅供学习，不构成投资建议")
    desp = "\n".join(rows)

    url = f"https://sctapi.ftqq.com/{send_key.strip()}.send"
    try:
        resp = requests.post(url, data={"title": title, "desp": desp}, timeout=15)
        result = resp.json()
        if result.get("code") == 0:
            print("[reporter] Server酱微信推送成功")
            return True
        else:
            print(f"[reporter] Server酱推送失败：{result}")
            return False
    except Exception as e:
        print(f"[reporter] Server酱推送异常：{e}")
        return False


def push_feishu(webhook_url: str, top_df: pd.DataFrame, date_str: str = None) -> bool:
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

    payload = {"msg_type": "text", "content": {"text": "\n".join(lines)}}
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
