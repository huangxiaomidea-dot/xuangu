# A股每日选股工具

每个交易日下午 **14:45** 自动运行，从 A 股主板/创业板中筛选出**次日开盘上涨概率最大**的一支股票，并生成 HTML 报告。

## 快速开始

```bash
cd stock_picker
pip install -r requirements.txt

# 立即运行一次选股（测试/手动触发）
python picker.py

# 启动每日定时调度（14:45 自动运行）
python scheduler.py
```

报告输出到 `output/` 目录：
- `output/latest.html`  —— 最新报告（始终覆盖）
- `output/report_YYYYMMDD.html`  —— 每日存档
- `output/result_YYYYMMDD.json`  —— 结构化数据

## 选股算法

从流动性最好的前 300 支股票（主板+创业板，价格 3-200 元，排除 ST）中，按 7 个技术指标评分（满分 100）：

| 指标 | 分值 | 说明 |
|------|------|------|
| 均线多头排列 | 20 | 收盘 > MA5 > MA10 > MA20 |
| 量能放大 | 15 | 今日量 > 5日均量 × 1.5 |
| MACD 改善 | 20 | 金叉且柱状线上升各得10分 |
| RSI 健康 | 10 | RSI(14) 在 40~70 区间 |
| KDJ J 上行 | 10 | J 值在 20~85 且上升 |
| 尾盘强势 | 15 | 收盘/最高 ≥ 0.95 |
| 布林位置 | 10 | 价格在布林中轨到上轨之间 |

## 数据源

使用 [BaoStock](http://baostock.com/)，免费、无需注册、覆盖全部 A 股历史行情。

## 用 cron 定时运行

```cron
# 每个工作日 14:45 运行
45 14 * * 1-5 cd /path/to/reception/stock_picker && python picker.py
```

## 免责声明

本工具仅供学习与技术研究，不构成投资建议。股市有风险，投资需谨慎。
