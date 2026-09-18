# -*- coding: utf-8 -*-
"""
阶段 7 自测：MCP 客户端 + 金十工具接入 + 额度保护

    .venv\\Scripts\\python.exe tools\\test_stage7.py

结果写入 tools/_stage7_result.txt（UTF-8），避免控制台码页把中文搞乱。

安全说明：
- A~D、F、G 段**完全离线**，不需要任何 Key，任何时候都能跑。
- E 段（真连金十）需要开发期临时 token，来源为环境变量 `JIN10_DEV_TOKEN`
  或本地未跟踪文件 `tools/_jin10_token.txt`；两者都没有就自动跳过（记为「跳过」而非「失败」）。
- token 只在内存里用（monkeypatch load_config），**不会**写进 config.json，也**不得写进本文件**。
- 交付版本里金十 Key 一律由用户自己在 ⚙ 面板填写（R7-A）。
"""
import json
import os
import re
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OUT = []
PASS, FAIL = [], []
# 需要外部凭据才能跑的检查（没凭据时记为「跳过」而不是「失败」）
SKIPPED = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    log("  %s %s%s" % ("✅" if cond else "❌", name, ("  —— " + extra) if extra else ""))


def run(fn, label):
    log("")
    log("=" * 62)
    log(label)
    log("=" * 62)
    try:
        fn()
    except Exception:
        FAIL.append(label + " 抛异常")
        log("❌ 本节异常：")
        log(traceback.format_exc())


# ==================== A. 模块导入 ====================

def t_imports():
    import src.mcp as mcp
    import src.jin10 as jin10
    import src.tools as tools
    import src.chat as chat
    import src.config as config
    import src.api as api

    check("src/mcp.py 可导入", hasattr(mcp, "McpClient"))
    check("src/jin10.py 可导入", hasattr(jin10, "JIN10_CODES"))
    check("src/tools.py 可导入", hasattr(tools, "JIN10_TOOL_SCHEMAS"))
    check("src/chat.py 可导入", hasattr(chat, "build_system_prompt"))
    check("src/api.py 有金十接口",
          hasattr(api.Api, "get_jin10_status") and hasattr(api.Api, "jin10_selftest"))
    check("config 默认关闭金十（R7-A）",
          config.DEFAULTS.get("jin10_enabled") is False
          and config.DEFAULTS.get("jin10_api_key") == "",
          "jin10_enabled=%r" % config.DEFAULTS.get("jin10_enabled"))
    # R7-A：交付程序（src/ 与 main.py）里不得出现任何形式的 API Key
    key_re = re.compile(r"sk-[A-Za-z0-9_\-]{16,}")
    leaks = []
    for base, _dirs, files in os.walk(os.path.join(ROOT, "src")):
        for fn in files:
            if fn.endswith(".py"):
                p = os.path.join(base, fn)
                if key_re.search(open(p, encoding="utf-8").read()):
                    leaks.append(os.path.relpath(p, ROOT))
    main_py = os.path.join(ROOT, "main.py")
    if key_re.search(open(main_py, encoding="utf-8").read()):
        leaks.append("main.py")
    check("交付程序里没有硬编码金十 Key（src/ 与 main.py）", not leaks, str(leaks))

    # 开发期脚本同样不该明文存 token（改从环境变量 / 本地未跟踪文件读）。
    # 注意匹配「真 token」而不是 TOKEN="sk-..." 这种文档示例，否则是假阳性。
    dev_leaks = []
    tools_dir = os.path.join(ROOT, "tools")
    for fn in sorted(os.listdir(tools_dir)):
        if fn.endswith(".py"):
            if key_re.search(open(os.path.join(tools_dir, fn), encoding="utf-8").read()):
                dev_leaks.append(fn)
    check("tools/ 下的脚本不含明文 token", not dev_leaks, str(dev_leaks))


# ==================== B. 工具门控 ====================

def t_gating():
    import src.tools as tools

    off = {"enable_tools": True, "jin10_enabled": False, "jin10_api_key": ""}
    names_off = [t["function"]["name"] for t in tools.active_tool_schemas(off)]
    # 阶段 9 新增 render_analysis_chart，免费源工具由 3 个变 4 个
    check("未启用金十 → 只暴露 4 个免费源工具", len(names_off) == 4, str(names_off))
    check("未启用金十 → 不含 jin10_*",
          not any(n.startswith("jin10_") for n in names_off))

    on = {"enable_tools": True, "jin10_enabled": True, "jin10_api_key": "dummy-key-for-gating"}
    names_on = [t["function"]["name"] for t in tools.active_tool_schemas(on)]
    check("启用金十 → 暴露 4 + 8 = 12 个工具", len(names_on) == 12, str(len(names_on)))
    check("启用金十 → 8 个 jin10_* 全部到位",
          sorted(n for n in names_on if n.startswith("jin10_")) == sorted(tools.JIN10_TOOL_NAMES),
          str(tools.JIN10_TOOL_NAMES))

    check("金十工具与免费源工具不重名",
          not (set(tools.JIN10_TOOL_NAMES) & {t["function"]["name"] for t in tools.TOOL_SCHEMAS}))

    # 每个工具都要有 executor，否则 AI 调了会报「不存在该工具」
    missing = [n for n in names_on if n not in tools._EXECUTORS]
    check("12 个工具都有 executor", not missing, str(missing))

    # summarize_call 对每个工具都能出中文标签
    bad = []
    for n in names_on:
        try:
            lbl = tools.summarize_call(n, {"code": "XAUUSD", "keyword": "黄金", "id": "1"})
            if "调用工具" in lbl or not lbl:
                bad.append(n)
        except Exception:
            bad.append(n)
    check("summarize_call 覆盖全部工具", not bad, str(bad))


# ==================== C. 品种代码解析 ====================

def t_codes():
    import src.jin10 as jin10

    cases = [
        ("XAUUSD", "XAUUSD"),
        ("现货黄金", "XAUUSD"),
        ("现货白银", "XAGUSD"),
        ("铜", "COPPER"),
        ("WTI原油", "USOIL"),
        ("标普500", "SPX"),
        ("上证指数", "000001"),
        ("沪深300", "000300"),
        ("恒生指数", "HSI"),
    ]
    for raw, want in cases:
        got, name = jin10.resolve_code(raw)
        check("resolve_code(%s) -> %s" % (raw, want), got == want, "实际 %r / %s" % (got, name))

    # P0 回归：纳斯达克100 曾被错映射成 SPX(标普500)，会静默把标普数据当成纳指给 AI
    got, msg = jin10.resolve_code("纳斯达克100")
    check("纳斯达克100 不串到标普500（P0 回归）",
          got is None and "不支持" in msg, "实际 %r / %s" % (got, msg[:50]))

    # 结构性护栏：映射表与「不支持」表必须互斥（resolve_code 先查映射表）
    overlap = sorted(set(jin10.SYMBOL_TO_CODE) & set(jin10.NOT_SUPPORTED))
    check("映射表与 NOT_SUPPORTED 不重叠", not overlap, str(overlap))

    # 每个映射目标都必须是实测得到的金十代码，防止手写映射时拍脑袋
    bad = [k for k, v in jin10.SYMBOL_TO_CODE.items() if v not in jin10.JIN10_CODES]
    check("映射目标都在 97 个实测代码内", not bad, str(bad))

    got, msg = jin10.resolve_code("螺纹钢")
    check("金十不支持的品种给出可读提示", got is None and "不支持" in msg, msg[:60])

    got, msg = jin10.resolve_code("完全不存在的品种")
    check("未知品种给可读提示", got is None and "不支持" in msg)

    check("codes 表与实测一致（97 个）", len(jin10.JIN10_CODES) == 97, str(len(jin10.JIN10_CODES)))
    check("浙商积存金在表内（阶段 8 要用）", jin10.JIN10_CODES.get("CZBJCJ") == "浙商积存金")


# ==================== D. 额度保护（R7-C）====================

def t_quota():
    import src.jin10 as jin10

    tmp = os.path.join(tempfile.gettempdir(), "_stage7_quota.json")
    if os.path.exists(tmp):
        os.remove(tmp)
    old = jin10.QUOTA_PATH
    jin10.QUOTA_PATH = tmp
    try:
        check("初始用量为 0", jin10.usage()["total"] == 0)
        check("初始剩余为上限", jin10.remaining("get_quote") == jin10.DAILY_LIMIT_PER_TOOL)

        for _ in range(3):
            jin10._take_quota("get_quote")
        check("计数累加正确", jin10.usage()["tools"].get("get_quote") == 3,
              str(jin10.usage()["tools"]))
        check("按工具分别计数（不串台）", jin10.remaining("list_flash") == jin10.DAILY_LIMIT_PER_TOOL)

        # 逼近上限：提醒线在 80%
        jin10._take_quota("get_quote")
        while jin10.remaining("get_quote") > int(jin10.DAILY_LIMIT_PER_TOOL * 0.2) + 1:
            jin10._take_quota("get_quote")
        left = jin10._take_quota("get_quote")
        check("接近上限时返回剩余次数（触发提醒）", left is not None, "left=%r" % (left,))

        # 打满
        while jin10.remaining("get_quote") > 0:
            jin10._take_quota("get_quote")
        check("打满后 remaining 为 0", jin10.remaining("get_quote") == 0)

        raised = False
        try:
            jin10._take_quota("get_quote")
        except jin10.QuotaExceeded as e:
            raised = True
            check("超额抛 QuotaExceeded 且文案可读",
                  "额度已用尽" in str(e) and "1500" in str(e), str(e)[:70])
        check("超额确实被拦住", raised)

        # 超额时工具层返回可读文本而不是崩
        orig_lc = jin10.load_config
        jin10.load_config = lambda: {"jin10_enabled": True, "jin10_api_key": "x"}
        try:
            out = jin10.quote("XAUUSD")
            check("额度耗尽时 quote() 返回可读提示", isinstance(out, str) and "额度已用尽" in out,
                  out[:70])
        finally:
            jin10.load_config = orig_lc

        # 跨天重置
        data = json.load(open(tmp, encoding="utf-8"))
        data["date"] = "2000-01-01"
        json.dump(data, open(tmp, "w", encoding="utf-8"))
        check("跨天后计数归零", jin10.usage()["total"] == 0)
    finally:
        jin10.QUOTA_PATH = old
        if os.path.exists(tmp):
            os.remove(tmp)


# ==================== E. 真连 MCP（开发期 token）====================

def _dev_token():
    """
    取开发期临时 token（用完即弃，不落盘、不进仓库）。

    优先级：环境变量 JIN10_DEV_TOKEN → 本地未跟踪文件 tools/_jin10_token.txt
    （`_*.txt` 已被 .gitignore 覆盖）。两者都没有就跳过真连测试。

    注意：**绝不把 token 写进本文件**——本文件是要提交的。
    """
    t = (os.environ.get("JIN10_DEV_TOKEN") or "").strip()
    if t:
        return t
    p = os.path.join(ROOT, "tools", "_jin10_token.txt")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                t = f.read().strip()
            return t or None
        except Exception:
            return None
    return None


def t_live():
    import src.mcp as mcp
    import src.jin10 as jin10

    token = _dev_token()
    if not token:
        # 没有 token 就跳过：离线也能跑完整套自测，真连是可选的最后一步
        SKIPPED.append("E. 真实 MCP 联调（未提供开发期 token）")
        log("  ⏭ 未提供开发期 token，跳过真连测试。")
        log("     要跑真连：设置环境变量 JIN10_DEV_TOKEN，"
            "或把 token 写进 tools/_jin10_token.txt（该文件不入库）")
        return

    # 握手
    c = mcp.McpClient(token)
    c.initialize()
    check("initialize 成功", bool(c.server_info), str(c.server_info.get("name")))
    check("拿到协议版本", bool(c.protocol_version), str(c.protocol_version))
    check("协议版本与实测一致", c.protocol_version == "2025-11-25", str(c.protocol_version))

    tools = c.list_tools()
    check("tools/list 返回 8 个工具", len(tools) == 8, str([t.get("name") for t in tools]))

    codes = c.read_resource_json("quote://codes")
    if isinstance(codes, dict):
        codes = codes.get("data") or []
    check("quote://codes 返回 97 个品种", len(codes) == 97, str(len(codes)))
    check("codes 与内置表一致",
          {x["code"] for x in codes} == set(jin10.JIN10_CODES),
          "差集 %s" % list({x["code"] for x in codes} ^ set(jin10.JIN10_CODES))[:5])

    # 中文不乱码（SSE 强制 utf-8 的验证）
    d = c.call_tool_data("get_quote", {"code": "XAUUSD"})
    check("get_quote 返回中文名且无乱码",
          d.get("name") == "现货黄金", str(d.get("name")))
    check("get_quote 有价格", bool(d.get("close")), str(d.get("close")))

    # 完走工具层（monkeypatch 配置，避免把 token 写进 config.json）
    jin10.reset_client()
    orig_lc = jin10.load_config
    jin10.load_config = lambda: {
        "jin10_enabled": True,
        "jin10_api_key": token,
        "jin10_base_url": mcp.DEFAULT_BASE_URL,
    }
    tmp_q = os.path.join(tempfile.gettempdir(), "_stage7_live_quota.json")
    if os.path.exists(tmp_q):
        os.remove(tmp_q)
    old_q = jin10.QUOTA_PATH
    jin10.QUOTA_PATH = tmp_q
    try:
        out = jin10.quote("现货黄金")
        check("工具层 quote 输出含来源标注（R7-B）",
              "【来源：金十数据】" in out and "现货黄金" in out, out[:80])

        out = jin10.calendar()
        check("list_calendar 可用（R7-D 财经日历）",
              "金十财经日历" in out and "【来源：金十数据】" in out, out.split("\n")[0][:80])

        out = jin10.flash()
        check("list_flash 可用", "金十快讯" in out, out.split("\n")[0][:80])

        out = jin10.search_flash("黄金")
        check("search_flash 可用", "快讯搜索" in out, out.split("\n")[0][:60])

        out = jin10.news()
        check("list_news 可用", "金十资讯" in out, out.split("\n")[0][:60])

        out = jin10.search_news("黄金")
        check("search_news 可用", "资讯搜索" in out, out.split("\n")[0][:60])

        out = jin10.kline("XAUUSD", count=3)
        check("get_kline 可用", "分钟级K线" in out, out.split("\n")[0][:80])

        # 额度确实记上了
        u = jin10.usage()
        check("额度计数已记录", u["total"] >= 7, str(u["tools"]))

        # get_news 详情（借第一篇的 id）
        import re as _re
        m = _re.search(r"id=(\d+)", jin10.news())
        if m:
            out = jin10.news_detail(m.group(1))
            check("get_news 详情可用", "【来源：金十数据】" in out, out.split("\n")[0][:60])
        else:
            check("get_news 详情可用", False, "没取到 id")
    finally:
        jin10.QUOTA_PATH = old_q
        jin10.load_config = orig_lc
        jin10.reset_client()
        if os.path.exists(tmp_q):
            os.remove(tmp_q)
        c.close()


# ==================== F. 优雅禁用 / 自检 ====================

def t_graceful():
    import src.jin10 as jin10

    # 未配置 Key：所有工具都返回可读说明，不抛异常
    orig_lc = jin10.load_config
    jin10.load_config = lambda: {"jin10_enabled": False, "jin10_api_key": ""}
    try:
        for fn, args in [
            (jin10.quote, ("XAUUSD",)),
            (jin10.flash, ()),
            (jin10.calendar, ()),
            (jin10.news, ()),
            (jin10.news_detail, ("1",)),
            (jin10.kline, ("XAUUSD",)),
        ]:
            try:
                r = fn(*args)
                ok = isinstance(r, str) and ("未启用" in r or "还没有填" in r)
                check("未启用时 %s 优雅禁用" % fn.__name__, ok, str(r)[:60])
            except Exception as e:
                check("未启用时 %s 优雅禁用" % fn.__name__, False, repr(e))

        st = jin10.status()
        check("status 报告未启用", st["available"] is False and st["reason"], st["reason"][:50])

        r = jin10.selftest()
        check("未配置时自检 skipped", r["skipped"] is True and "跳过" in r["line"], r["line"][:60])
    finally:
        jin10.load_config = orig_lc

    # 错 Key：握手失败但不崩（用短假 Key，避免被 A 段的「明文 token」扫描误判）
    jin10.load_config = lambda: {"jin10_enabled": True, "jin10_api_key": "sk-bad-key"}
    try:
        r = jin10.selftest()
        check("错 Key 时自检返回失败而非抛异常", r["ok"] is False and bool(r["line"]),
              r["line"][:70])
        out = jin10.quote("XAUUSD")
        check("错 Key 时 quote 返回可读错误", isinstance(out, str) and len(out) > 0, out[:70])
    finally:
        jin10.load_config = orig_lc
        jin10.reset_client()


# ==================== G. 系统提示词 ====================

def t_prompt():
    import src.chat as chat
    import src.jin10 as jin10

    base = chat.build_system_prompt({"enable_tools": True, "active_skills": None})
    check("未启用金十 → 提示词不含金十工具说明", "jin10_calendar" not in base)

    orig_lc = jin10.load_config
    jin10.load_config = lambda: {"jin10_enabled": True, "jin10_api_key": "k",
                                 "active_skills": None, "enable_tools": True}
    try:
        # build_system_prompt 内部用 is_enabled(cfg)，直接传 cfg 即可
        on = chat.build_system_prompt({"enable_tools": True, "active_skills": None,
                                       "jin10_enabled": True, "jin10_api_key": "k"})
        check("启用金十 → 提示词含 jin10_calendar", "jin10_calendar" in on)
        check("启用金十 → 提示词要求来源标注", "来源：金十数据" in on)
        check("启用金十 → 提示词要求事件前查日历", "非农" in on or "重大事件" in on)
    finally:
        jin10.load_config = orig_lc


# ==================== 主流程 ====================

run(t_imports, "A. 模块导入与 R7-A（Key 不硬编码）")
run(t_gating, "B. 工具门控（优雅启用/禁用）")
run(t_codes, "C. 品种代码解析（阶段 8 铺垫）")
run(t_quota, "D. 额度保护 R7-C")
run(t_graceful, "F. 优雅禁用与错误处理")
run(t_prompt, "G. 系统提示词注入")
run(t_live, "E. 真实 MCP 联调（开发期 token）")

log("")
log("=" * 62)
log("汇总：通过 %d 项，失败 %d 项，跳过 %d 项" % (len(PASS), len(FAIL), len(SKIPPED)))
if SKIPPED:
    log("跳过项（缺外部凭据，不算失败）：")
    for s in SKIPPED:
        log("  - " + s)
if FAIL:
    log("失败项：")
    for f in FAIL:
        log("  - " + f)
log("=" * 62)

out_path = os.path.join(ROOT, "tools", "_stage7_result.txt")
with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))

print("done: pass=%d fail=%d skip=%d -> %s" % (len(PASS), len(FAIL), len(SKIPPED), out_path))
sys.exit(1 if FAIL else 0)
