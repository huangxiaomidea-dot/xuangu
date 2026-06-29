#!/usr/bin/env python3
"""
A股每日选股工具
每天下午2:45运行，推荐次日开盘上涨概率最高的一支股票
数据源：BaoStock（免费、稳定的A股历史行情接口）
"""

import json
import logging
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

# ─── 选股过滤条件 ───────────────────────────────────────────────
MIN_PRICE = 3.0        # 最低股价（元）
MAX_PRICE = 200.0      # 最高股价（元）
HISTORY_DAYS = 80      # 获取历史数据天数
TOP_N_CANDIDATES = 300 # 从流动性最好的前N支股票中选

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
    return k, d, 3*k - 2*d

def boll(close, n=20):
    m = sma(close, n)
    s = close.rolling(n).std()
    return m + 2*s, m, m - 2*s

# ─── 评分函数（满分100） ────────────────────────────────────────

def score_stock(df: pd.DataFrame) -> dict | None:
    """
    评分维度：
      均线多头排列      20分
      量能放大          15分
      MACD改善          20分
      RSI健康区间       10分
      KDJ J值上行       10分
      尾盘强势          15分
      布林带位置        10分
    """
    if len(df) < 30:
        return None

    c = df["close"]
    h = df["high"]
    l = df["low"]
    v = df["volume"]

    ma5  = sma(c, 5)
    ma10 = sma(c, 10)
    ma20 = sma(c, 20)
    dif, dea, hist = macd(c)
    r = rsi(c)
    _, _, j = kdj(h, l, c)
    bu, bm, bl = boll(c)

    i = -1
    score = 0
    details: dict = {}

    # 均线多头
    bull = (c.iloc[i] > ma5.iloc[i] > ma10.iloc[i] > ma20.iloc[i])
    if bull: score += 20
    details["均线多头排列"] = bull

    # 量能放大（今日量 > 5日均量 1.5x）
    vol_avg5 = v.iloc[-6:-1].mean()
    surge = bool(v.iloc[i] > vol_avg5 * 1.5) if vol_avg5 > 0 else False
    if surge: score += 15
    details["量能放大"] = surge

    # MACD
    cross = bool(dif.iloc[i] > dea.iloc[i])
    improve = bool(hist.iloc[i] > hist.iloc[-2])
    if cross and improve: score += 20
    elif cross or improve: score += 10
    details["MACD金叉"] = cross
    details["MACD柱改善"] = improve

    # RSI
    rv = float(r.iloc[i])
    rsi_ok = 40 <= rv <= 70 if not np.isnan(rv) else False
    if rsi_ok: score += 10
    details["RSI"] = round(rv, 1) if not np.isnan(rv) else None

    # KDJ J
    jv = float(j.iloc[i])
    j_ok = (20 <= jv <= 85) and (j.iloc[i] > j.iloc[-2]) if not np.isnan(jv) else False
    if j_ok: score += 10
    details["KDJ_J"] = round(jv, 1) if not np.isnan(jv) else None

    # 尾盘强势（收盘/最高）
    strength = float(c.iloc[i] / h.iloc[i]) if h.iloc[i] > 0 else 0
    if strength >= 0.95: score += 15
    elif strength >= 0.90: score += 7
    details["尾盘强度"] = round(strength, 3)

    # 布林带位置
    bv_u, bv_m, bv_l = bu.iloc[i], bm.iloc[i], bl.iloc[i]
    if not any(np.isnan([bv_u, bv_m, bv_l])) and bv_u > bv_l:
        pos = (c.iloc[i] - bv_l) / (bv_u - bv_l)
        if 0.4 <= pos <= 0.85: score += 10
        elif 0.2 <= pos < 0.4: score += 5
        details["布林位置"] = round(float(pos), 2)

    return {"score": score, "details": details}

# ─── BaoStock 数据获取 ─────────────────────────────────────────

def bs_login():
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"BaoStock登录失败: {lg.error_msg}")

def get_stock_list() -> pd.DataFrame:
    """获取A股全部股票列表"""
    log.info("获取A股股票列表...")
    rs = bs.query_stock_basic(type_="1")    # type_=1 股票
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    df = pd.DataFrame(rows, columns=rs.fields)
    # 过滤：上市状态=1（正常），剔除ST/北交所/科创板
    df = df[df["status"] == "1"]
    df = df[~df["code_name"].str.contains(r"ST|\*ST", na=False)]
    # 只保留沪深主板 + 创业板
    df = df[df["code"].str.match(r"^(sh\.6[0-5]|sz\.0|sz\.3)")]
    return df.reset_index(drop=True)

def get_history(code: str) -> pd.DataFrame | None:
    end = datetime.today().strftime("%Y-%m-%d")
    start = (datetime.today() - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d")
    fields = "date,open,high,low,close,volume,amount,turn,pctChg"
    rs = bs.query_history_k_data_plus(
        code, fields, start_date=start, end_date=end,
        frequency="d", adjustflag="2"   # 前复权
    )
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if len(rows) < 20:
        return None
    df = pd.DataFrame(rows, columns=rs.fields)
    for col in ["open","high","low","close","volume","amount","turn","pctChg"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close","volume"])
    return df if len(df) >= 20 else None

# ─── 主流程 ────────────────────────────────────────────────────

def pick_stock() -> tuple[dict, list[dict]]:
    bs_login()
    try:
        stock_list = get_stock_list()
        log.info(f"A股股票总数：{len(stock_list)}")

        # 先获取全量最新日行情来排序流动性
        # BaoStock没有实时行情接口，用前一交易日收盘数据排序
        # 取成交额最大的 TOP_N_CANDIDATES 只股票
        today = datetime.today().strftime("%Y-%m-%d")
        yesterday = (datetime.today() - timedelta(days=5)).strftime("%Y-%m-%d")

        log.info("获取近期成交额以筛选流动性较好的候选股...")
        amount_map: dict[str, float] = {}
        price_map:  dict[str, float] = {}
        chg_map:    dict[str, float] = {}
        name_map:   dict[str, str]   = {}

        for _, row in stock_list.iterrows():
            code = row["code"]
            name = row["code_name"]
            rs = bs.query_history_k_data_plus(
                code, "date,close,amount,pctChg",
                start_date=yesterday, end_date=today,
                frequency="d", adjustflag="2"
            )
            last_row = None
            while rs.error_code == "0" and rs.next():
                last_row = rs.get_row_data()
            if last_row:
                try:
                    amt = float(last_row[2]) if last_row[2] else 0
                    price = float(last_row[1]) if last_row[1] else 0
                    chg = float(last_row[3]) if last_row[3] else 0
                    if MIN_PRICE <= price <= MAX_PRICE and abs(chg) < 9.5:
                        amount_map[code] = amt
                        price_map[code]  = price
                        chg_map[code]    = chg
                        name_map[code]   = name
                except ValueError:
                    pass

        if not amount_map:
            raise RuntimeError("无法获取行情数据，请检查网络")

        # 按成交额排序取 TOP_N
        sorted_codes = sorted(amount_map, key=lambda x: amount_map[x], reverse=True)
        candidates = sorted_codes[:TOP_N_CANDIDATES]
        log.info(f"流动性过滤后候选：{len(candidates)} 支，开始评分...")

        results = []
        for idx, code in enumerate(candidates, 1):
            hist = get_history(code)
            if hist is None:
                continue
            res = score_stock(hist)
            if res is None:
                continue
            results.append({
                "code": code,
                "name": name_map[code],
                "price": price_map[code],
                "change_pct": chg_map[code],
                "amount": amount_map[code],
                **res,
            })
            if idx % 50 == 0:
                log.info(f"  已处理 {idx}/{len(candidates)}，有效 {len(results)} 支")

        if not results:
            raise RuntimeError("没有符合条件的股票")

        df_r = pd.DataFrame(results).sort_values("score", ascending=False)
        best = df_r.iloc[0].to_dict()
        top10 = df_r.head(10).to_dict("records")
        log.info(f"推荐：{best['name']}（{best['code']}）评分 {best['score']}/100")
        return best, top10
    finally:
        bs.logout()

# ─── HTML 报告 ─────────────────────────────────────────────────

def generate_report(best: dict, top10: list[dict]) -> str:
    date_str = datetime.now().strftime("%Y年%m月%d日")
    time_str = datetime.now().strftime("%H:%M")

    def fmt(v):
        if isinstance(v, bool): return "✅" if v else "❌"
        if isinstance(v, (int, float)) and not isinstance(v, bool): return str(v)
        return str(v) if v is not None else "—"

    details_rows = "".join(
        f"<tr><td>{k}</td><td>{fmt(v)}</td></tr>"
        for k, v in best.get("details", {}).items()
    )

    top10_rows = ""
    for i, s in enumerate(top10, 1):
        badge = "🏆" if i == 1 else f"#{i}"
        chg = s.get("change_pct", 0) or 0
        cls = "up" if chg >= 0 else "dn"
        top10_rows += (
            f'<tr class="{"highlight" if i==1 else ""}">'
            f"<td>{badge}</td>"
            f"<td><b>{s['name']}</b><br><small>{s['code']}</small></td>"
            f"<td>¥{s['price']:.2f}</td>"
            f'<td class="{cls}">{chg:+.2f}%</td>'
            f"<td>{s['score']}分</td>"
            f"</tr>"
        )

    score = best["score"]
    chg = best.get("change_pct", 0) or 0

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
.hero-code{{font-size:.95rem;color:#888;margin-top:4px}}
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
    <p>{date_str} · {time_str} 生成 · 预测次日开盘上涨概率</p>
  </div>

  <div class="card">
    <h2>今日推荐</h2>
    <div class="hero">
      <div>
        <div class="hero-name">{best['name']}</div>
        <div class="hero-code">{best['code']}</div>
      </div>
      <div>
        <div class="hero-price">¥{best['price']:.2f}</div>
        <div class="{'up' if chg>=0 else 'dn'}">{chg:+.2f}%</div>
      </div>
    </div>
    <div class="bar-wrap">
      <div class="bar-label">综合评分：<b>{score}</b> / 100</div>
      <div class="bar"><div class="bar-fill" style="width:{score}%"></div></div>
    </div>
  </div>

  <div class="card">
    <h2>评分明细</h2>
    <table>
      <tr><th>指标</th><th>状态</th></tr>
      {details_rows}
    </table>
  </div>

  <div class="card">
    <h2>今日 Top 10</h2>
    <table>
      <tr><th>排名</th><th>股票</th><th>现价</th><th>涨跌幅</th><th>评分</th></tr>
      {top10_rows}
    </table>
  </div>

  <div class="note">⚠️ 本工具仅供学习与参考，不构成投资建议。股市有风险，投资需谨慎。</div>
</div>
</body>
</html>"""

    today = datetime.now().strftime("%Y%m%d")
    (OUTPUT_DIR / f"report_{today}.html").write_text(html, encoding="utf-8")
    (OUTPUT_DIR / "latest.html").write_text(html, encoding="utf-8")
    (OUTPUT_DIR / f"result_{today}.json").write_text(
        json.dumps({"best": best, "top10": top10, "generated_at": datetime.now().isoformat()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    path = str(OUTPUT_DIR / f"report_{today}.html")
    log.info(f"报告已生成：{path}")
    return path

# ─── 入口 ──────────────────────────────────────────────────────

def run():
    log.info("=== A股选股工具启动 ===")
    best, top10 = pick_stock()
    path = generate_report(best, top10)
    chg = best.get("change_pct", 0) or 0
    print(f"\n✅ 推荐完成！")
    print(f"   今日推荐：{best['name']}（{best['code']}）")
    print(f"   现价：¥{best['price']:.2f}  涨跌：{chg:+.2f}%")
    print(f"   综合评分：{best['score']}/100")
    print(f"   报告路径：{path}\n")

if __name__ == "__main__":
    run()
