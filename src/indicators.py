# -*- coding: utf-8 -*-
"""
江门金量化 · 技术指标计算

纯 pandas 实现（不依赖 TA-Lib）：
    MA(5/10/20/40/60) / MACD / RSI / KDJ / BOLL / 涨跌幅 / 量能
    斐波那契回撤 + 扩展位 + 多组汇聚区
    背离检测（MACD柱、RSI）
    K线形态（Pin Bar / 吞没 / Inside Bar）
    摆动结构高低点（SMC / 波浪结构基础）
"""
import numpy as np
import pandas as pd

MAX_BARS = 400       # 计算指标时最多回溯多少根
FIB_LOOKBACK = 120   # 斐波那契/结构分析窗口
DIV_LOOKBACK = 90    # 背离检测窗口


# ---------------- 基础指标 ----------------

def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def macd(close, fast=12, slow=26, signal=9):
    dif = ema(close, fast) - ema(close, slow)
    dea = ema(dif, signal)
    hist = (dif - dea) * 2
    return dif, dea, hist


def rsi(close, n=14):
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    avg_up = up.ewm(alpha=1.0 / n, adjust=False).mean()
    avg_down = down.ewm(alpha=1.0 / n, adjust=False).mean()
    rs = avg_up / avg_down.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def kdj(df, n=9, m1=3, m2=3):
    low_n = df["low"].rolling(n).min()
    high_n = df["high"].rolling(n).max()
    rng = (high_n - low_n).replace(0, np.nan)
    rsv = ((df["close"] - low_n) / rng * 100).fillna(50)
    k = rsv.ewm(alpha=1.0 / m1, adjust=False).mean()
    d = k.ewm(alpha=1.0 / m2, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


def boll(close, n=20, k=2):
    mid = close.rolling(n).mean()
    std = close.rolling(n).std()
    return mid + k * std, mid, mid - k * std


# ---------------- 结构 ----------------

def swing_points(df, left=2, right=2):
    """摆动高低点，返回 [(时间, 价格), ...]。"""
    highs, lows = [], []
    if df is None or len(df) < left + right + 1:
        return highs, lows
    h = df["high"].values
    l = df["low"].values
    t = df["datetime"].values
    for i in range(left, len(df) - right):
        if h[i] == h[i - left:i + right + 1].max():
            highs.append((pd.Timestamp(t[i]), float(h[i])))
        if l[i] == l[i - left:i + right + 1].min():
            lows.append((pd.Timestamp(t[i]), float(l[i])))
    return highs, lows


def fib_levels(df, lookback=FIB_LOOKBACK):
    """单组斐波那契回撤（基于观察窗口的高低点）。"""
    recent = df.tail(lookback)
    n = len(recent)
    if n < 10:
        return None
    hi = float(recent["high"].max())
    lo = float(recent["low"].min())
    diff = hi - lo
    if diff <= 0:
        return None
    ratios = [0.236, 0.382, 0.5, 0.618, 0.786]
    return {"high": hi, "low": lo, "levels": {r: hi - diff * r for r in ratios}, "bars": n}


def _swing_legs(df, max_legs=3, min_ratio=0.3):
    """
    取最近的几条**有效**摆动腿（过滤掉幅度过小的噪声摆动）。

    小周期数据里充满微小波动，若全部计入，会算出"8重汇聚"这类假信号。
    这里只保留幅度 ≥ 最大腿幅度 min_ratio 的腿。
    """
    d = df.tail(220).reset_index(drop=True)
    if len(d) < 30:
        return []
    highs, lows = swing_points(d, left=3, right=3)
    pts = sorted([(t, v, "高") for t, v in highs] + [(t, v, "低") for t, v in lows])
    if len(pts) < 3:
        return []

    cand = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        size = abs(b[1] - a[1])
        cand.append((size, a, b))
    biggest = max(c[0] for c in cand) if cand else 0
    if biggest <= 0:
        return []
    valid = [c for c in cand if c[0] >= biggest * min_ratio]
    return [(a, b) for _, a, b in valid[-max_legs:]]


def fib_confluence(df, max_sets=3, tol_pct=0.35):
    """
    多组斐波那契回撤的**汇聚区**检测（对应 skill 的"多重汇聚"要求）。
    取最近几条有效摆动腿分别画回撤，找出 2 组以上重叠的区域。
    """
    legs = _swing_legs(df, max_legs=max_sets)
    if len(legs) < 2:
        return None

    levels = []
    for li, (a, b) in enumerate(legs):
        hi, lo = max(a[1], b[1]), min(a[1], b[1])
        diff = hi - lo
        if diff <= 0:
            continue
        tag = "%s→%s" % (a[2], b[2])
        for r in (0.382, 0.5, 0.618, 0.786):
            levels.append({"v": hi - diff * r, "r": r, "tag": tag, "leg": li})

    if len(levels) < 2:
        return None

    levels.sort(key=lambda x: x["v"])
    used = [False] * len(levels)
    zones = []
    for i in range(len(levels)):
        if used[i]:
            continue
        group = [levels[i]]
        used[i] = True
        for j in range(i + 1, len(levels)):
            if used[j]:
                continue
            if abs(levels[j]["v"] - levels[i]["v"]) / abs(levels[i]["v"]) * 100 <= tol_pct:
                group.append(levels[j])
                used[j] = True
        # 只统计**不同的摆动腿**数量（同一腿的 4 个回撤位不算多组汇聚）
        leg_ids = sorted({g["leg"] for g in group})
        if len(leg_ids) >= 2:
            vals = [g["v"] for g in group]
            # 去重后的比例，例如 0.382/0.5/0.618 —— 告诉 AI 是哪几个斐波那契位在汇聚
            ratios = sorted({g["r"] for g in group})
            zones.append({
                "low": min(vals), "high": max(vals),
                "legs": len(leg_ids),
                "levels": ["%.3f" % r for r in ratios],
                "score": len(leg_ids),
            })

    if not zones:
        return None
    zones.sort(key=lambda z: -z["score"])
    return zones[:4]


def fib_extension(df):
    """斐波那契扩展位（用于目标位 TP1~TP4），基于最近一条有效摆动腿。"""
    legs = _swing_legs(df, max_legs=1)
    if not legs:
        return None
    a, b = legs[-1]
    diff = b[1] - a[1]
    if diff == 0:
        return None
    close = df["close"]
    base = float(close.iloc[-1])
    ratios = [0.382, 0.618, 1.0, 1.618]
    return {
        "from": a[1], "to": b[1], "dir": "上" if diff > 0 else "下",
        "targets": {r: base + diff * r for r in ratios},
    }


# ---------------- 背离 ----------------

def detect_divergence(df, lookback=DIV_LOOKBACK):
    """检测 MACD柱 / RSI 与价格的顶背离、底背离。"""
    d = df.tail(lookback).reset_index(drop=True)
    if len(d) < 40:
        return []
    close = d["close"]
    _, _, hist = macd(close)
    r = rsi(close, 14)
    highs, lows = swing_points(d, left=2, right=2)
    idx = {t: i for i, t in enumerate(d["datetime"])}
    out = []

    def _pair(items):
        if len(items) < 2:
            return None
        (t1, p1), (t2, p2) = items[-2], items[-1]
        i1, i2 = idx.get(t1), idx.get(t2)
        if i1 is None or i2 is None:
            return None
        return p1, p2, i1, i2

    ph = _pair(highs)
    if ph:
        p1, p2, i1, i2 = ph
        if p2 > p1 and hist.iloc[i2] < hist.iloc[i1] and hist.iloc[i2] < hist.iloc[i1] * 0.9:
            out.append("顶背离：价格创新高 %.4g→%.4g，MACD柱走弱 %.3f→%.3f" %
                       (p1, p2, hist.iloc[i1], hist.iloc[i2]))
        if p2 > p1 and r.iloc[i2] < r.iloc[i1] - 2:
            out.append("顶背离（RSI）：价格新高但 RSI 走低 %.1f→%.1f" % (r.iloc[i1], r.iloc[i2]))

    pl = _pair(lows)
    if pl:
        p1, p2, i1, i2 = pl
        if p2 < p1 and hist.iloc[i2] > hist.iloc[i1] and hist.iloc[i2] > hist.iloc[i1] * 0.9:
            out.append("底背离：价格创新低 %.4g→%.4g，MACD柱走强 %.3f→%.3f" %
                       (p1, p2, hist.iloc[i1], hist.iloc[i2]))
        if p2 < p1 and r.iloc[i2] > r.iloc[i1] + 2:
            out.append("底背离（RSI）：价格新低但 RSI 走高 %.1f→%.1f" % (r.iloc[i1], r.iloc[i2]))
    return out


# ---------------- K线形态（价格行为） ----------------

def candle_patterns(df, n=4):
    """最近 n 根的 K 线形态：Pin Bar / 吞没 / Inside Bar。"""
    d = df.tail(n + 2).reset_index(drop=True)
    if len(d) < 3:
        return []
    out = []
    for i in range(2, len(d)):
        o, h, l, c = (float(d["open"].iloc[i]), float(d["high"].iloc[i]),
                      float(d["low"].iloc[i]), float(d["close"].iloc[i]))
        po, ph, pl, pc = (float(d["open"].iloc[i - 1]), float(d["high"].iloc[i - 1]),
                          float(d["low"].iloc[i - 1]), float(d["close"].iloc[i - 1]))
        ts = pd.Timestamp(d["datetime"].iloc[i]).strftime("%m-%d %H:%M")
        rng = h - l
        if rng <= 0:
            continue
        body = abs(c - o)
        upper = h - max(o, c)
        lower = min(o, c) - l
        tag = None
        if lower > max(body, rng * 0.6) and upper < rng * 0.2:
            tag = "锤子线/看涨Pin Bar"
        elif upper > max(body, rng * 0.6) and lower < rng * 0.2:
            tag = "射击之星/看跌Pin Bar"
        elif c > o and pc < po and c >= po and o <= pc:
            tag = "看涨吞没"
        elif c < o and pc > po and c <= po and o >= pc:
            tag = "看跌吞没"
        elif h < ph and l > pl:
            tag = "Inside Bar（内包线）"
        if tag:
            out.append("%s %s" % (ts, tag))
    return out[-3:]


# ---------------- 汇总计算 ----------------

def _fmt(v, digits=2):
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return "-"
    try:
        return ("%%.%df" % digits) % float(v)
    except (TypeError, ValueError):
        return "-"


def compute(df):
    """计算最新一根K线上的全部指标值。"""
    if df is None or len(df) < 5:
        return None
    d = df.tail(MAX_BARS).reset_index(drop=True)
    close = d["close"]

    out = {"bars": len(df), "close": float(close.iloc[-1])}

    # 均线（含 skill 要求的 MA40）
    for n in (5, 10, 20, 40, 60):
        out["ma%d" % n] = float(close.rolling(n).mean().iloc[-1]) if len(close) >= n else None

    # MACD
    if len(close) >= 35:
        dif, dea, hist = macd(close)
        out["dif"] = float(dif.iloc[-1])
        out["dea"] = float(dea.iloc[-1])
        out["macd_hist"] = float(hist.iloc[-1])
        out["macd_prev_hist"] = float(hist.iloc[-2])
    else:
        out["dif"] = out["dea"] = out["macd_hist"] = out["macd_prev_hist"] = None

    # RSI / KDJ / BOLL
    out["rsi14"] = float(rsi(close, 14).iloc[-1]) if len(close) >= 15 else None
    out["rsi6"] = float(rsi(close, 6).iloc[-1]) if len(close) >= 7 else None
    if len(close) >= 12:
        k, dd, j = kdj(d)
        out["kdj_k"], out["kdj_d"], out["kdj_j"] = float(k.iloc[-1]), float(dd.iloc[-1]), float(j.iloc[-1])
    else:
        out["kdj_k"] = out["kdj_d"] = out["kdj_j"] = None
    if len(close) >= 20:
        up, mid, low = boll(close)
        out["boll_up"], out["boll_mid"], out["boll_low"] = float(up.iloc[-1]), float(mid.iloc[-1]), float(low.iloc[-1])
    else:
        out["boll_up"] = out["boll_mid"] = out["boll_low"] = None

    # 涨跌幅
    for n, key in ((1, "chg1"), (5, "chg5"), (20, "chg20")):
        if len(close) > n:
            base = float(close.iloc[-1 - n])
            out[key] = (out["close"] - base) / base * 100 if base else 0.0
        else:
            out[key] = None

    # 量能
    vol = d["volume"]
    if len(vol) >= 10 and vol.tail(10).sum() > 0:
        rv, pv = float(vol.tail(5).mean()), float(vol.tail(10).head(5).mean())
        out["vol_ratio"] = (rv / pv) if pv else None
    else:
        out["vol_ratio"] = None

    out["fib"] = fib_levels(d)
    out["confluence"] = fib_confluence(d)
    out["extension"] = fib_extension(d)
    out["divergence"] = detect_divergence(d)
    out["patterns"] = candle_patterns(d)
    highs, lows = swing_points(d.tail(120).reset_index(drop=True))
    out["last_highs"], out["last_lows"] = highs[-3:], lows[-3:]
    return out


def summarize(df, label):
    """把某个周期的指标汇总成一段紧凑文本（供 AI 阅读）。"""
    c = compute(df)
    if not c:
        return None

    lines = []
    close = c["close"]

    # 1) 价格 + 均线
    ma = []
    for n in (20, 40):
        v = c.get("ma%d" % n)
        if v is not None:
            ma.append("MA%d=%.4g(价在%s)" % (n, v, "上" if close >= v else "下"))
    for n in (5, 60):
        v = c.get("ma%d" % n)
        if v is not None:
            ma.append("MA%d=%.4g" % (n, v))
    if c.get("ma20") is not None and c.get("ma40") is not None:
        ma.append("MA20%sMA40(%s排列)" % (">" if c["ma20"] > c["ma40"] else "<",
                                          "多头" if c["ma20"] > c["ma40"] else "空头"))
    chg = ["%s%+.2f%%" % (nm, c[k]) for k, nm in
           (("chg1", "本根"), ("chg5", "近5根"), ("chg20", "近20根")) if c.get(k) is not None]
    lines.append("%s：收%.4g | %s | %s" % (label, close, " ".join(ma), " ".join(chg)))

    # 2) 摆动指标
    osc = []
    if c.get("dif") is not None:
        cross = ""
        if c["macd_prev_hist"] is not None and c["macd_hist"] is not None:
            if c["macd_prev_hist"] < 0 <= c["macd_hist"]:
                cross = "，刚金叉"
            elif c["macd_prev_hist"] > 0 >= c["macd_hist"]:
                cross = "，刚死叉"
        zero = "零轴上" if c["dif"] > 0 else "零轴下"
        osc.append("MACD：DIF=%.4g DEA=%.4g 柱=%.4g（%s%s）" % (c["dif"], c["dea"], c["macd_hist"], zero, cross))
    if c.get("rsi14") is not None:
        osc.append("RSI14=%.1f" % c["rsi14"])
    if c.get("kdj_k") is not None:
        def jtag(j):
            if j is None:
                return ""
            if j > 100:
                return "，J超买钝化"
            if j < 0:
                return "，J超卖钝化"
            return ""
        osc.append("KDJ：K=%.1f D=%.1f J=%.1f%s" % (c["kdj_k"], c["kdj_d"], c["kdj_j"], jtag(c["kdj_j"])))
    if osc:
        lines.append("      " + " | ".join(osc))

    # 3) 布林带 + 量能
    extra = []
    if c.get("boll_up") is not None:
        pos = "上轨外" if close > c["boll_up"] else ("下轨外" if close < c["boll_low"] else
                                                   ("中轨上" if close >= c["boll_mid"] else "中轨下"))
        extra.append("BOLL：上%.4g 中%.4g 下%.4g（价在%s）" % (c["boll_up"], c["boll_mid"], c["boll_low"], pos))
    if c.get("vol_ratio") is not None:
        extra.append("量能比前5根 %+.0f%%" % ((c["vol_ratio"] - 1) * 100))
    if extra:
        lines.append("      " + " | ".join(extra))

    # 4) 斐波那契：回撤 + 扩展 + 汇聚
    fib = c.get("fib")
    if fib:
        lv = fib["levels"]
        lines.append("      斐波那契回撤(近%d根 高%.4g/低%.4g)：0.382=%.4g 0.5=%.4g 0.618=%.4g 0.786=%.4g"
                     % (fib.get("bars", FIB_LOOKBACK), fib["high"], fib["low"],
                        lv[0.382], lv[0.5], lv[0.618], lv[0.786]))
    ext = c.get("extension")
    if ext:
        t = ext["targets"]
        lines.append("      斐波那契扩展(自%.4g→%.4g %s)：0.382=%.4g 0.618=%.4g 1.0=%.4g 1.618=%.4g"
                     % (ext["from"], ext["to"], ext["dir"],
                        t[0.382], t[0.618], t[1.0], t[1.618]))
    conf = c.get("confluence")
    if conf:
        zs = "；".join("%.4g~%.4g（%d组重叠，汇聚位 %s）" % (z["low"], z["high"], z["legs"], "/".join(z["levels"]))
                       for z in conf[:2])
        lines.append("      ★斐波那契汇聚区：%s" % zs)

    # 5) 背离 + K线形态
    div = c.get("divergence")
    if div:
        lines.append("      ⚠背离信号：" + "；".join(div[:2]))
    pat = c.get("patterns")
    if pat:
        lines.append("      K线形态：" + "；".join(pat))

    # 6) 结构高低点
    hs, ls = c.get("last_highs") or [], c.get("last_lows") or []
    if hs or ls:
        sh = "，".join("%.4g(%s)" % (v, t.strftime("%m-%d")) for t, v in hs[-2:])
        sl = "，".join("%.4g(%s)" % (v, t.strftime("%m-%d")) for t, v in ls[-2:])
        lines.append("      近期结构：高点 %s | 低点 %s" % (sh or "-", sl or "-"))

    return "\n".join(lines)
