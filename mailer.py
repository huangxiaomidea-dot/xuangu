#!/usr/bin/env python3
"""
邮件发送模块
配置方式：设置环境变量或在 .env 文件中填写
  SMTP_HOST   - SMTP服务器，如 smtp.qq.com / smtp.163.com / smtp.gmail.com
  SMTP_PORT   - 端口，默认 465（SSL）
  SMTP_USER   - 发件邮箱
  SMTP_PASS   - 邮箱授权码（非登录密码）
  MAIL_TO     - 收件人，默认 huangxiao4@midea.com
"""
import json
import logging
import os
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

log = logging.getLogger(__name__)

MAIL_TO = os.getenv("MAIL_TO", "huangxiao4@midea.com")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")


def _load_env():
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    global MAIL_TO, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
    MAIL_TO   = os.getenv("MAIL_TO", "huangxiao4@midea.com")
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASS = os.getenv("SMTP_PASS", "")


def _build_html(best: dict, top10: list, generated_at: str) -> str:
    chg = best.get("change_pct") or best.get("chg") or 0
    chg_color = "#e74c3c" if chg >= 0 else "#27ae60"
    chg_str = f"+{chg:.2f}%" if chg >= 0 else f"{chg:.2f}%"
    code_clean = best.get("code", "").replace("sh.", "").replace("sz.", "")
    mkt = "SH" if best.get("code", "").startswith("sh") else "SZ"

    details = best.get("details", {})
    det_rows = ""
    for k, v in details.items():
        if isinstance(v, bool):
            val = "✅" if v else "❌"
            color = "#27ae60" if v else "#aaa"
        elif isinstance(v, float):
            val = f"{v:.2f}"
            color = "#2980b9"
        else:
            val = str(v)
            color = "#555"
        det_rows += f'<tr><td style="padding:6px 10px;color:#666">{k}</td><td style="padding:6px 10px;font-weight:600;color:{color}">{val}</td></tr>'

    top10_rows = ""
    medals = ["🥇", "🥈", "🥉"]
    for i, s in enumerate(top10[:10]):
        c = s.get("change_pct") or s.get("chg") or 0
        c_color = "#e74c3c" if c >= 0 else "#27ae60"
        c_str = f"+{c:.2f}%" if c >= 0 else f"{c:.2f}%"
        code = s.get("code", "").replace("sh.", "").replace("sz.", "")
        medal = medals[i] if i < 3 else f"{i+1}"
        bg = "#fff8f8" if i == 0 else "#fff"
        top10_rows += f'<tr style="background:{bg}"><td style="padding:8px 10px">{medal}</td><td style="padding:8px 10px"><b>{s["name"]}</b><br><small style="color:#aaa">{code}</small></td><td style="padding:8px 10px">¥{float(s["price"]):.2f}</td><td style="padding:8px 10px;color:{c_color}">{c_str}</td><td style="padding:8px 10px;font-weight:700">{s["score"]}分</td></tr>'

    date_str = datetime.now().strftime("%Y年%m月%d日")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif">
<div style="max-width:640px;margin:20px auto;background:#fff;border-radius:14px;box-shadow:0 2px 16px rgba(0,0,0,.08);overflow:hidden">
  <div style="background:linear-gradient(135deg,#e74c3c,#c0392b);padding:28px 24px;text-align:center">
    <h1 style="margin:0;color:#fff;font-size:1.5rem;letter-spacing:1px">📈 A股每日选股推荐</h1>
    <p style="margin:6px 0 0;color:rgba(255,255,255,.8);font-size:.88rem">{date_str} · 基于7项技术指标评分</p>
  </div>
  <div style="padding:24px">
    <h2 style="margin:0 0 16px;font-size:.95rem;color:#333;border-left:4px solid #c0392b;padding-left:10px">🏆 今日推荐</h2>
    <div style="background:#fff8f8;border:2px solid #e74c3c;border-radius:12px;padding:20px;margin-bottom:20px">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px">
        <div>
          <div style="font-size:1.8rem;font-weight:800;color:#c0392b">{best["name"]}</div>
          <div style="color:#aaa;font-size:.85rem;margin-top:2px">{mkt} · {code_clean}</div>
        </div>
        <div style="text-align:right">
          <div style="font-size:1.5rem;font-weight:700">¥{float(best["price"]):.2f}</div>
          <div style="color:{chg_color};font-size:1rem;margin-top:2px">{chg_str}</div>
        </div>
      </div>
      <div style="margin-top:16px">
        <div style="font-size:.82rem;color:#666;margin-bottom:6px">综合评分 <b style="color:#c0392b;font-size:1.1rem">{best["score"]}</b> / 100</div>
        <div style="height:12px;background:#eee;border-radius:6px;overflow:hidden">
          <div style="height:100%;width:{best["score"]}%;background:linear-gradient(90deg,#f39c12,#e74c3c);border-radius:6px"></div>
        </div>
      </div>
    </div>
    <h2 style="margin:0 0 12px;font-size:.95rem;color:#333;border-left:4px solid #c0392b;padding-left:10px">📊 评分明细</h2>
    <table style="width:100%;border-collapse:collapse;font-size:.85rem;margin-bottom:20px">
      <thead><tr style="background:#f8f8f8"><th style="padding:8px 10px;text-align:left;color:#666">指标</th><th style="padding:8px 10px;text-align:left;color:#666">状态</th></tr></thead>
      <tbody>{det_rows}</tbody>
    </table>
    <h2 style="margin:0 0 12px;font-size:.95rem;color:#333;border-left:4px solid #c0392b;padding-left:10px">📋 今日 Top 10</h2>
    <table style="width:100%;border-collapse:collapse;font-size:.85rem">
      <thead><tr style="background:#f8f8f8">
        <th style="padding:8px 10px;text-align:left;color:#666">排名</th>
        <th style="padding:8px 10px;text-align:left;color:#666">股票</th>
        <th style="padding:8px 10px;text-align:left;color:#666">现价</th>
        <th style="padding:8px 10px;text-align:left;color:#666">涨跌幅</th>
        <th style="padding:8px 10px;text-align:left;color:#666">评分</th>
      </tr></thead>
      <tbody>{top10_rows}</tbody>
    </table>
  </div>
  <div style="padding:16px 24px;background:#fffbe6;font-size:.75rem;color:#888;text-align:center">
    ⚠️ 本邮件仅供学习参考，不构成投资建议。股市有风险，投资需谨慎。<br>
    生成时间：{generated_at}
  </div>
</div>
</body></html>"""


def send_report(best: dict, top10: list, generated_at: str = "") -> bool:
    _load_env()
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASS:
        log.warning("未配置 SMTP，跳过邮件发送。请在 .env 文件中配置 SMTP_HOST/SMTP_USER/SMTP_PASS")
        return False

    date_str = datetime.now().strftime("%Y年%m月%d日")
    subject = f"📈 A股每日选股推荐 {date_str} · 今日推荐：{best['name']}（评分{best['score']}分）"
    html_body = _build_html(best, top10, generated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = MAIL_TO
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, MAIL_TO, msg.as_string())
        log.info(f"邮件已发送至 {MAIL_TO}")
        return True
    except Exception as e:
        log.error(f"邮件发送失败：{e}")
        return False


def send_from_latest_result():
    """从最新结果文件发送邮件（供独立调用）"""
    output_dir = Path(__file__).parent / "output"
    files = sorted(output_dir.glob("result_*.json"), reverse=True)
    if not files:
        log.error("无结果文件，请先运行 picker.py")
        return False
    data = json.loads(files[0].read_text(encoding="utf-8"))
    return send_report(data["best"], data.get("top10", []), data.get("generated_at", ""))


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    success = send_from_latest_result()
    sys.exit(0 if success else 1)
