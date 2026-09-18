# -*- coding: utf-8 -*-
"""
江门金量化 · 分析图表（阶段 9）

把 AI 的分析结论画成一张K线标注图：浪型计数、支撑/压力位、入场、止损、分档止盈。
**图表只出现在导出的报告里**，主界面仍然不显示K线（需求 2.1 / 5.3.2）。

设计要点（来自需求 5.3.2）：
- 浪型与价位由 AI 判定（skill 的核心能力），程序只负责把它们结构化后画出来；
- 红涨绿跌（国内习惯，见 docs/03 配色表）；
- 中文用 Windows 自带字体，缺失时逐级回退，画不出中文就退化为拼音/英文不至于崩。

打包提示：PyInstaller 打包后 matplotlib 会被一并收集，但**中文字体文件在系统目录**，
打包版直接读 C:\\Windows\\Fonts\\，Windows 上始终存在 msyh/simhei，无需打包字体。
"""
import math
import os
from datetime import datetime

import matplotlib

matplotlib.use("Agg")            # 无窗口环境出图
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

from .kline import PERIOD_NAME, get_kline
from .paths import data_path

# 中文字体候选（按清晰度优先级），Windows 自带，实测都存在
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",      # 微软雅黑
    r"C:\Windows\Fonts\msyhbd.ttc",    # 微软雅黑 粗体
    r"C:\Windows\Fonts\simhei.ttf",    # 黑体
    r"C:\Windows\Fonts\simsun.ttc",    # 宋体
]
_font_cache = {"path": None, "checked": False}

# 配色：与 docs/03 设计规范一致
UP = "#E03131"        # 上涨（红）
DOWN = "#12B886"      # 下跌（绿）
TEXT = "#1A1A1A"
SUB = "#8A8A8A"
GRID = "#EBEBEB"

# 标注线颜色
LEVEL_STYLE = {
    "support": {"color": "#1C7ED6", "ls": "--", "lw": 1.2, "label": "支撑位"},
    "resistance": {"color": "#F76707", "ls": "--", "lw": 1.2, "label": "压力位"},
    "entry": {"color": "#495057", "ls": "-", "lw": 1.4, "label": "入场位"},
    "stop_loss": {"color": "#C92A2A", "ls": "--", "lw": 1.5, "label": "止损位"},
    "take_profit": {"color": "#0CA678", "ls": "-", "lw": 1.2, "label": "止盈位"},
}


def st_label(key, j):
    """某类价位的图上标签（分档止盈带序号 TP1/TP2/…）。"""
    base = LEVEL_STYLE[key]["label"]
    return base + ("TP%d" % (j + 1)) if key == "take_profit" else base


def resolve_font():
    """返回可用的中文字体文件路径；找不到返回 None（图上中文会变方块，但不崩）。"""
    if not _font_cache["checked"]:
        _font_cache["checked"] = True
        for p in FONT_CANDIDATES:
            if os.path.exists(p):
                _font_cache["path"] = p
                break
    return _font_cache["path"]


def _font(size=None):
    p = resolve_font()
    if not p:
        return None
    return FontProperties(fname=p, size=size) if size else FontProperties(fname=p)


def reports_dir():
    d = data_path("reports")
    os.makedirs(d, exist_ok=True)
    return d


def _safe_name(name):
    """Windows 文件名里不能出现 \\ / : * ? " < > |，品种名里的 '/'（美元兑离岸人民币没有）替换掉。"""
    return "".join(c if c not in '\\/:*?"<>|' else "_" for c in name).strip()


def _to_index(item, dates, warnings):
    """把 AI 给的单个浪型定位转成窗口内的K线下标。支持 index（0 基）或 date。"""
    n = len(dates)
    if not isinstance(item, dict):
        return None
    idx = item.get("index")
    if idx is not None:
        try:
            i = int(idx)
        except (TypeError, ValueError):
            return None
        # 允许 AI 用 1 基下标或负数：做个宽容换算，但超出窗口就放弃并提示
        if 0 <= i < n:
            return i
        if 1 <= i <= n:
            return i - 1
        if -n <= i < 0:
            return n + i
        warnings.append("浪型标记 index=%s 超出窗口（0~%d），已忽略" % (idx, n - 1))
        return None
    d = item.get("date")
    if d:
        d = str(d).strip()
        for cand in (d, d[:10], d.replace("/", "-")):
            for i, dt in enumerate(dates):
                if str(dt).startswith(cand):
                    return i
        warnings.append("浪型标记 date=%s 没有对应K线，已忽略" % d)
    return None


def render(symbol, period, waves=None, support=None, resistance=None,
           entry=None, stop_loss=None, take_profit=None, note=None, limit=120):
    """
    生成一张K线标注图。

    :return: dict(ok, path, bars, warnings, error)
    """
    df = get_kline(symbol, period)
    if df is None or len(df) == 0:
        return {"ok": False, "error": "%s 暂无%sK线数据，画不了图。" % (symbol, PERIOD_NAME.get(period, period))}

    sub = df.tail(max(10, min(int(limit or 120), 300))).reset_index(drop=True)
    n = len(sub)
    dates = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for d in sub["datetime"]]
    o = [float(v) for v in sub["open"]]
    h = [float(v) for v in sub["high"]]
    lo = [float(v) for v in sub["low"]]
    c = [float(v) for v in sub["close"]]

    warnings = []

    fig, ax = plt.subplots(figsize=(12.5, 7.0), dpi=110)
    fp = _font()

    # ---- K线：影线 + 实体（红涨绿跌）----
    body_w = 0.62
    for i in range(n):
        up = c[i] >= o[i]
        color = UP if up else DOWN
        ax.vlines(i, lo[i], h[i], color=color, linewidth=1.0, zorder=2)
        top, bottom = max(o[i], c[i]), min(o[i], c[i])
        height = top - bottom
        if height <= 0:
            height = (max(h) - min(lo)) * 0.0006 or 1e-9
        ax.add_patch(Rectangle((i - body_w / 2, bottom), body_w, height,
                               facecolor=color if not up else "white",
                               edgecolor=color, linewidth=1.0, zorder=3))

    # ---- 均线（skill 依赖 MA20/MA40，数据够就画）----
    for win, color, name in ((20, "#F59F00", "MA20"), (40, "#7048E8", "MA40")):
        if n >= win:
            ma = [sum(c[i - win + 1:i + 1]) / win for i in range(win - 1, n)]
            ax.plot(range(win - 1, n), ma, color=color, linewidth=1.0, alpha=0.85,
                    label=name, zorder=4)

    # ---- 纵轴范围：把所有标注价位包进来，避免止盈止损线画在图外 ----
    levels = []
    for key in ("entry", "stop_loss"):
        v = locals().get(key)
        if v is not None:
            try:
                levels.append(float(v))
            except (TypeError, ValueError):
                pass
    for seq in (support, resistance, take_profit):
        for v in (seq or []):
            try:
                levels.append(float(v))
            except (TypeError, ValueError):
                continue
    for w in (waves or []):
        p = w.get("price") if isinstance(w, dict) else None
        try:
            if p is not None:
                levels.append(float(p))
        except (TypeError, ValueError):
            continue

    ymin, ymax = min(lo), max(h)
    span = (ymax - ymin) or 1.0
    if levels:
        ymin = min(ymin, min(levels))
        ymax = max(ymax, max(levels))
    pad = (ymax - ymin) * 0.06 or span * 0.06
    ax.set_xlim(-1, n + max(6, int(n * 0.08)))     # 右侧留白放价位标签
    ax.set_ylim(ymin - pad, ymax + pad)

    # ---- 水平标注线 + 右侧文字 ----
    # 先收集所有价位（AI 经常把同一个价位同时给成「压力位」和「止盈 TP1」，
    # 若各画各的，两条线与两个标签会完全叠在一起），同价位合并成一条线、标签拼接。
    level_items = []                     # (y, style_key, label)
    for key, values in (("support", support), ("resistance", resistance),
                        ("take_profit", take_profit)):
        for j, v in enumerate(values or []):
            try:
                y = float(v)
            except (TypeError, ValueError):
                continue
            label = st_label(key, j)
            level_items.append((y, key, label))
    for key in ("entry", "stop_loss"):
        try:
            y = float(locals().get(key))
        except (TypeError, ValueError):
            continue
        level_items.append((y, key, LEVEL_STYLE[key]["label"]))

    merged = {}
    for y, key, label in level_items:
        slot = merged.setdefault(round(y, 4), {"y": y, "key": key, "labels": []})
        if label not in slot["labels"]:
            slot["labels"].append(label)

    # 标签防重叠：按价位排序后逐个往下找空位（相邻标签至少留出约 2.2% 量程）
    used_text_y = []
    tol = (ymax - ymin) * 0.022 or 1e-9
    for item in sorted(merged.values(), key=lambda d: d["y"]):
        y, st = item["y"], LEVEL_STYLE[item["key"]]
        ax.axhline(y, color=st["color"], linestyle=st["ls"], linewidth=st["lw"],
                   alpha=0.9, zorder=1)
        text_y = y
        while any(abs(text_y - u) < tol for u in used_text_y):
            text_y += tol
        used_text_y.append(text_y)
        text = "%s  %g" % (" / ".join(item["labels"]), y)
        ax.annotate(text, xy=(1.0, text_y),
                    xycoords=("axes fraction", "data"), xytext=(5, 0),
                    textcoords="offset points", va="center", ha="left",
                    fontsize=8.5, color=st["color"], fontproperties=_font(8.5), zorder=6)

    # ---- 浪型标注 ----
    for k, w in enumerate(waves or []):
        if not isinstance(w, dict):
            continue
        label = str(w.get("label") or "").strip()
        i = _to_index(w, dates, warnings)
        if i is None or not label:
            continue
        try:
            y = float(w.get("price"))
        except (TypeError, ValueError):
            continue
        # 交替上下偏移，减少相邻浪标重叠
        dy = 14 if k % 2 == 0 else -18
        ax.scatter([i], [y], s=16, color=TEXT, zorder=6)
        ax.annotate(label, xy=(i, y), xytext=(0, dy), textcoords="offset points",
                    ha="center", fontsize=11, color=TEXT, fontproperties=_font(11), zorder=6)

    # ---- 坐标轴 ----
    step = max(1, n // 9)
    ticks = list(range(0, n, step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([dates[i] for i in ticks], rotation=0, fontsize=8, color=SUB)
    ax.tick_params(axis="y", labelsize=8, colors=SUB)
    ax.grid(True, axis="y", color=GRID, linewidth=0.7, alpha=0.9, zorder=0)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(GRID)

    title = "%s · %s（最近 %d 根）" % (symbol, PERIOD_NAME.get(period, period), n)
    if fp:
        ax.set_title(title, fontsize=13, color=TEXT, fontproperties=_font(13), loc="left", pad=10)
    else:
        ax.set_title(title, fontsize=13, color=TEXT, loc="left", pad=10)

    if note:
        ax.text(0, -0.09, str(note), transform=ax.transAxes, fontsize=8.5, color=SUB,
                fontproperties=_font(8.5))

    src = ("数据来源：新浪财经 · 免费源（上海金为上海黄金交易所）｜生成时间 %s"
           % datetime.now().strftime("%Y-%m-%d %H:%M"))
    ax.text(1, -0.09, src, transform=ax.transAxes, fontsize=8, color=SUB,
            ha="right", fontproperties=_font(8))

    # 图例（只放有数据的项）
    handles, labels_ = ax.get_legend_handles_labels()
    if handles:
        leg = ax.legend(handles, labels_, loc="upper left", fontsize=8, frameon=False)
        if fp:
            for t in leg.get_texts():
                t.set_fontproperties(_font(8))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(reports_dir(), "%s-%s-%s.png" % (stamp, _safe_name(symbol), period))
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)

    return {
        "ok": True,
        "path": path,
        "bars": n,
        "period": period,
        "warnings": warnings,
    }
