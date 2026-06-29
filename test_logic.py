#!/usr/bin/env python3
"""
离线单元测试：验证评分算法逻辑正确性（不需要网络）
"""
import numpy as np
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from picker import score_stock, ema, sma, macd, rsi, kdj, boll

def make_df(n=60, trend="up"):
    """生成模拟行情数据"""
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=n)
    if trend == "up":
        base = np.linspace(10, 15, n) + np.random.randn(n) * 0.2
    elif trend == "down":
        base = np.linspace(15, 10, n) + np.random.randn(n) * 0.2
    else:
        base = 12 + np.random.randn(n) * 0.3

    df = pd.DataFrame({
        "date": dates,
        "open":   base * (1 - np.abs(np.random.randn(n)) * 0.005),
        "close":  base,
        "high":   base * (1 + np.abs(np.random.randn(n)) * 0.01),
        "low":    base * (1 - np.abs(np.random.randn(n)) * 0.01),
        "volume": np.abs(np.random.randn(n)) * 1e7 + 5e7,
        "amount": np.abs(np.random.randn(n)) * 1e9 + 5e8,
    })
    # 尾盘强势：最后一天收盘接近最高
    df.loc[df.index[-1], "high"] = df["close"].iloc[-1] * 1.001
    return df


def test_indicators():
    """测试各指标计算"""
    c = pd.Series([10, 10.5, 11, 10.8, 11.5, 12, 11.8, 12.5, 13, 12.8])

    ma5 = sma(c, 5)
    assert not ma5.dropna().empty, "MA5计算失败"

    e12 = ema(c, 3)
    assert len(e12) == len(c), "EMA长度不匹配"

    dif, dea, hist = macd(c)
    assert len(dif) == len(c), "MACD长度不匹配"

    r = rsi(c, 5)
    assert r.dropna().between(0, 100).all(), "RSI超出[0,100]范围"

    h = c * 1.01
    l = c * 0.99
    k, d, j = kdj(h, l, c)
    assert len(k) == len(c), "KDJ长度不匹配"

    bu, bm, bl = boll(c, 5)
    valid = bu.dropna().index
    assert (bu[valid] >= bm[valid]).all(), "布林上轨应≥中轨"
    assert (bm[valid] >= bl[valid]).all(), "布林中轨应≥下轨"

    print("✅ 指标计算测试通过")


def test_scoring():
    """测试评分：上升趋势应比下降趋势分高"""
    up_df   = make_df(60, "up")
    down_df = make_df(60, "down")
    flat_df = make_df(60, "flat")

    up_res   = score_stock(up_df)
    down_res = score_stock(down_df)
    flat_res = score_stock(flat_df)

    assert up_res is not None, "上升趋势评分不应为None"
    assert down_res is not None, "下降趋势评分不应为None"

    print(f"  上升趋势评分: {up_res['score']}")
    print(f"  横盘趋势评分: {flat_res['score'] if flat_res else 'N/A'}")
    print(f"  下降趋势评分: {down_res['score']}")

    assert up_res["score"] >= down_res["score"], (
        f"上升趋势({up_res['score']})应>=下降趋势({down_res['score']})"
    )
    assert 0 <= up_res["score"] <= 100, "评分应在[0,100]范围"

    print("✅ 评分逻辑测试通过")


def test_report():
    """测试报告生成（不依赖网络）"""
    from picker import generate_report
    mock_best = {
        "code": "sh.600036",
        "name": "招商银行",
        "price": 42.50,
        "change_pct": 1.23,
        "amount": 3.2e9,
        "score": 75,
        "details": {
            "均线多头排列": True,
            "量能放大": True,
            "MACD金叉": True,
            "MACD柱改善": False,
            "RSI": 58.3,
            "KDJ_J": 72.1,
            "尾盘强度": 0.967,
            "布林位置": 0.62,
        }
    }
    mock_top10 = [mock_best] + [
        {**mock_best, "name": f"股票{i}", "code": f"sh.60000{i}",
         "price": 30 + i, "change_pct": 0.5 * i, "score": 75 - i * 3}
        for i in range(1, 10)
    ]
    path = generate_report(mock_best, mock_top10)
    from pathlib import Path
    assert Path(path).exists(), f"报告文件不存在: {path}"
    content = Path(path).read_text(encoding="utf-8")
    assert "招商银行" in content
    assert "sh.600036" in content
    assert "75" in content
    print(f"✅ 报告生成测试通过，路径: {path}")


if __name__ == "__main__":
    print("=== A股选股工具 · 离线逻辑测试 ===\n")
    test_indicators()
    test_scoring()
    test_report()
    print("\n🎉 所有测试通过！")
