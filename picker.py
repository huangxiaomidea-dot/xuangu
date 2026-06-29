#!/usr/bin/env python3
"""
A股每日选股工具
候选池：沪深300 + 中证500 + 上证50 成分股（约800支，流动性好）
评分维度：均线/量能/MACD/RSI/KDJ/尾盘/布林带（满分100）
数据源：BaoStock（A股免费历史行情接口）
"""

import json
import logging
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import baostock as bs
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

MIN_PRICE    = 3.0    # 最低股价（元）
MAX_PRICE    = 300.0  # 最高股价（元）
HISTORY_DAYS = 90     # 拉取历史天数（日历天，实际交易日约60个）

# ─── 技术指标 ──────────────────────────────────────────────────

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()

def macd(close: pd.Series):
    dif = ema(close, 12) - ema(close, 26)
    dea = ema(dif, 9)
    return dif, dea, (dif - dea) * 2

def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    gain = d.clip(lower=0).rolling(n).mean()
    loss = (-d.clip(upper=0)).rolling(n).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))

def kdj(high, low, close, n=9):
    lo = low.rolling(n).min()
    hi = high.rolling(n).max()
    rsv = (close - lo) / (hi - lo).replace(0, np.nan) * 100
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    return k, d, 3 * k - 2 * d

def boll(close, n=20):
    m = sma(close, n)
    s = close.rolling(n).std()
    return m + 2 * s, m, m - 2 * s

# ─── 评分（满分100） ────────────────────────────────────────────

def score_stock(df: pd.DataFrame) -> dict | None:
    """
    技术指标评分，输入前复权数据（adjustflag=2），确保相对关系正确。
    返回 {"score": int, "details": dict}
    """
    if len(df) < 30:
        return None

    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    ma5  = sma(c, 5)
    ma10 = sma(c, 10)
    ma20 = sma(c, 20)
    dif, dea, hist = macd(c)
    r    = rsi(c)
    _, _, j = kdj(h, l, c)
    bu, bm, bl = boll(c)

    i     = -1
    score = 0
    details: dict = {}

    # 均线多头排列 20分
    bull = bool(c.iloc[i] > ma5.iloc[i] > ma10.iloc[i] > ma20.iloc[i])
    if bull:
        score += 20
    details["均线多头排列"] = bull

    # 量能放大 15分（今日量 > 5日均量 1.5倍）
    vol_avg5 = v.iloc[-6:-1].mean()
    surge = bool(v.iloc[i] > vol_avg5 * 1.5) if vol_avg5 > 0 else False
    if surge:
        score += 15
    details["量能放大"] = surge

    # MACD 20分
    cross   = bool(dif.iloc[i] > dea.iloc[i])
    improve = bool(hist.iloc[i] > hist.iloc[-2])
    if cross and improve:
        score += 20
    elif cross or improve:
        score += 10
    details["MACD金叉"]   = cross
    details["MACD柱改善"] = improve

    # RSI 10分
    rv = float(r.iloc[i]) if not np.isnan(r.iloc[i]) else None
    rsi_ok = (40 <= rv <= 70) if rv is not None else False
    if rsi_ok:
        score += 10
    details["RSI"] = round(rv, 1) if rv is not None else None

    # KDJ J值 10分
    jv = float(j.iloc[i]) if not np.isnan(j.iloc[i]) else None
    j_ok = (20 <= jv <= 85 and j.iloc[i] > j.iloc[-2]) if jv is not None else False
    if j_ok:
        score += 10
    details["KDJ_J"] = round(jv, 1) if jv is not None else None

    # 尾盘强势 15分（收盘 / 最高价）
    strength = float(c.iloc[i] / h.iloc[i]) if h.iloc[i] > 0 else 0
    if strength >= 0.95:
        score += 15
    elif strength >= 0.90:
        score += 7
    details["尾盘强度"] = round(strength, 3)

    # 布林带位置 10分
    bv_u = float(bu.iloc[i])
    bv_l = float(bl.iloc[i])
    if not any(np.isnan([bv_u, bv_l])) and bv_u > bv_l:
        pos = (c.iloc[i] - bv_l) / (bv_u - bv_l)
        if 0.4 <= pos <= 0.85:
            score += 10
        elif 0.2 <= pos < 0.4:
            score += 5
        details["布林位置"] = round(float(pos), 2)

    return {"score": int(score), "details": details}

# ─── BaoStock 数据层 ───────────────────────────────────────────

def bs_login():
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"BaoStock登录失败: {lg.error_msg}")


def _drain(rs) -> list:
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    return rows


def get_latest_trading_day() -> str | None:
    """返回最近已收盘的交易日（yyyy-mm-dd）"""
    today = datetime.today()
    start = (today - timedelta(days=10)).strftime("%Y-%m-%d")
    end   = today.strftime("%Y-%m-%d")
    rs    = bs.query_trade_dates(start_date=start, end_date=end)
    trade_days = [r[0] for r in _drain(rs) if r[1] == "1"]
    return trade_days[-1] if trade_days else None


def get_index_pool() -> dict[str, str]:
    """
    返回 {code: name}
    来源：沪深300 + 中证500 + 上证50，约 800 支高流动性股票
    """
    pool: dict[str, str] = {}
    for fetcher in (bs.query_hs300_stocks, bs.query_zz500_stocks, bs.query_sz50_stocks):
        rs = fetcher()
        for row in _drain(rs):
            if len(row) >= 3:
                pool[row[1]] = row[2]   # code -> code_name
    log.info(f"候选池（指数成分股）：{len(pool)} 支")
    return pool


def _fetch_kdata(code: str, start: str, end: str, adjustflag: str) -> pd.DataFrame | None:
    fields = "date,open,high,low,close,volume,amount,pctChg"
    rs = bs.query_history_k_data_plus(
        code, fields,
        start_date=start, end_date=end,
        frequency="d", adjustflag=adjustflag,
    )
    rows = _drain(rs)
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=rs.fields)
    for col in ["open", "high", "low", "close", "volume", "amount", "pctChg"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close", "volume"])
    return df if not df.empty else None


# ─── 主流程 ────────────────────────────────────────────────────

def pick_stock() -> tuple[dict, list[dict]]:
    bs_login()
    try:
        latest_day = get_latest_trading_day()
        if not latest_day:
            raise RuntimeError("无法获取交易日历，可能是非交易时段")
        log.info(f"最近交易日：{latest_day}")

        start = (
            datetime.strptime(latest_day, "%Y-%m-%d") - timedelta(days=HISTORY_DAYS)
        ).strftime("%Y-%m-%d")

        pool = get_index_pool()
        if not pool:
            raise RuntimeError("候选池为空")

        log.info(f"开始对 {len(pool)} 支股票取数评分...")
        results = []
        skipped = 0

        for idx, (code, name) in enumerate(pool.items(), 1):
            # ① 不复权数据 → 用于展示真实价格和涨跌幅
            df_raw = _fetch_kdata(code, start, latest_day, adjustflag="3")
            # ② 前复权数据 → 用于技术指标计算（相对关系更准确）
            df_adj = _fetch_kdata(code, start, latest_day, adjustflag="2")

            if df_raw is None or df_adj is None or len(df_adj) < 20:
                skipped += 1
                continue

            last = df_raw.iloc[-1]
            price = float(last["close"])
            chg   = float(last["pctChg"]) if not pd.isna(last["pctChg"]) else 0.0
            amt   = float(last["amount"]) if not pd.isna(last["amount"]) else 0.0
            date  = str(last["date"])

            # 价格过滤
            if not (MIN_PRICE <= price <= MAX_PRICE):
                skipped += 1
                continue
            # 跌停/涨停过滤（不选当日已涨跌停股票）
            if abs(chg) >= 9.5:
                skipped += 1
                continue

            res = score_stock(df_adj)
            if res is None:
                skipped += 1
                continue

            results.append({
                "code":       code,
                "name":       name,
                "price":      round(price, 2),
                "change_pct": round(chg, 2),
                "amount":     amt,
                "date":       date,
                **res,
            })

            if idx % 100 == 0:
                log.info(f"  进度 {idx}/{len(pool)}，有效 {len(results)} 支，跳过 {skipped} 支")

        log.info(f"评分完成：{len(results)} 支有效，{skipped} 支跳过")

        if not results:
            raise RuntimeError("没有符合条件的股票，可能是非交易日或数据暂时不可用")

        df_r  = pd.DataFrame(results).sort_values("score", ascending=False)
        best  = df_r.iloc[0].to_dict()
        top10 = df_r.head(10).to_dict("records")
        log.info(f"推荐：{best['name']}（{best['code']}）评分 {best['score']}/100")
        return best, top10

    finally:
        bs.logout()


# ─── 生成报告 ──────────────────────────────────────────────────

def generate_report(best: dict, top10: list[dict]) -> str:
    now      = datetime.now()
    date_str = now.strftime("%Y年%m月%d日")
    time_str = now.strftime("%H:%M")
    today    = now.strftime("%Y%m%d")

    def fmt(v):
        if isinstance(v, bool):
            return "✅" if v else "❌"
        if isinstance(v, float):
            return f"{v:.2f}"
        return str(v) if v is not None else "—"

    det_rows = "".join(
        f"<tr><td>{k}</td><td>{fmt(v)}</td></tr>"
        for k, v in best.get("details", {}).items()
    )

    medals = ["🥇", "🥈", "🥉"]
    top10_rows = ""
    for i, s in enumerate(top10, 1):
        chg     = s.get("change_pct", 0) or 0
        cls     = "up" if chg >= 0 else "dn"
        badge   = medals[i - 1] if i <= 3 else f"#{i}"
        hi      = ' class="highlight"' if i == 1 else ""
        code_c  = s["code"].replace("sh.", "").replace("sz.", "")
        top10_rows += (
            f"<tr{hi}><td>{badge}</td>"
            f"<td><b>{s['name']}</b><br><small>{code_c}</small></td>"
            f"<td>¥{float(s['price']):.2f}</td>"
            f'<td class="{cls}">{chg:+.2f}%</td>'
            f"<td><b>{s['score']}</b>分</td></tr>"
        )

    score    = best["score"]
    chg      = best.get("change_pct", 0) or 0
    chg_cls  = "up" if chg >= 0 else "dn"
    code_c   = best["code"].replace("sh.", "").replace("sz.", "")
    data_date = best.get("date", "")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>A股每日推荐 · {date_str}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#f0f2f5;color:#222}}
.wrap{{max-width:820px;margin:0 auto;padding:24px 16px}}
.hd{{text-align:center;margin-bottom:28px}}
.hd h1{{font-size:1.6rem;color:#c0392b;margin-bottom:6px}}
.hd p{{color:#666;font-size:.9rem}}
.card{{background:#fff;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.08);padding:24px;margin-bottom:20px}}
.card h2{{font-size:1.05rem;color:#333;margin-bottom:16px;border-left:4px solid #c0392b;padding-left:10px}}
.hero{{display:flex;align-items:center;gap:20px;flex-wrap:wrap}}
.hero-name{{font-size:2rem;font-weight:700;color:#c0392b}}
.hero-code{{font-size:.9rem;color:#888;margin-top:4px}}
.hero-price{{font-size:1.5rem;font-weight:600}}
.up{{color:#e74c3c}}.dn{{color:#27ae60}}
.bar-wrap{{margin-top:16px}}
.bar-label{{font-size:.85rem;color:#666;margin-bottom:6px}}
.bar{{height:14px;background:#eee;border-radius:7px;overflow:hidden}}
.bar-fill{{height:100%;border-radius:7px;background:linear-gradient(90deg,#f39c12,#e74c3c)}}
table{{width:100%;border-collapse:collapse;font-size:.9rem}}
th{{background:#f7f7f7;padding:10px 8px;text-align:left;color:#555;font-weight:600;border-bottom:2px solid #eee}}
td{{padding:9px 8px;border-bottom:1px solid #f0f0f0}}
tr.highlight td{{background:#fff8f8}}
.note{{font-size:.78rem;color:#999;text-align:center;margin-top:24px;padding:12px;background:#fffbe6;border-radius:8px}}
@media(max-width:480px){{.hero{{flex-direction:column;gap:8px}}}}
</style>
</head>
<body>
<div class="wrap">
  <div class="hd">
    <h1>📈 A股每日选股推荐</h1>
    <p>数据日期：{data_date} · {time_str} 生成</p>
  </div>
  <div class="card">
    <h2>今日推荐</h2>
    <div class="hero">
      <div>
        <div class="hero-name">{best["name"]}</div>
        <div class="hero-code">{code_c}</div>
      </div>
      <div>
        <div class="hero-price">¥{float(best["price"]):.2f}</div>
        <div class="{chg_cls}">{chg:+.2f}%</div>
      </div>
    </div>
    <div class="bar-wrap">
      <div class="bar-label">综合评分：<b>{score}</b> / 100</div>
      <div class="bar"><div class="bar-fill" style="width:{score}%"></div></div>
    </div>
  </div>
  <div class="card">
    <h2>评分明细</h2>
    <table><tr><th>指标</th><th>状态</th></tr>{det_rows}</table>
  </div>
  <div class="card">
    <h2>今日 Top 10</h2>
    <table>
      <tr><th>排名</th><th>股票</th><th>收盘价</th><th>涨跌幅</th><th>评分</th></tr>
      {top10_rows}
    </table>
  </div>
  <div class="note">⚠️ 本工具仅供学习与参考，不构成投资建议。股市有风险，投资需谨慎。</div>
</div>
</body>
</html>"""

    generated_at = now.isoformat()
    result = {"best": best, "top10": top10, "generated_at": generated_at}

    (OUTPUT_DIR / f"report_{today}.html").write_text(html, encoding="utf-8")
    (OUTPUT_DIR / "latest.html").write_text(html, encoding="utf-8")
    (OUTPUT_DIR / f"result_{today}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / "latest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    path = str(OUTPUT_DIR / f"report_{today}.html")
    log.info(f"报告已生成：{path}")
    return path


# ─── 入口 ──────────────────────────────────────────────────────

def run():
    log.info("=== A股选股工具启动 ===")
    try:
        best, top10 = pick_stock()
    except RuntimeError as e:
        msg = str(e)
        if any(k in msg for k in ["没有符合条件", "非交易", "数据暂时不可用", "交易日历"]):
            log.warning(f"跳过本次运行：{msg}")
            sys.exit(0)
        raise
    path = generate_report(best, top10)
    chg  = best.get("change_pct", 0) or 0
    print(f"\n✅ 推荐完成！")
    print(f"   今日推荐：{best['name']}（{best['code']}）")
    print(f"   收盘价：¥{float(best['price']):.2f}  涨跌：{chg:+.2f}%")
    print(f"   综合评分：{best['score']}/100")
    print(f"   报告路径：{path}\n")


if __name__ == "__main__":
    run()
