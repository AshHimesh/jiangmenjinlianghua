# -*- coding: utf-8 -*-
"""
江门金量化 · 金十数据业务层

职责
----
1. 从配置里取用户自己填的金十 API Key（R7-A：绝不硬编码）。
2. 用 src/mcp.py 的 MCP 客户端调用金十的 8 个工具，把结果整理成 AI 能直接读的文本。
3. 额度保护（R7-C）：每个工具每天 1500 次，本地计数，接近上限给提示，超限给可读说明。
4. 为界面提供状态信息与连接自检。

★ 重要约束（R7-C）
------------------
金十**只能**出现在 AI 工具调用（按需触发）路径里。
**绝不允许**把它接进行情刷新循环 —— 本模块不提供任何"定时调用"接口，
调用方（src/tools.py）也只会在 AI 主动调用工具时触发。

来源标注（R7-B）
----------------
所有返回文本都带 `【来源：金十数据】`，方便 AI 在回答里如实注明数据出处。

错误处理约定
------------
所有对外函数**永不抛异常**，统一返回「给 AI 读的文本」。
额度用尽、Key 没填、网络失败，都返回可读的中文说明而不是让程序崩。
"""

import json
import os
import threading
from datetime import datetime, timedelta, timezone

from .config import load_config
from .mcp import DEFAULT_BASE_URL, McpClient, McpError, probe
from .paths import data_path

# ---------------- 额度（R7-C） ----------------

# 金十：每个用户每个工具每天 1500 次
DAILY_LIMIT_PER_TOOL = 1500
# 用到这个比例就开始提醒用户
WARN_RATIO = 0.8
# 提醒线：剩余次数降到这个值（含）就开始提醒。
# 用整数算，别写 DAILY_LIMIT * (1 - WARN_RATIO) —— 浮点会得到 299.99999999999994，
# 导致「剩 300 次」判定失败、提醒永不触发。
WARN_LEFT_LINE = DAILY_LIMIT_PER_TOOL - int(DAILY_LIMIT_PER_TOOL * WARN_RATIO)

QUOTA_PATH = data_path("jin10_quota.json")

_quota_lock = threading.Lock()


# 金十的额度按「北京时间自然日」重置。这里用固定 UTC+8 偏移显式换算，
# 不依赖 zoneinfo / tzdata（Windows 上可能缺），也不受本机时区设置影响。
_BEIJING_TZ = timezone(timedelta(hours=8))


def _today():
    """北京时间的日期字符串（纯函数）。"""
    return datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d")


def _load_quota():
    """读取额度计数；文件损坏或跨天则重置。"""
    today = _today()
    empty = {"date": today, "tools": {}}
    if not os.path.exists(QUOTA_PATH):
        return empty
    try:
        with open(QUOTA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("date") != today:
            return empty
        tools = data.get("tools")
        if not isinstance(tools, dict):
            return empty
        clean = {}
        for k, v in tools.items():
            if isinstance(v, (int, float)):
                clean[str(k)] = int(v)
        return {"date": today, "tools": clean}
    except Exception:
        return empty


def _save_quota(data):
    try:
        with open(QUOTA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # 计数写不进去不该影响功能


def usage():
    """当前用量快照，供界面展示。"""
    with _quota_lock:
        data = _load_quota()
    tools = data["tools"]
    return {
        "date": data["date"],
        "limit": DAILY_LIMIT_PER_TOOL,
        "tools": tools,
        "total": sum(tools.values()),
    }


def remaining(tool):
    with _quota_lock:
        data = _load_quota()
    return max(0, DAILY_LIMIT_PER_TOOL - data["tools"].get(tool, 0))


class QuotaExceeded(Exception):
    """额度用尽。"""


def _take_quota(tool):
    """
    占用一次额度。返回剩余次数（int）或 None（还没到提醒线）。
    额度用尽时抛 QuotaExceeded。
    """
    with _quota_lock:
        data = _load_quota()
        used = data["tools"].get(tool, 0)
        if used >= DAILY_LIMIT_PER_TOOL:
            raise QuotaExceeded(
                "金十「%s」今日额度已用尽（%d/%d 次）。额度每天 0 点重置，"
                "也可以先在 ⚙ 设置里临时关闭金十。" % (tool, used, DAILY_LIMIT_PER_TOOL)
            )
        used += 1
        data["tools"][tool] = used
        _save_quota(data)

    left = DAILY_LIMIT_PER_TOOL - used
    return left if left <= WARN_LEFT_LINE else None


def _rollback_quota(tool):
    """
    归还一次额度（请求失败时调用）。

    额度按「真正成功的调用」计费：网络不通、Key 失效这类失败不该占用用户额度。
    归还不会把计数压到 0 以下。
    """
    with _quota_lock:
        data = _load_quota()
        used = data["tools"].get(tool, 0)
        if used <= 0:
            return
        data["tools"][tool] = used - 1
        _save_quota(data)


# ---------------- 品种代码 ----------------

# 金十支持的完整报价品种表（2026-09-18 从 quote://codes 资源实测取得，97 个）
JIN10_CODES = {
    "TA25": "以色列特拉维夫25指数",
    "USOIL": "WTI原油",
    "COPPER": "现货铜",
    "IAUD": "工行账户澳大利亚元",
    "ICNYXAU": "工行人民币账户黄金",
    "UKOILX": "布伦特原油(暗油参考价)",
    "899050": "北证50",
    "GBPUSD": "英镑/美元",
    "IUSDJPY": "工行账户美元/日元",
    "IUSDSEK": "工行账户美元/瑞典克朗",
    "ICBCJCJ": "工行积存金",
    "ICBCRYJCJ": "工行如意积存金",
    "ZHJCJ": "招行积存金",
    "AEX": "荷兰阿姆斯特丹证交所指数",
    "XU100": "土耳其National-100指数",
    "XAUUSD": "现货黄金",
    "EURUSD": "欧元/美元",
    "USDCNH": "美元/人民币",
    "USDHKD": "美元/港元",
    "ICNYXAG": "工行人民币账户白银",
    "ICNYXPT": "工行人民币账户铂金",
    "FCHI": "法国CAC40指数",
    "TASI": "沙特阿拉伯Tadawu全股指数",
    "XPDUSD": "现货钯金",
    "ISEK": "工行账户瑞典克朗",
    "ACNYXAU": "农行人民币账户黄金",
    "AUSDXAU": "农行美元账户黄金",
    "XAGXUSD": "现货白银(暗银参考价)",
    "UKOIL": "布伦特原油",
    "NZDUSD": "纽元/美元",
    "IUSDXAG": "工行美元账户白银",
    "ICNYBRENT": "工行人民币账户国际原油（连续产品）",
    "XPTXUSD": "现货铂金(暗铂参考价)",
    "MCX": "俄罗斯MICEX综合指数",
    "000001": "上证指数",
    "USDCAD": "美元/加元",
    "INOK": "工行账户挪威克朗",
    "IEURUSD": "工行账户欧元/美元",
    "PAXGUSD": "现货黄金(暗金参考价)",
    "CMBCJCJ": "民生积存金",
    "DJI": "道琼斯工业指数",
    "INZD": "工行账户新西兰元",
    "IUSDCHF": "工行账户美元/瑞士法郎",
    "IUSDNOK": "工行账户美元/挪威克朗",
    "399006": "创业板指",
    "INZDUSD": "工行账户新西兰元/美元",
    "IUSDXAU": "工行美元账户黄金",
    "IUSDWTI": "工行美元账户北美原油（连续产品）",
    "IUSDGAS": "工行美元账户天然气",
    "ACNYXAG": "农行人民币账户白银",
    "FTSE": "英国富时100指数",
    "AXJO": "澳大利亚S&P/ASX200指数",
    "JKSE": "印尼雅加达综合指数",
    "XPTUSD": "现货铂金",
    "IEUR": "工行账户欧元",
    "IGBPUSD": "工行账户英镑/美元",
    "AUSDXAG": "农行美元账户白银",
    "CZBJCJ": "浙商积存金",
    "SPX": "标普500指数",
    "N225": "日经225指数",
    "IUSDSGD": "工行账户美元/新加坡元",
    "IUSDBRENT": "工行美元账户国际原油（连续产品）",
    "KS11": "韩国KOSPI指数",
    "XAGUSD": "现货白银",
    "ICNYXPD": "工行人民币账户钯金",
    "IBEX": "西班牙IBEX35指数",
    "USDJPY": "美元/日元",
    "ISGD": "工行账户新加坡元",
    "IAUDUSD": "工行账户澳大利亚元/美元",
    "GDAXI": "德国DAX30指数",
    "NSEI": "印度S&P CNX NIFTY指数",
    "NGAS": "天然气",
    "AUDUSD": "澳元/美元",
    "ICAD": "工行账户加拿大元",
    "IJPY": "工行账户日元",
    "IUSDXPT": "工行美元账户铂金",
    "IUSDXPD": "工行美元账户钯金",
    "ICNYWTI": "工行人民币账户北美原油（连续产品）",
    "USOILX": "WTI原油(暗油参考价)",
    "IGBP": "工行账户英镑",
    "ICHF": "工行账户瑞士法郎",
    "IUSDHKD": "工行账户美元/港币",
    "XPDXUSD": "现货钯金(暗钯参考价)",
    "SSMI": "瑞士SWI20指数",
    "BVSP": "巴西Bovespa指数",
    "IRTS": "俄罗斯RTSI指数",
    "MXX": "墨西哥IPC指数",
    "USDCHF": "美元/瑞郎",
    "ICNYGAS": "工行人民币账户天然气",
    "COPPERXUSD": "现货铜(暗铜参考价)",
    "HSI": "香港恒生指数",
    "399001": "深证成指",
    "000300": "沪深300",
    "IUSDCAD": "工行账户美元/加拿大元",
    "FTMIB": "意大利富时MIB指数",
    "BSESN": "印度BSE Sensex指数",
    "GSPTSE": "加拿大多伦多标普/TSX综合指数",
}

# 金十中文名 -> 代码（反查用，例如 AI 直接说"现货黄金"）
_NAME_TO_CODE = {v: k for k, v in JIN10_CODES.items()}

# 本项目品种名 -> 金十代码（只有金十确实提供的才映射）
SYMBOL_TO_CODE = {
    # 现有 14 个品种里金十覆盖得上的
    "现货黄金": "XAUUSD",
    "现货白银": "XAGUSD",
    "铜": "COPPER",
    "WTI原油": "USOIL",
    "标普500": "SPX",
    "上证指数": "000001",
    # 阶段 8 已接入 / 后备的品种
    # 注：「上海金 Au99.99」金十没有；但金十有「浙商积存金 CZBJCJ」，
    #     这正好满足需求 5.2.1（浙商买卖价原本被认为无公开接口）。
    "浙商积存金": "CZBJCJ",
    "沪深300": "000300",
    "创业板指": "399006",
    "深证成指": "399001",
    "北证50": "899050",
    "恒生指数": "HSI",
    "布伦特原油": "UKOIL",
    "天然气": "NGAS",
    "美元兑离岸人民币": "USDCNH",
    "美元/人民币": "USDCNH",
    "美元/港元": "USDHKD",
}

# 金十**确无**的品种 —— 写在这里，避免 AI 反复试探浪费额度。
# 注意：这张表与上面的 SYMBOL_TO_CODE 必须互斥（resolve_code 先查映射表，
# 若同一品种两边都有，就会静默串成别的品种的数据）。
NOT_SUPPORTED = [
    "纳斯达克100", "美元指数", "科创50",
    "螺纹钢", "焦煤", "甲醇", "乙二醇", "纯碱", "铁矿石", "玻璃",
    "上海金", "沪金AU", "沪银AG", "黄金ETF",
]

# 启动时自检映射表与 NOT_SUPPORTED 的互斥性，防止以后再出现「同一品种两处都写」
_OVERLAP = sorted(set(SYMBOL_TO_CODE) & set(NOT_SUPPORTED))
assert not _OVERLAP, "SYMBOL_TO_CODE 与 NOT_SUPPORTED 冲突：%s" % _OVERLAP


def resolve_code(code):
    """
    允许 AI 传三种形式：
      - 金十代码      XAUUSD
      - 本项目品种名  现货黄金
      - 金十中文名    现货黄金（走反查）
    返回 (金十代码, 中文名)；无法识别时返回 (None, 给 AI 的错误说明)。
    """
    code = (code or "").strip()
    if not code:
        return None, "错误：code 不能为空。用法见工具说明中的代码表。"

    if code in JIN10_CODES:
        return code, JIN10_CODES[code]
    if code in SYMBOL_TO_CODE:
        c = SYMBOL_TO_CODE[code]
        return c, JIN10_CODES.get(c, code)
    if code in _NAME_TO_CODE:
        return _NAME_TO_CODE[code], code

    hint = ""
    if code in NOT_SUPPORTED:
        hint = "（金十不提供该品种，请改用现有免费源数据）"
    return None, (
        "错误：金十不支持品种「%s」%s。金十覆盖的常用代码：XAUUSD(现货黄金)、XAGUSD(现货白银)、"
        "COPPER(现货铜)、USOIL(WTI原油)、SPX(标普500)、UKOIL(布伦特原油)、000001(上证指数)、"
        "000300(沪深300)、399006(创业板指)、HSI(恒生指数)、USDCNH(美元/人民币)、CZBJCJ(浙商积存金)。"
        % (code, hint)
    )


# ---------------- 客户端与会话 ----------------

_client_lock = threading.Lock()
_client = None
_client_sig = None

SOURCE_TAG = "【来源：金十数据】"


def _signature(cfg):
    return ((cfg.get("jin10_api_key") or "").strip(),
            (cfg.get("jin10_base_url") or DEFAULT_BASE_URL).strip())


def is_enabled(cfg=None):
    """金十功能是否可用：开关打开 + 用户填了 Key。"""
    cfg = cfg or load_config()
    return bool(cfg.get("jin10_enabled")) and bool((cfg.get("jin10_api_key") or "").strip())


def disabled_reason(cfg=None):
    cfg = cfg or load_config()
    if not cfg.get("jin10_enabled"):
        return "金十数据未启用。请到 ⚙ 设置里打开「金十数据」开关，并填入你自己的金十 API Key。"
    if not (cfg.get("jin10_api_key") or "").strip():
        return "金十数据已打开，但还没填 API Key。请到 ⚙ 设置里填写你自己的金十 Key。"
    return ""


def _get_client(cfg=None):
    """按当前配置取（或重建）客户端。Key 变了会自动重建会话。"""
    global _client, _client_sig
    cfg = cfg or load_config()
    key, base = _signature(cfg)
    if not key:
        raise McpError(disabled_reason(cfg))

    with _client_lock:
        if _client is not None and _client_sig == (key, base):
            return _client
        if _client is not None:
            _client.close()
        _client = McpClient(key, base)
        _client_sig = (key, base)
        return _client


def reset_client():
    """配置变更后调用，丢掉旧会话。"""
    global _client, _client_sig
    with _client_lock:
        if _client is not None:
            _client.close()
        _client = None
        _client_sig = None


def _run(tool, arguments=None, cfg=None):
    """
    受额度保护的工具调用。

    :return: (data, err_text, warn_text) —— 三者互斥/互补，永不抛异常。
             data 为 None 表示失败，此时 err_text 是给用户看的原因。
    """
    cfg = cfg or load_config()
    if not is_enabled(cfg):
        return None, disabled_reason(cfg), None

    try:
        warn_left = _take_quota(tool)          # 超额抛 QuotaExceeded
    except QuotaExceeded as e:
        return None, str(e), None

    try:
        data = _get_client(cfg).call_tool_data(tool, arguments or {})
    except McpError as e:
        _rollback_quota(tool)                   # 没调成功，不占用户额度
        return None, "金十调用失败：%s" % e, None
    except Exception as e:                      # 兜底：绝不让工具层把主流程带崩
        _rollback_quota(tool)
        return None, "金十调用异常：%s: %s" % (type(e).__name__, e), None

    warn = None
    if warn_left is not None:
        warn = ("【额度提醒】金十「%s」今天只剩 %d 次调用额度（上限 %d 次/天），请节约使用。"
                % (tool, warn_left, DAILY_LIMIT_PER_TOOL))
    return data, None, warn


def _tail(warn):
    return ("\n\n" + warn) if warn else ""


# ---------------- 8 个工具（文本化） ----------------
# 每个函数返回「给 AI 读的文本」。

def _signed(value):
    if value in (None, ""):
        return "-"
    s = str(value)
    return s if s.startswith("-") else "+" + s


def quote(code):
    c, name = resolve_code(code)
    if c is None:
        return name
    d, err, warn = _run("get_quote", {"code": c})
    if err:
        return err
    if not isinstance(d, dict):
        return "金十没有返回 %s 的行情。" % c
    return ("%s(%s)：现价 %s，涨跌 %s%%（%s），最高 %s，最低 %s，成交量 %s，时间 %s  %s"
            % (d.get("name") or name, c, d.get("close", "-"),
               _signed(d.get("ups_percent")), _signed(d.get("ups_price")),
               d.get("high", "-"), d.get("low", "-"),
               d.get("volume", "-"), d.get("time", "-"), SOURCE_TAG)) + _tail(warn)


def kline(code, time_from=None, count=None):
    c, name = resolve_code(code)
    if c is None:
        return name
    args = {"code": c}
    if time_from:
        try:
            args["time"] = int(time_from)
        except (TypeError, ValueError):
            pass
    if count:
        try:
            args["count"] = max(1, min(int(count), 100))
        except (TypeError, ValueError):
            pass

    d, err, warn = _run("get_kline", args)
    if err:
        return err
    rows = (d or {}).get("klines") or []
    if not rows:
        return "金十没有返回 %s 的K线数据。" % c

    lines = ["%s(%s) 金十分钟级K线，共 %d 根（时间, 开, 高, 低, 收, 量）  %s"
             % (d.get("name") or name, c, len(rows), SOURCE_TAG)]
    for r in rows:
        try:
            ts = datetime.fromtimestamp(int(r.get("time", 0))).strftime("%m-%d %H:%M")
        except Exception:
            ts = str(r.get("time", ""))
        lines.append("%s,%s,%s,%s,%s,%s" % (ts, r.get("open"), r.get("high"),
                                            r.get("low"), r.get("close"), r.get("volume")))
    lines.append("说明：金十K线为分钟级、最多回溯 24 小时，用于补充短线细节。")
    return "\n".join(lines) + _tail(warn)


def _fmt_flash_items(items, limit):
    return ["- [%s] %s" % (it.get("time", ""), (it.get("content") or "").strip())
            for it in items[:limit]]


def flash(cursor=None):
    d, err, warn = _run("list_flash", {"cursor": cursor} if cursor else {})
    if err:
        return err
    items = (d or {}).get("items") or []
    if not items:
        return "金十暂无快讯。"
    lines = ["金十快讯（最新 %d 条）  %s" % (len(items), SOURCE_TAG)]
    lines += _fmt_flash_items(items, 12)
    if (d or {}).get("has_more"):
        lines.append("（还有更多，可带 cursor 继续翻页：%s）" % (d.get("next_cursor") or ""))
    return "\n".join(lines) + _tail(warn)


def search_flash(keyword):
    if not (keyword or "").strip():
        return "错误：keyword 不能为空。"
    d, err, warn = _run("search_flash", {"keyword": keyword.strip()})
    if err:
        return err
    items = (d or {}).get("items") or []
    if not items:
        return "金十没有搜到与「%s」相关的快讯。" % keyword
    lines = ["金十快讯搜索「%s」，共 %d 条  %s" % (keyword, len(items), SOURCE_TAG)]
    lines += _fmt_flash_items(items, 12)
    lines.append("（该接口最多返回 150 条且不支持翻页）")
    return "\n".join(lines) + _tail(warn)


def _fmt_news_items(items, limit):
    return ["- [%s] %s（id=%s）\n  %s\n  %s"
            % (it.get("time", ""), (it.get("title") or "").strip(), it.get("id", ""),
               (it.get("introduction") or "").strip(), it.get("url", ""))
            for it in items[:limit]]


def news(cursor=None):
    d, err, warn = _run("list_news", {"cursor": cursor} if cursor else {})
    if err:
        return err
    items = (d or {}).get("items") or []
    if not items:
        return "金十暂无资讯。"
    lines = ["金十资讯（最新 %d 条）  %s" % (len(items), SOURCE_TAG)]
    lines += _fmt_news_items(items, 8)
    if (d or {}).get("has_more"):
        lines.append("（还有更多，可带 cursor 继续翻页：%s）" % (d.get("next_cursor") or ""))
    return "\n".join(lines) + _tail(warn)


def search_news(keyword, cursor=None):
    if not (keyword or "").strip():
        return "错误：keyword 不能为空。"
    args = {"keyword": keyword.strip()}
    if cursor:
        args["cursor"] = cursor
    d, err, warn = _run("search_news", args)
    if err:
        return err
    items = (d or {}).get("items") or []
    if not items:
        return "金十没有搜到与「%s」相关的资讯。" % keyword
    lines = ["金十资讯搜索「%s」，共 %d 条  %s" % (keyword, len(items), SOURCE_TAG)]
    lines += _fmt_news_items(items, 8)
    if (d or {}).get("has_more"):
        lines.append("（还有更多，可带 cursor 继续翻页：%s）" % (d.get("next_cursor") or ""))
    return "\n".join(lines) + _tail(warn)


def news_detail(news_id):
    if not (news_id or "").strip():
        return "错误：id 不能为空。"
    d, err, warn = _run("get_news", {"id": str(news_id).strip()})
    if err:
        return err
    if not isinstance(d, dict):
        return "金十没有返回该文章。"

    parts = ["%s  %s" % ((d.get("title") or "").strip(), SOURCE_TAG)]
    if d.get("time"):
        parts.append("时间：%s" % d["time"])
    if d.get("introduction"):
        parts.append("摘要：%s" % d["introduction"].strip())
    body = d.get("content") or d.get("body") or ""
    if body:
        body = body.strip()
        parts.append("正文：\n" + (body[:4000] + "…" if len(body) > 4000 else body))
    if d.get("url"):
        parts.append("原文：%s" % d["url"])
    return "\n".join(parts) + _tail(warn)


def calendar():
    d, err, warn = _run("list_calendar", {})
    if err:
        return err
    rows = d if isinstance(d, list) else (d or {}).get("items") or []
    if not rows:
        return "金十本周暂无财经日历数据。"
    lines = ["金十财经日历（本周，共 %d 条）  %s" % (len(rows), SOURCE_TAG)]
    for r in rows:
        star = "★" * int(r.get("star") or 0)
        lines.append("- %s  %s %s  前值=%s 预期=%s 实际=%s %s"
                     % (r.get("pub_time", ""), star, (r.get("title") or "").strip(),
                        r.get("previous"), r.get("consensus"), r.get("actual"),
                        r.get("affect_txt") or ""))
    lines.append("说明：非农、CPI、FOMC 等重大事件前后请按 skill 要求控制仓位。")
    return "\n".join(lines) + _tail(warn)


# ---------------- 界面状态 / 自检 ----------------

def status():
    """给 ⚙ 设置面板用的金十状态。"""
    cfg = load_config()
    u = usage()
    return {
        "enabled": bool(cfg.get("jin10_enabled")),
        "has_key": bool((cfg.get("jin10_api_key") or "").strip()),
        "available": is_enabled(cfg),
        "reason": disabled_reason(cfg),
        "base_url": cfg.get("jin10_base_url") or DEFAULT_BASE_URL,
        "quota": {
            "date": u["date"],
            "limit": u["limit"],
            "total": u["total"],
            "tools": u["tools"],
        },
        "codes_count": len(JIN10_CODES),
        # 能被金十兜底的本项目品种名（界面用来打角标）
        "covered": sorted(SYMBOL_TO_CODE.keys()),
        # 金十确实没有的现有品种，界面上如实说明
        "not_supported": list(NOT_SUPPORTED),
    }


def selftest():
    """
    连接自检：用户点按钮、或 --selftest 时调用。

    绝不抛异常 —— 所有失败都变成 error 文本。
    """
    cfg = load_config()
    out = {
        "enabled": bool(cfg.get("jin10_enabled")),
        "has_key": bool((cfg.get("jin10_api_key") or "").strip()),
        "ok": False,
        "skipped": False,
        "line": "",
        "detail": "",
    }

    if not (cfg.get("jin10_api_key") or "").strip():
        out["skipped"] = True
        out["line"] = "未配置金十 API Key，已跳过（可在 ⚙ 设置里填入你自己的金十 Key）"
        return out

    info = probe((cfg.get("jin10_api_key") or "").strip(),
                 cfg.get("jin10_base_url") or DEFAULT_BASE_URL)
    out["probe"] = info
    if not info.get("ok"):
        out["line"] = "连接失败：%s" % (info.get("error") or "未知错误")
        return out

    out["ok"] = True
    tools = info.get("tools") or []
    out["detail"] = (
        "服务端：%s（%s v%s）｜协议版本：%s\n工具 %d 个：%s\n资源 %d 个｜报价品种 %d 个"
        % (info.get("title") or info.get("name"), info.get("name"), info.get("version"),
           info.get("protocol"), len(tools), "、".join(tools) or "(未返回)",
           len(info.get("resources") or []), info.get("codes_count") or 0)
    )

    # 真跑一次调用，确认工具层通
    if remaining("list_calendar") <= 0:
        out["line"] = "握手成功，但今日额度已用尽，未做实际调用"
        return out

    data, err, _warn = _run("list_calendar", {}, cfg)
    if err:
        out["ok"] = False
        out["line"] = "握手成功，但工具调用失败：%s" % err
    else:
        n = len(data) if isinstance(data, list) else len((data or {}).get("items") or [])
        out["line"] = "连接正常，本周财经日历返回 %d 条" % n

    u = usage()
    out["detail"] += "\n今日已用额度：%d / %d 次" % (u["total"], u["limit"])
    return out
