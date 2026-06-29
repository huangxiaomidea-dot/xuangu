"""
14:40 尾盘选股器 — Web 控制台后端
运行方式：cd tail-screener && python app.py
访问地址：http://localhost:5000
"""

import os
import sys
import re
import json
import queue
import threading
import subprocess
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

ROOT = os.path.dirname(os.path.abspath(__file__))
NOTES_DIR = os.path.join(ROOT, "notes")
SCRIPTS_DIR = os.path.join(ROOT, "scripts")

app = Flask(__name__, template_folder="templates")

# 全局运行状态
_run_state = {
    "running": False,
    "last_run": None,
    "last_status": "idle",  # idle | running | success | error
}

# 日志队列：每次启动重置，SSE 客户端从队列消费
_log_queue: queue.Queue = queue.Queue()
_log_history: list = []  # 保留本次完整日志供刷新后补全


# ── 工具函数 ────────────────────────────────────────────────

def _parse_report_md(md_path: str) -> dict:
    """解析 Markdown 报告，提取 TOP3 结构化数据"""
    try:
        text = Path(md_path).read_text(encoding="utf-8")
    except Exception:
        return {}

    date_str = Path(md_path).stem

    # 提取 TOP3 表格行
    top3 = []
    in_top3 = False
    for line in text.splitlines():
        if "## TOP3" in line:
            in_top3 = True
            continue
        if in_top3 and line.startswith("## "):
            break
        if in_top3 and line.startswith("|") and not line.startswith("| :") and not line.startswith("| 排"):
            cols = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cols) >= 7 and cols[0].isdigit():
                top3.append({
                    "rank":    int(cols[0]),
                    "code":    cols[1],
                    "name":    cols[2],
                    "price":   cols[3],
                    "pct":     cols[4],
                    "amp":     cols[5],
                    "score":   cols[6],
                    "factors": cols[7] if len(cols) > 7 else "",
                })

    # 提取 TOP10 表格行
    top10 = []
    in_top10 = False
    for line in text.splitlines():
        if "## TOP10" in line:
            in_top10 = True
            continue
        if in_top10 and line.startswith("## "):
            break
        if in_top10 and line.startswith("|") and not line.startswith("| :") and not line.startswith("| 排"):
            cols = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cols) >= 7 and cols[0].isdigit():
                top10.append({
                    "rank":     int(cols[0]),
                    "code":     cols[1],
                    "name":     cols[2],
                    "pct":      cols[3],
                    "vol_ratio": cols[4],
                    "turnover": cols[5],
                    "amp":      cols[6],
                    "score":    cols[7] if len(cols) > 7 else "",
                })

    return {"date": date_str, "top3": top3, "top10": top10, "raw": text}


def _list_reports() -> list:
    """返回所有历史报告的日期列表（倒序）"""
    os.makedirs(NOTES_DIR, exist_ok=True)
    files = sorted(Path(NOTES_DIR).glob("*.md"), reverse=True)
    return [f.stem for f in files]


def _run_screener():
    """在子线程中运行选股脚本，将输出逐行放入队列"""
    global _run_state, _log_history
    _run_state["running"] = True
    _run_state["last_status"] = "running"
    _run_state["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _log_history = []

    def emit(line: str):
        _log_queue.put(line)
        _log_history.append(line)

    emit(f"[web] 启动选股器 {_run_state['last_run']}")

    try:
        proc = subprocess.Popen(
            [sys.executable, os.path.join(SCRIPTS_DIR, "run_screen.py")],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=ROOT,
        )
        for line in proc.stdout:
            emit(line.rstrip())
        proc.wait()
        if proc.returncode == 0:
            _run_state["last_status"] = "success"
            emit("[web] ✅ 选股完成")
        else:
            _run_state["last_status"] = "error"
            emit(f"[web] ❌ 进程退出码 {proc.returncode}")
    except Exception as e:
        _run_state["last_status"] = "error"
        emit(f"[web] ❌ 异常：{e}")
    finally:
        _run_state["running"] = False
        # 发送结束信号
        _log_queue.put("__DONE__")


# ── 路由 ────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/run", methods=["POST"])
def api_run():
    """启动选股（同一时间只允许一个实例）"""
    if _run_state["running"]:
        return jsonify({"ok": False, "msg": "选股正在运行中，请稍候"})
    # 清空上次日志队列
    while not _log_queue.empty():
        try:
            _log_queue.get_nowait()
        except queue.Empty:
            break
    t = threading.Thread(target=_run_screener, daemon=True)
    t.start()
    return jsonify({"ok": True, "msg": "选股已启动"})


@app.route("/api/status")
def api_status():
    """返回当前运行状态"""
    return jsonify({
        "running":     _run_state["running"],
        "last_run":    _run_state["last_run"],
        "last_status": _run_state["last_status"],
        "reports":     _list_reports(),
    })


@app.route("/api/logs/stream")
def api_logs_stream():
    """SSE 实时日志流"""
    def generate():
        # 先把本次已有历史日志推送（页面刷新后补全）
        for line in list(_log_history):
            yield f"data: {json.dumps(line)}\n\n"
        # 然后实时消费队列
        while True:
            try:
                line = _log_queue.get(timeout=30)
                if line == "__DONE__":
                    yield f"data: {json.dumps('__DONE__')}\n\n"
                    break
                yield f"data: {json.dumps(line)}\n\n"
            except queue.Empty:
                # 心跳，保持连接
                yield ": heartbeat\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/report/latest")
def api_report_latest():
    """返回最新报告数据"""
    reports = _list_reports()
    if not reports:
        return jsonify({"ok": False, "msg": "暂无报告"})
    md_path = os.path.join(NOTES_DIR, f"{reports[0]}.md")
    return jsonify({"ok": True, "data": _parse_report_md(md_path)})


@app.route("/api/report/<date_str>")
def api_report(date_str):
    """返回指定日期报告数据"""
    # 简单防注入：只允许 YYYY-MM-DD 格式
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        return jsonify({"ok": False, "msg": "日期格式错误"}), 400
    md_path = os.path.join(NOTES_DIR, f"{date_str}.md")
    if not os.path.exists(md_path):
        return jsonify({"ok": False, "msg": "报告不存在"})
    return jsonify({"ok": True, "data": _parse_report_md(md_path)})


if __name__ == "__main__":
    print("=" * 50)
    print("  14:40 尾盘选股器 Web 控制台")
    print("  访问地址：http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
