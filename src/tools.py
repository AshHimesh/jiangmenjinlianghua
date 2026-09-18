# -*- coding: utf-8 -*-
"""
江门金量化 · AI 工具（Function Calling）

让 AI 可以**按需**读取数据，而不是只能看预先注入的内容：
    - get_kline        读取任意品种/周期的原始K线
    - get_indicators   读取任意品种/周期的技术指标
    - list_symbols     查询品种清单与各自支持的周期

注意：函数调用需要模型支持（DeepSeek-chat / GLM-4 / Qwen / GPT 等），
推理模型（如 deepseek-reasoner）多数不支持，届时会自动降级为纯文本注入模式。
"""
import json

from .indicators import summarize
from .kline import PERIODS, PERIOD_NAME, get_kline
from .symbols import SYMBOL_MAP

MAX_LIMIT = 120
DEFAULT_LIMIT = 30

SYMBOL_NAMES = list(SYMBOL_MAP.keys())

# 各品种实际可用的周期（按数据源静态判断，避免逐个联网探测）
PERIODS_BY_SOURCE = {
    "sina_futures": ["W", "D", "12H", "4H", "1H", "15M", "5M"],
    "sina_index": ["W", "D", "12H", "4H", "1H", "15M", "5M"],
    "sina_foreign": ["W", "D", "4H", "1H", "15M", "5M"],
    "sina_global": ["W", "D"],
}


def available_periods(symbol):
    item = SYMBOL_MAP.get(symbol)
    if not item:
        return []
    return PERIODS_BY_SOURCE.get(item.get("source"), [])


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_kline",
            "description": (
                "读取指定品种、指定周期的原始K线数据（日期/开/高/低/收/成交量），"
                "按时间从早到晚排列。当你需要精确的历史价位、逐根K线形态、"
                "跳空缺口、或者要分析的周期不在已提供的数据中时使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "enum": SYMBOL_NAMES,
                        "description": "品种名称",
                    },
                    "period": {
                        "type": "string",
                        "enum": PERIODS,
                        "description": "K线周期：W=周线 D=日线 12H=12小时 4H=4小时 1H=1小时 15M=15分钟 5M=5分钟",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回最近多少根K线，默认 %d，最大 %d" % (DEFAULT_LIMIT, MAX_LIMIT),
                    },
                },
                "required": ["symbol", "period"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_indicators",
            "description": (
                "读取指定品种、指定周期的完整技术指标：均线与多空排列、MACD、RSI、KDJ、"
                "布林带、涨跌幅、量能、斐波那契回撤与扩展位、多组斐波那契汇聚区、"
                "背离信号、K线形态、近期结构高低点。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "enum": SYMBOL_NAMES, "description": "品种名称"},
                    "period": {"type": "string", "enum": PERIODS, "description": "K线周期"},
                },
                "required": ["symbol", "period"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_symbols",
            "description": "查询全部可分析品种，以及每个品种实际支持的K线周期。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def _check(symbol, period):
    """参数校验，返回错误文本或 None。"""
    if symbol not in SYMBOL_MAP:
        return "错误：未知品种「%s」。可用品种：%s" % (symbol, "、".join(SYMBOL_NAMES))
    if period not in PERIODS:
        return "错误：未知周期「%s」。可用周期：%s" % (period, "/".join(PERIODS))
    avail = available_periods(symbol)
    if period not in avail:
        return "%s 不支持%s周期。该品种可用周期：%s" % (
            symbol, PERIOD_NAME[period],
            " / ".join(PERIOD_NAME[p] for p in avail) or "无")
    return None


# ---------------- 各工具实现 ----------------

def _tool_get_kline(symbol, period, limit=DEFAULT_LIMIT):
    err = _check(symbol, period)
    if err:
        return err

    df = get_kline(symbol, period)
    if df is None or len(df) == 0:
        return "暂无数据：%s 的%s当前取不到数据，请稍后重试或改用其他周期。" % (symbol, PERIOD_NAME[period])

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(1, min(limit, MAX_LIMIT))
    sub = df.tail(limit)

    lines = ["%s %s 最近%d根（时间, 开, 高, 低, 收, 量）：" % (symbol, PERIOD_NAME[period], len(sub))]
    for _, r in sub.iterrows():
        ts = r["datetime"]
        fmt = "%Y-%m-%d" if period in ("W", "D") else "%m-%d %H:%M"
        lines.append("%s,%.6g,%.6g,%.6g,%.6g,%.6g" % (
            ts.strftime(fmt), r["open"], r["high"], r["low"], r["close"], r["volume"]))
    return "\n".join(lines)


def _tool_get_indicators(symbol, period):
    err = _check(symbol, period)
    if err:
        return err

    df = get_kline(symbol, period)
    if df is None or len(df) == 0:
        return "暂无数据：%s 的%s当前取不到数据，请稍后重试或改用其他周期。" % (symbol, PERIOD_NAME[period])
    text = summarize(df, "%s %s" % (symbol, PERIOD_NAME[period]))
    if not text:
        return "该周期历史数据太少（仅 %d 根），指标不可靠。" % len(df)
    return text


def _tool_list_symbols():
    lines = ["可分析品种及其支持的周期："]
    for name in SYMBOL_NAMES:
        ps = available_periods(name)
        lines.append("- %s：%s" % (name, " / ".join(PERIOD_NAME[p] for p in ps) or "无"))
    return "\n".join(lines)


_EXECUTORS = {
    "get_kline": _tool_get_kline,
    "get_indicators": _tool_get_indicators,
    "list_symbols": lambda **_: _tool_list_symbols(),
}


def execute(name, arguments):
    """
    执行一个工具调用。

    :param name: 工具名
    :param arguments: JSON 字符串或 dict
    :return: 结果文本（供模型阅读）
    """
    fn = _EXECUTORS.get(name)
    if fn is None:
        return "错误：不存在名为「%s」的工具。可用工具：%s" % (name, "、".join(_EXECUTORS))
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except ValueError:
            return "错误：工具参数不是合法 JSON：%s" % arguments[:200]
    elif isinstance(arguments, dict):
        args = arguments
    else:
        args = {}
    try:
        return fn(**args)
    except TypeError as e:
        return "错误：工具参数不正确（%s）" % e
    except Exception as e:
        return "工具执行失败：%r" % e


def summarize_call(name, arguments):
    """把一次工具调用转成给用户看的一句话（用于界面展示）。"""
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except ValueError:
            args = {}
    else:
        args = arguments or {}

    if name == "get_kline":
        return "读取 %s 的%sK线" % (args.get("symbol", "?"), PERIOD_NAME.get(args.get("period"), args.get("period", "?")))
    if name == "get_indicators":
        return "读取 %s 的%s指标" % (args.get("symbol", "?"), PERIOD_NAME.get(args.get("period"), args.get("period", "?")))
    if name == "list_symbols":
        return "查询可用品种与周期"
    return "调用工具 %s" % name
