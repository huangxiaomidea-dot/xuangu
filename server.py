#!/usr/bin/env python3
"""
Flask 后端服务：提供选股 API + 静态文件托管
"""
import json
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")
CORS(app)

_cache = {}
_lock = threading.Lock()


@app.route("/")
def index():
    return send_from_directory(str(BASE_DIR), "index.html")


@app.route("/api/pick")
def api_pick():
    today = datetime.now().strftime("%Y%m%d")
    result_file = OUTPUT_DIR / f"result_{today}.json"

    # 有当天缓存直接返回
    if result_file.exists():
        data = json.loads(result_file.read_text(encoding="utf-8"))
        data["cached"] = True
        return jsonify(data)

    # 实时运行选股
    try:
        from picker import pick_stock, generate_report
        best, top10 = pick_stock()
        generate_report(best, top10)
        data = json.loads(result_file.read_text(encoding="utf-8"))
        data["cached"] = False
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/latest")
def api_latest():
    """返回最新一次的结果（不重新运行）"""
    files = sorted(OUTPUT_DIR.glob("result_*.json"), reverse=True)
    if not files:
        return jsonify({"error": "暂无数据，请先点击运行选股"}), 404
    data = json.loads(files[0].read_text(encoding="utf-8"))
    data["cached"] = True
    return jsonify(data)


if __name__ == "__main__":
    print("启动 A股选股服务：http://localhost:8080")
    app.run(host="0.0.0.0", port=8080, debug=False)
