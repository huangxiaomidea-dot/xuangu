#!/usr/bin/env python3
"""
定时调度器：每个交易日下午 14:45 运行选股
"""

import logging
import time
from datetime import datetime

import schedule

from picker import run

log = logging.getLogger(__name__)

# 中国法定节假日（需每年更新，此处列出2025年）
HOLIDAYS_2025 = {
    "20250101", "20250128", "20250129", "20250130", "20250131",
    "20250201", "20250202", "20250203", "20250204",
    "20250404", "20250430", "20250501", "20250502",
    "20250531", "20250601", "20250602",
    "20251001", "20251002", "20251003", "20251004",
    "20251005", "20251006", "20251007",
}

HOLIDAYS_2026 = {
    "20260101", "20260102",
    "20260217", "20260218", "20260219", "20260220",
    "20260221", "20260222", "20260223", "20260224",
    "20260406", "20260407", "20260408",
    "20260501", "20260502", "20260503", "20260504", "20260505",
    "20261001", "20261002", "20261003", "20261004",
    "20261005", "20261006", "20261007", "20261008",
}

ALL_HOLIDAYS = HOLIDAYS_2025 | HOLIDAYS_2026


def is_trading_day() -> bool:
    today = datetime.now()
    if today.weekday() >= 5:  # 周六、周日
        return False
    if today.strftime("%Y%m%d") in ALL_HOLIDAYS:
        return False
    return True


def job():
    if not is_trading_day():
        log.info("今日非交易日，跳过选股")
        return
    log.info("触发每日选股任务...")
    run()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    schedule.every().day.at("14:45").do(job)
    log.info("调度器已启动，等待每日 14:45 执行选股...")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
