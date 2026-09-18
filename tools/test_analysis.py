# -*- coding: utf-8 -*-
"""测试多周期技术面报告生成。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis import build_report, detect_symbols

OUT = []


def log(*args):
    OUT.append(" ".join(str(a) for a in args))


log("=== 1. 品种识别测试 ===")
tests = [
    ("黄金现在怎么看？", "现货黄金"),
    ("白银和黄金哪个强", "现货黄金"),
    ("纳指是不是要跌了", "螺纹钢"),
    ("帮我看下螺纹钢和纯碱", None),
    ("美元指数走强对大宗的影响", "WTI原油"),
    ("大盘怎么样", None),
]
for q, focus in tests:
    log("  问: %-24s focus=%-8s -> %s" % (q, focus, detect_symbols(q, focus)))

log("")
log("=== 2. 螺纹钢（全周期）报告 ===")
txt, used = build_report("螺纹钢")
log("已用周期: %s" % used)
log(txt or "(无)")

log("")
log("=== 3. 现货黄金报告 ===")
txt2, used2 = build_report("现货黄金")
log("已用周期: %s" % used2)
log(txt2 or "(无)")

log("")
log("=== 4. 美元指数报告 ===")
txt3, used3 = build_report("美元指数")
log("已用周期: %s" % used3)
log(txt3 or "(无)")

log("")
log("=== 5. token 体量估算 ===")
for nm, t in [("螺纹钢", txt), ("现货黄金", txt2), ("美元指数", txt3)]:
    if t:
        log("  %-8s 字符数=%d  约 %d tokens" % (nm, len(t), len(t) // 2))

with open("tools/_analysis_test.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("done")
