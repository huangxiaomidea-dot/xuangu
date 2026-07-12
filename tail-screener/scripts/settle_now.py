"""
手动触发一次滚动复盘结算（不重新选股，只结算历史待结算记录）
用法：cd tail-screener && python scripts/settle_now.py
"""

import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import tracker


def main():
    print("=== 手动结算滚动复盘 ===")
    newly_settled = tracker.settle_pending_open_window()
    print(tracker.format_rolling_summary(newly_settled))


if __name__ == "__main__":
    main()
