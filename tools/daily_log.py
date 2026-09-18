# -*- coding: utf-8 -*-
"""
每天自动创建当天开发日志（已存在则跳过，不覆盖）。

用法：
    python tools/daily_log.py
"""
import os
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "开发日志")
TEMPLATE = os.path.join(LOG_DIR, "_模板.md")


def main():
    today = date.today().isoformat()  # 例：2026-09-10
    target = os.path.join(LOG_DIR, today + ".md")

    if os.path.exists(target):
        print("今日日志已存在，跳过创建：%s" % target)
        return

    os.makedirs(LOG_DIR, exist_ok=True)

    if os.path.exists(TEMPLATE):
        with open(TEMPLATE, "r", encoding="utf-8") as f:
            content = f.read().replace("YYYY-MM-DD", today)
    else:
        content = (
            "# 开发日志 · %s\n\n"
            "## ✅ 已完成\n- [ ] \n\n"
            "## 📋 待办\n- [ ] \n\n"
            "## 备注\n" % today
        )

    with open(target, "w", encoding="utf-8") as f:
        f.write(content)

    print("已创建今日日志：%s" % target)


if __name__ == "__main__":
    main()
