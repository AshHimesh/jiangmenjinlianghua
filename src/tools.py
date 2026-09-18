# -*- coding: utf-8 -*-
"""
江门金量化 · AI 工具（Function Calling）

让 AI 可以**按需**读取数据，而不是只能看预先注入的内容：

免费源（新浪 AKShare，主力）：
    - get_kline        读取任意品种/周期的原始K线
    - get_indicators   读取任意品种/周期的技术指标
    - list_symbols     查询品种清单与各自支持的周期

金十数据（阶段 7，MCP 协议；需用户在 ⚙ 设置里填自己的 Key）：
    - jin10_quote / jin10_kline          行情与分钟级K线
    - jin10_flash / jin10_search_flash   快讯列表 / 搜索
    - jin10_news / jin10_search_news / jin10_news_detail   资讯列表 / 搜索 / 详情
    - jin10_calendar                     本周财经日历

注意
----
1. 函数调用需要模型支持（DeepSeek-chat / GLM-4 / Qwen / GPT 等），
   推理模型（如 deepseek-reasoner）多数不支持，届时会自动降级为纯文本注入模式。
2. 金十工具统一加 `jin10_` 前缀，因为金十自己也有个叫 `get_kline` 的工具，
   与本项目的 `get_kline`（走新浪免费源、支持多周期）语义不同，必须区分开。
3. 金十工具有额度限制（每个工具每天 1500 次，R7-C），**只在 AI 主动调用时触发**，
   绝不参与行情刷新循环。额度相关逻辑全部在 src/jin10.py。
"""
import json

from . import jin10
from .indicators import summarize
from .kline import PERIODS, PERIOD_NAME, get_kline
# 可用周期矩阵的唯一事实源在 src/symbols.py
# （src/kline.py 的 get_kline 也用它做闸门，避免出现两处各写一份、互相漂移）
from .symbols import PERIODS_BY_SOURCE, SYMBOL_MAP

MAX_LIMIT = 120
DEFAULT_LIMIT = 30

SYMBOL_NAMES = list(SYMBOL_MAP.keys())


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
    {
        "type": "function",
        "function": {
            "name": "render_analysis_chart",
            "description": (
                "把你的分析结论画成一张K线标注图：浪型计数、支撑/压力位、入场位、止损位、"
                "分档止盈位都会标在图上。图片只嵌入导出的报告，不会出现在主界面。"
                "当你已经得出完整的交易计划（或用户要求生成报告/研报）时调用它。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "enum": SYMBOL_NAMES, "description": "品种名称"},
                    "period": {
                        "type": "string", "enum": PERIODS,
                        "description": "K线周期：选你这份交易计划所在的主周期",
                    },
                    "waves": {
                        "type": "array",
                        "description": "艾略特波浪计数（可选）。每项 {label, index, price}；"
                                       "index 为最近窗口内K线序号（0 = 最早一根），price 为该浪起点价位",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string", "description": "浪型标记，如 ①②③④⑤ 或 A/B/C"},
                                "index": {"type": "integer", "description": "该浪起点在窗口内的K线序号（0 基）"},
                                "price": {"type": "number", "description": "该浪起点价位"},
                            },
                            "required": ["label", "index", "price"],
                        },
                    },
                    "support": {"type": "array", "items": {"type": "number"},
                                "description": "支撑位列表（可选，可多个）"},
                    "resistance": {"type": "array", "items": {"type": "number"},
                                   "description": "压力位列表（可选，可多个）"},
                    "entry": {"type": "number", "description": "入场位（可选）"},
                    "stop_loss": {"type": "number", "description": "止损位 SL（可选）"},
                    "take_profit": {"type": "array", "items": {"type": "number"},
                                    "description": "分档止盈位 TP1/TP2/TP3（可选）"},
                    "note": {"type": "string", "description": "图上要写的一句话备注（可选）"},
                },
                "required": ["symbol", "period"],
            },
        },
    },
]


# ---------------- 金十数据工具（阶段 7，需用户配置 Key）----------------

# 写进描述里的常用代码表。用户/模型也可以直接传中文名，resolve_code 会自行识别。
_JIN10_CODE_HINT = (
    "常用代码：XAUUSD=现货黄金、XAGUSD=现货白银、COPPER=现货铜、USOIL=WTI原油、"
    "UKOIL=布伦特原油、SPX=标普500、NGAS=天然气、XPTUSD=现货铂金、XPDUSD=现货钯金、"
    "DJI=道琼斯、N225=日经225、HSI=恒生指数、000001=上证指数、399001=深证成指、"
    "000300=沪深300、399006=创业板指、899050=北证50、USDCNH=美元/人民币、"
    "EURUSD=欧元/美元、USDJPY=美元/日元、GBPUSD=英镑/美元、USDHKD=美元/港元、"
    "ICBCJCJ=工行积存金、CZBJCJ=浙商积存金、ZHJCJ=招行积存金、CMBCJCJ=民生积存金。"
    "也可以直接传中文名（如「现货黄金」）。"
)

JIN10_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "jin10_quote",
            "description": (
                "【金十数据】读取指定品种的实时行情报价（价格、涨跌幅、最高最低、成交量）。"
                "金十覆盖的品种比免费源更广，含各国指数、外汇、各银行积存金。"
                + _JIN10_CODE_HINT +
                "注意：金十数据有每日调用额度，仅在免费源取不到、或需要金十独有品种时才用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "品种代码或中文名，如 XAUUSD 或 现货黄金"},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "jin10_kline",
            "description": (
                "【金十数据】读取指定品种的**分钟级**K线，最多回溯 24 小时、最多 100 根。"
                "用于补充短线细节（逐根分钟K线、盘中跳空）。"
                "需要日线以上的多周期K线时，请用 get_kline（走免费源）。"
                + _JIN10_CODE_HINT
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "品种代码或中文名"},
                    "time": {"type": "integer", "description": "起始 Unix 时间戳（秒），可选，默认当前"},
                    "count": {"type": "integer", "description": "取多少根，1-100，默认 100"},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "jin10_flash",
            "description": (
                "【金十数据】获取最新快讯列表（金十 7x24 快讯）。"
                "用于了解当前市场突发消息、宏观事件、品种异动原因。"
                "翻页时把上一页返回的 next_cursor 传进 cursor。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cursor": {"type": "string", "description": "分页游标，首次不传"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "jin10_search_flash",
            "description": (
                "【金十数据】按关键词搜索历史快讯，最多返回 150 条、不支持翻页。"
                "适合查某品种/事件（如「黄金」「美联储」「非农」）的近期相关快讯。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词，如 黄金、美联储、非农"},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "jin10_news",
            "description": "【金十数据】获取最新深度资讯文章列表（标题 + 摘要 + 链接）。可用 cursor 翻页。",
            "parameters": {
                "type": "object",
                "properties": {
                    "cursor": {"type": "string", "description": "分页游标，首次不传"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "jin10_search_news",
            "description": "【金十数据】按关键词搜索深度资讯文章，支持 cursor 翻页。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词"},
                    "cursor": {"type": "string", "description": "分页游标，首次不传"},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "jin10_news_detail",
            "description": (
                "【金十数据】按文章 id 获取资讯正文详情。"
                "id 来自 jin10_news / jin10_search_news 的返回结果。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "文章 id，如 230459"},
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "jin10_calendar",
            "description": (
                "【金十数据】获取**本周（周一到周日）财经日历**：数据公布时间、前值、预期、实际、"
                "星级与利多利空。"
                "重要：用户的技能要求「非农、CPI、FOMC 等重大事件前平仓或减仓」，"
                "涉及交易计划、持仓建议、事件风险时**必须**先查日历。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

JIN10_TOOL_NAMES = [t["function"]["name"] for t in JIN10_TOOL_SCHEMAS]


def active_tool_schemas(cfg=None):
    """
    本次请求可用的工具清单。

    金十工具只在「开关打开 + 用户填了 Key」时才暴露给模型，
    未配置时 AI 根本看不到它们，也就不会误调用（验收要求：优雅禁用）。
    """
    schemas = list(TOOL_SCHEMAS)
    try:
        if jin10.is_enabled(cfg):
            schemas.extend(JIN10_TOOL_SCHEMAS)
    except Exception:
        pass
    return schemas


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


def _tool_render_analysis_chart(symbol, period, waves=None, support=None,
                                resistance=None, entry=None, stop_loss=None,
                                take_profit=None, note=None):
    """把 AI 的结构化分析结论画成K线标注图（图片只进报告，不进主界面）。"""
    err = _check(symbol, period)
    if err:
        return err

    from . import chart        # 延迟导入：没装 matplotlib 时其余功能照常可用
    res = chart.render(symbol, period, waves=waves, support=support,
                       resistance=resistance, entry=entry, stop_loss=stop_loss,
                       take_profit=take_profit, note=note)
    if not res.get("ok"):
        return "画图失败：%s" % res.get("error", "未知原因")

    parts = []
    parts.append("✅ 已生成 %s %s 的K线标注图（%d 根）" % (symbol, PERIOD_NAME[period], res["bars"]))
    parts.append("[[chart:%s]]" % res["path"])
    counts = []
    if waves:
        counts.append("浪型 %d 个" % len(waves))
    if support:
        counts.append("支撑 %d 个" % len(support))
    if resistance:
        counts.append("压力 %d 个" % len(resistance))
    if entry is not None:
        counts.append("入场位")
    if stop_loss is not None:
        counts.append("止损位")
    if take_profit:
        counts.append("止盈 %d 档" % len(take_profit))
    parts.append("已标注：" + ("、".join(counts) if counts else "无价位标注"))
    if res.get("warnings"):
        parts.append("注意：" + "；".join(res["warnings"]))
    parts.append("说明：图表不会出现在主界面，导出报告时会自动嵌入。")
    return "\n".join(parts)


# ---------------- 金十工具实现 ----------------
# 全部委托给 src/jin10.py；那里已经保证「额度/未配置/网络错误」都返回可读文本。

def _tool_jin10_quote(code):
    return jin10.quote(code)


def _tool_jin10_kline(code, time=None, count=None):
    return jin10.kline(code, time_from=time, count=count)


def _tool_jin10_flash(cursor=None):
    return jin10.flash(cursor)


def _tool_jin10_search_flash(keyword):
    return jin10.search_flash(keyword)


def _tool_jin10_news(cursor=None):
    return jin10.news(cursor)


def _tool_jin10_search_news(keyword, cursor=None):
    return jin10.search_news(keyword, cursor)


def _tool_jin10_news_detail(id):
    return jin10.news_detail(id)


def _tool_jin10_calendar():
    return jin10.calendar()


_EXECUTORS = {
    "get_kline": _tool_get_kline,
    "get_indicators": _tool_get_indicators,
    "list_symbols": lambda **_: _tool_list_symbols(),
    "render_analysis_chart": _tool_render_analysis_chart,
    # 金十（阶段 7）。即使未启用也注册：此时 jin10.* 会返回「未启用」的可读说明，
    # 比让 execute 报「不存在该工具」更友好。
    "jin10_quote": _tool_jin10_quote,
    "jin10_kline": _tool_jin10_kline,
    "jin10_flash": _tool_jin10_flash,
    "jin10_search_flash": _tool_jin10_search_flash,
    "jin10_news": _tool_jin10_news,
    "jin10_search_news": _tool_jin10_search_news,
    "jin10_news_detail": _tool_jin10_news_detail,
    "jin10_calendar": _tool_jin10_calendar,
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
    if name == "render_analysis_chart":
        return "绘制 %s 的%s标注图" % (
            args.get("symbol", "?"),
            PERIOD_NAME.get(args.get("period"), args.get("period", "?")))

    # 金十（阶段 7）—— 标签统一带「金十」，让用户在界面上能一眼看出数据出处（R7-B）
    code = args.get("code", "?")
    if name == "jin10_quote":
        return "金十 · 读取 %s 实时行情" % code
    if name == "jin10_kline":
        return "金十 · 读取 %s 分钟K线" % code
    if name == "jin10_flash":
        return "金十 · 读取最新快讯"
    if name == "jin10_search_flash":
        return "金十 · 搜索快讯「%s」" % args.get("keyword", "?")
    if name == "jin10_news":
        return "金十 · 读取资讯列表"
    if name == "jin10_search_news":
        return "金十 · 搜索资讯「%s」" % args.get("keyword", "?")
    if name == "jin10_news_detail":
        return "金十 · 读取文章详情"
    if name == "jin10_calendar":
        return "金十 · 读取本周财经日历"

    return "调用工具 %s" % name
