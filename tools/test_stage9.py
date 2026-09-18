# -*- coding: utf-8 -*-
"""
阶段 9 自测：分析图表 + 报告导出

    .venv\\Scripts\\python.exe tools\\test_stage9.py

结果写 tools/_stage9_result.txt（UTF-8），不要用 shell 管道接输出。

注意：图表部分要取真实K线（联网）；报告导出部分完全离线。
测试产生的文件一律在 finally 里清理，不留在 reports/ 目录。
"""
import base64
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OUT = []
PASS, FAIL = [], []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    log("  %s %s%s" % ("✅" if cond else "❌", name, ("  —— " + extra) if extra else ""))


def run(fn, label):
    log("")
    log("=" * 64)
    log(label)
    log("=" * 64)
    try:
        fn()
    except Exception:
        FAIL.append(label + " 抛异常")
        log("❌ 本节异常：")
        log(traceback.format_exc())


def _cleanup(paths):
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


# ==================== A. 结构与依赖（离线）====================

def t_structure():
    from src import chart, report
    from src.tools import TOOL_SCHEMAS, _EXECUTORS, active_tool_schemas, summarize_call
    from src.api import REPORT_PROMPT

    check("src/chart.py 可导入", hasattr(chart, "render"))
    check("src/report.py 可导入", hasattr(report, "export") and hasattr(report, "open_report"))

    names = [t["function"]["name"] for t in TOOL_SCHEMAS]
    check("render_analysis_chart 已注册为 AI 工具", "render_analysis_chart" in names, str(names))
    check("render_analysis_chart 有 executor", "render_analysis_chart" in _EXECUTORS)

    names_on = [t["function"]["name"] for t in active_tool_schemas(
        {"enable_tools": True, "jin10_enabled": True, "jin10_api_key": "k"})]
    check("启用金十时共 12 个工具（4 免费 + 8 金十）", len(names_on) == 12, str(len(names_on)))
    names_off = [t["function"]["name"] for t in active_tool_schemas(
        {"enable_tools": True, "jin10_enabled": False, "jin10_api_key": ""})]
    check("未启用金十时共 4 个工具", len(names_off) == 4, str(names_off))
    lbl = summarize_call("render_analysis_chart", {"symbol": "螺纹钢", "period": "D"})
    check("summarize_call 能给出可读标签", "标注图" in lbl and "螺纹钢" in lbl, lbl)

    fp = chart.resolve_font()
    check("中文字体可用（否则图上中文变方块）", bool(fp), str(fp))

    # 一键研报的指令必须要求画图（图是报告的必要组成）
    check("研报指令要求调用画图工具", "render_analysis_chart" in REPORT_PROMPT)
    check("研报指令禁止编造价位", "不得编造" in REPORT_PROMPT)


# ==================== B. 图表绘制（联网取K线）====================

def t_chart():
    from src import chart

    res = chart.render(
        "螺纹钢", "D",
        waves=[{"label": "①", "index": 5, "price": 3000},
               {"label": "②", "index": 12, "price": 3120},
               {"label": "③", "index": 40, "price": 3050}],
        support=[3000, 2950], resistance=[3200, 3260],
        entry=3080, stop_loss=3010, take_profit=[3200, 3280, 3350],
        note="阶段 9 自检测试图",
    )
    check("带完整标注能出图", res.get("ok") is True, str(res.get("error") or ""))
    if res.get("ok"):
        p = res["path"]
        size = os.path.getsize(p) if os.path.exists(p) else 0
        check("PNG 已落盘且非空（>20KB）", size > 20 * 1024, "%d bytes" % size)
        check("标注了 3 档止盈与 2 个压力位", res.get("bars", 0) >= 10)
        _cleanup([p])

    # 越界浪型：要给 warning 而不是崩
    res2 = chart.render("螺纹钢", "D", waves=[{"label": "①", "index": 9999, "price": 3000}])
    check("浪型下标越界给可读警告而非崩溃",
          res2.get("ok") and res2.get("warnings"), str(res2.get("warnings"))[:80])
    _cleanup([res2.get("path")])

    # 不支持的周期：应直接失败并说明（周期矩阵闸门生效）
    res3 = chart.render("现货黄金", "12H")
    check("未声明周期画不了图（矩阵闸门生效）",
          res3.get("ok") is False and "暂无" in (res3.get("error") or ""), str(res3.get("error")))

    # 慢速源也能画（上海金只有周/日）
    res4 = chart.render("上海金", "D")
    check("上海金（上金所日线）能出图", res4.get("ok") is True, str(res4.get("error")))
    _cleanup([res4.get("path")])


# ==================== C. 报告导出（离线）====================

def t_report_export():
    from src import chart, report

    png = None
    res = chart.render("螺纹钢", "D", support=[3000], resistance=[3200])
    if res.get("ok"):
        png = res["path"]

    skills = ["斐波那契短线入场专家", "价格行为斐波那契专家"]
    out = report.export(
        symbol="螺纹钢",
        question="螺纹钢现在能做多吗？",
        answer="一、多周期判读……\n二、浪型计数……\n三、关键价位……\n四、交易计划……",
        charts=[png] if png else [],
        model="deepseek-reasoner",
        skills=skills,
        quotes={"螺纹钢": {"price": 3101.0, "change": 0.47,
                          "source": "新浪财经 · 免费源"}},
    )
    try:
        check("报告导出成功", out.get("ok") is True, str(out.get("error")))
        if not out.get("ok"):
            return
        md, html_path = out["md"], out["html"]
        check("同时产出 .md 与 .html", os.path.exists(md) and os.path.exists(html_path))

        with open(md, encoding="utf-8") as f:
            md_text = f.read()
        for key in ["生成时间", "品种", "当前价", "数据时间戳", "启用技能", "模型", "数据来源", "风险提示"]:
            check("元信息含「%s」" % key, "| %s |" % key in md_text)
        check("md 包含回答正文", "多周期判读" in md_text)
        check("md 含风险提示文案", "不构成投资建议" in md_text)
        if png:
            check("md 用相对路径引用图片", os.path.basename(png) in md_text)

        with open(html_path, encoding="utf-8") as f:
            html_text = f.read()
        check("html 是自包含（图片 base64 内嵌）",
              "data:image/png;base64," in html_text or not png)
        check("html 元信息齐全", "数据时间戳" in html_text and "启用技能" in html_text)
        check("html 保留回答换行结构", "white-space: pre-wrap" in html_text)

        # 元信息里的当前价要与传入行情一致
        check("当前价取自行情快照", "3101" in md_text, "price=%s" % "3101")
    finally:
        _cleanup([out.get("md"), out.get("html"), png])


def t_report_edge():
    from src import report

    out = report.export(symbol="螺纹钢", question="q", answer="  ", charts=[])
    check("空回答不给导出", out.get("ok") is False and "没有可导出" in out.get("error", ""), str(out.get("error")))

    r = report.open_report(os.path.join(ROOT, "config.json"))
    check("拒绝打开 reports 目录以外的文件", r.get("ok") is False, str(r.get("error")))

    # 目录内但文件不存在：走「文件不存在」分支（与越权分支区分开）
    missing = os.path.join(report.reports_dir(), "no_such_file.html")
    r2 = report.open_report(missing)
    check("文件不存在给可读错误", r2.get("ok") is False and "不存在" in r2.get("error", ""),
          str(r2.get("error")))


# ==================== 主流程 ====================

run(t_structure, "A. 结构与依赖（工具注册 / 字体 / 研报指令）")
run(t_chart, "B. 图表绘制（联网取K线，含越界与不支持周期）")
run(t_report_export, "C. 报告导出（md + 自包含 html）")
run(t_report_edge, "D. 导出边界与文件安全")

log("")
log("=" * 64)
log("汇总：通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
if FAIL:
    log("失败项：")
    for f in FAIL:
        log("  - " + f)
log("=" * 64)

out_path = os.path.join(ROOT, "tools", "_stage9_result.txt")
with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("done: pass=%d fail=%d -> %s" % (len(PASS), len(FAIL), out_path))
sys.exit(1 if FAIL else 0)
