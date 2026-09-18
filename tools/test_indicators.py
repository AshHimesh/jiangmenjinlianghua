# -*- coding: utf-8 -*-
"""验证增强指标：MA40 / 背离 / 斐波那契扩展 / 汇聚区 / K线形态。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis import build_report

OUT = []


def log(*args):
    OUT.append(" ".join(str(a) for a in args))


for name in ["现货黄金", "螺纹钢"]:
    txt, used = build_report(name)
    log("=" * 70)
    log("%s   周期: %s" % (name, used))
    log("=" * 70)
    log(txt or "(无)")
    log("")

with open("tools/_indicator_test.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("done")
