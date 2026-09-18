# -*- coding: utf-8 -*-
"""
江门金量化 · 多周期技术面分析

把各周期的技术指标汇总成给 AI 阅读的报告。
周期按权重从高到低排列（周线 > 日线 > 12H > 4H > 1H > 15M > 5M），
提示词中会明确告知 AI「大周期权重更高」。
"""
import threading

from .indicators import summarize
from .kline import PERIODS, PERIOD_NAME, get_kline
from .symbols import SYMBOL_MAP

# 单次提问最多分析几个品种（控制 token 消耗）
MAX_SYMBOLS = 3

# 品种别名（用于从用户问题中识别提到的品种）
# 注意：别名之间存在包含关系（黄金 / 黄金ETF、原油 / 布伦特原油、美元 / 美元兑离岸人民币），
# 因此 detect_symbols 按「命中的别名长度」降序取，长的优先，避免短别名抢走长别名。
ALIASES = {
    "现货黄金": ["现货黄金", "黄金", "金价", "伦敦金", "xau", "gold"],
    "现货白银": ["现货白银", "白银", "银价", "伦敦银", "xag", "silver"],
    "上海金": ["上海金", "au99.99", "au9999", "上金所", "上海黄金"],
    "沪金AU": ["沪金au", "沪金", "沪金主力", "au0", "shfe金"],
    "沪银AG": ["沪银ag", "沪银", "沪银主力", "ag0"],
    "铜": ["现货铜", "美铜", "comex铜", "铜价", "沪铜", "铜"],
    "WTI原油": ["wti", "美油", "原油", "油价", "crude", "oil"],
    "布伦特原油": ["布伦特原油", "布伦特", "布油", "brent", "ukoil"],
    "纳斯达克100": ["纳斯达克100", "纳斯达克", "纳指", "ndx", "nasdaq"],
    "标普500": ["标普500", "标普", "spx", "s&p"],
    "美元指数": ["美元指数", "美指", "dxy", "美元"],
    "恒生指数": ["恒生指数", "恒指", "hsi", "港股"],
    "螺纹钢": ["螺纹钢", "螺纹", "rb"],
    "铁矿石": ["铁矿石", "铁矿", "i0"],
    "焦煤": ["焦煤", "jm"],
    "玻璃": ["玻璃", "fg"],
    "纯碱": ["纯碱", "sa"],
    "甲醇": ["甲醇", "ma"],
    "乙二醇": ["乙二醇", "eg"],
    "上证指数": ["上证指数", "上证", "大盘", "沪指"],
    "沪深300": ["沪深300", "hs300", "csi300", "沪深"],
    "创业板指": ["创业板指", "创业板", "创指", "399006"],
    "科创50": ["科创50", "科创板50", "科创"],
    "黄金ETF": ["黄金etf", "518880", "黄金基金"],
    "美元兑离岸人民币": ["美元兑离岸人民币", "离岸人民币", "usdcnh", "cnh", "离岸汇率"],
}


def detect_symbols(question, focus=None, limit=MAX_SYMBOLS):
    """
    从用户问题中识别提到的品种；focus（当前查看的品种）永远排第一。

    命中规则：按「命中的别名长度」降序取。这样问「黄金ETF」时命中的是
    「黄金etf」(6 字) 而不是「现货黄金」的别名「黄金」(2 字)；
    问「布伦特原油」时不会被「WTI原油」的别名「原油」抢走。
    """
    q = (question or "").lower()
    found = []
    if focus and focus in SYMBOL_MAP:
        found.append(focus)

    hits = []
    for name in SYMBOL_MAP:
        if name in found:
            continue
        best_len, best_pos = 0, 0
        for alias in ALIASES.get(name, [name]):
            a = (alias or "").lower()
            if not a:
                continue
            pos = q.find(a)
            if pos < 0:
                continue
            # 同一品种内取更靠前的命中位置；若新别名更长则改用更长者
            if len(a) > best_len or (best_len and len(a) == best_len and pos < best_pos):
                best_len, best_pos = len(a), pos
        if best_len:
            hits.append((best_len, best_pos, name))

    # 先按别名长度降序（越长越具体），长度相同则按在问题里出现的先后
    hits.sort(key=lambda x: (-x[0], x[1]))
    for _length, _pos, name in hits:
        if len(found) >= limit:
            break
        found.append(name)
    return found[:limit]


def build_report(name):
    """生成某个品种的多周期技术面报告。返回 (文本 或 None, 已用周期列表)。"""
    parts = []
    used = []
    for p in PERIODS:  # 已按权重从高到低
        try:
            df = get_kline(name, p)
        except Exception:
            df = None
        if df is None or len(df) < 5:
            continue
        text = summarize(df, PERIOD_NAME[p])
        if text:
            parts.append(text)
            used.append(p)
    if not parts:
        return None, []

    weights = " > ".join(PERIOD_NAME[p] for p in used)
    header = "【%s · 多周期技术面】周期权重：%s（越靠前权重越高，判断大方向优先看靠前的周期）" % (name, weights)
    return header + "\n" + "\n".join(parts), used


def build_reports(names):
    """为多个品种生成报告，拼接成一段文本。"""
    blocks = []
    for n in names:
        txt, _ = build_report(n)
        if txt:
            blocks.append(txt)
    return "\n\n".join(blocks)


# ---------------- 缓存预热 ----------------

_warm_lock = threading.Lock()
_warming = set()


def warm(name):
    """后台预热某品种的全部周期K线缓存（用户切换品种时调用，避免提问时等待）。"""
    if not name or name not in SYMBOL_MAP:
        return
    with _warm_lock:
        if name in _warming:
            return
        _warming.add(name)

    def _run():
        try:
            for p in PERIODS:
                try:
                    get_kline(name, p)
                except Exception:
                    pass
        finally:
            with _warm_lock:
                _warming.discard(name)

    threading.Thread(target=_run, daemon=True).start()
