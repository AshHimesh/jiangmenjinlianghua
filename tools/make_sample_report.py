# -*- coding: utf-8 -*-
"""
生成一份「分析报告 + 标注图表」的样例，用真实行情数据演示阶段 9 的能力。

    .venv\\Scripts\\python.exe tools\\make_sample_report.py

说明：
- 报告里的**分析文字是示例文本**（明确标注，非 AI 实时分析）；
- 图表数据与价位取自**真实K线**（从最近 60 根日线里自动找摆动高低点），
  因此支撑/压力/止盈止损的数字是合理的，不是编造的。

用途：给用户直观看到阶段 9 的成图效果，也作为回归演示工具保留。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import src  # noqa: F401

from src import chart, report
from src.kline import get_kline
from src.symbols import SYMBOL_MAP

SYMBOL = "螺纹钢"
PERIOD = "D"
WINDOW = 60


def swings(df, left=3, right=3):
    """极简摆动点检测：某根K线的高低点在前后各 left/right 根里都是极值，视为摆动点。"""
    highs, lows = [], []
    h = list(df["high"])
    lo = list(df["low"])
    n = len(h)
    for i in range(left, n - right):
        if all(h[i] >= h[j] for j in range(i - left, i + right + 1) if j != i):
            highs.append(i)
        if all(lo[i] <= lo[j] for j in range(i - left, i + right + 1) if j != i):
            lows.append(i)
    return highs, lows


def main():
    df = get_kline(SYMBOL, PERIOD)
    if df is None or len(df) < WINDOW:
        raise SystemExit("K线数据不足，无法生成样例")
    sub = df.tail(WINDOW).reset_index(drop=True)
    closes = [float(v) for v in sub["close"]]
    n = len(sub)

    highs, lows = swings(sub)
    last_high = highs[-1] if highs else int(n * 0.7)
    last_low = lows[-1] if lows else int(n * 0.3)
    swing_high = float(sub["high"][last_high])
    swing_low = float(sub["low"][last_low])
    last = closes[-1]

    # 简单斐波那契回撤位（摆动区间）
    rng = swing_high - swing_low
    fib382 = swing_high - rng * 0.382
    fib618 = swing_high - rng * 0.618
    ext = swing_low + rng * 1.0

    # 浪型：取最近几个摆动点做示意计数（样例用途，非严格艾略特计数）
    pts = sorted(set(lows[-3:] + [last_high]))
    labels = ["①", "②", "③", "④", "⑤"]
    waves = []
    for k, i in enumerate(pts[:4]):
        price = float(sub["low"][i] if i in lows else sub["high"][i])
        waves.append({"label": labels[k], "index": i, "price": round(price, 2)})

    res = chart.render(
        SYMBOL, PERIOD, waves=waves,
        support=[round(fib618, 2), round(swing_low, 2)],
        resistance=[round(fib382, 2), round(swing_high, 2)],
        entry=round(last, 2),
        stop_loss=round(swing_low * 0.995, 2),
        take_profit=[round(fib382, 2), round(swing_high, 2), round(ext, 2)],
        note="样例图：价位取自最近 %d 根日线的真实摆动点（演示用途）" % n,
    )
    if not res.get("ok"):
        raise SystemExit(res.get("error"))

    unit = SYMBOL_MAP[SYMBOL]["unit"]
    answer = (
        "【示例文本】本报告用于演示「分析报告 + 标注图表」能力，文字为演示用样例，"
        "非 AI 实时分析；图上的价位取自真实K线。\n\n"
        "一、多周期判读\n"
        "  日线最近 %d 根里，价格在 %.2f ~ %.2f 区间运行，最新收盘 %.2f（%s）。\n\n"
        "二、浪型计数（示意）\n"
        "  按摆动点标注 %s；当前处于标注段之后的延伸位置，需结合小周期确认。\n\n"
        "三、关键价位（真实数据）\n"
        "  支撑：斐波那契 0.618 回撤 %.2f、摆动低点 %.2f\n"
        "  压力：斐波那契 0.382 回撤 %.2f、摆动高点 %.2f\n\n"
        "四、交易计划（演示口径）\n"
        "  参考入场 %.2f；止损 %.2f（摆动低点下方留缓冲）；分档止盈 %.2f / %.2f / %.2f。\n\n"
        "五、风险提示\n"
        "  本样例不构成投资建议；实际研报请用「生成研报」按钮，由 AI 依据实时数据输出。"
        % (n, min([float(v) for v in sub["low"]]), max([float(v) for v in sub["high"]]),
           last, unit, "、".join(w["label"] for w in waves),
           fib618, swing_low, fib382, swing_high, last,
           swing_low * 0.995, fib382, swing_high, ext)
    )

    out = report.export(
        symbol=SYMBOL,
        question="（样例）请按 skill 流程对螺纹钢做一次研报级分析。",
        answer=answer,
        charts=[res["path"]],
        model="样例（无模型调用）",
        skills=["斐波那契短线入场专家（示例）"],
        quotes={SYMBOL: {"price": last, "change": 0.0,
                         "source": report.source_of(SYMBOL)}},
    )
    if not out.get("ok"):
        raise SystemExit(out.get("error"))

    # 把文件名改成一眼能认出的样例名，避免和真实报告混淆
    import shutil
    renamed = []
    for key, tag in (("html", "html"), ("md", "md")):
        src_p = out[key]
        dst_p = os.path.join(report.reports_dir(), "示例-分析报告样例-%s.%s" % (SYMBOL, tag))
        shutil.move(src_p, dst_p)
        renamed.append(dst_p)
    png_dst = os.path.join(report.reports_dir(), os.path.basename(res["path"]))

    # .md 里引用的是原始 PNG 文件名，改名 HTML 无影响（内嵌 base64）
    print("ok")
    print("html: %s" % renamed[0])
    print("md  : %s" % renamed[1])
    print("png : %s" % png_dst)


if __name__ == "__main__":
    main()
