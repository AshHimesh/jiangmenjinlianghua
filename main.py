# -*- coding: utf-8 -*-
"""
江门金量化 · 程序入口

阶段 5：打包为 Windows 可执行程序。
- 前端页面 web/ 打包进程序内部（只读资源）
- skills/、config.json、cache.db 放在程序旁边的「用户数据目录」，用户可自行编辑
- 打包后无控制台窗口，因此异常会写入 error.log 便于排查
"""
import os
import sys
import traceback

from src.paths import data_path, resource_path
from src.skills import ensure_dir as ensure_skills_dir


def _write_crash_log():
    try:
        path = data_path("error.log")
        with open(path, "w", encoding="utf-8") as f:
            f.write("江门金量化 · 启动失败\n")
            f.write("=" * 60 + "\n")
            f.write(traceback.format_exc())
        return path
    except Exception:
        return None


def _run():
    import webview

    from src.api import Api
    from src.chat import ChatSession
    from src.fetcher import QuoteService

    # 首次运行时准备技能目录（打包后位于程序旁边）
    ensure_skills_dir()

    # 行情后台刷新服务
    service = QuoteService()
    service.start()

    # 对话会话
    chat = ChatSession()

    api = Api(service, chat)
    index_path = resource_path("web", "index.html")

    if not os.path.isfile(index_path):
        raise RuntimeError("前端资源缺失：%s" % index_path)

    webview.create_window(
        title="江门金量化",
        url=index_path,
        js_api=api,
        width=1200,
        height=800,
        min_size=(960, 640),
    )

    # 阻塞主线程，保持窗口运行，直到用户关闭窗口
    webview.start()


def _selftest():
    """诊断模式（江门金量化.exe --selftest）：逐项检查打包环境，结果写入 selftest.log。"""
    lines = []

    def log(*a):
        lines.append(" ".join(str(x) for x in a))

    try:
        from src.paths import is_frozen, resources_dir, data_dir
        from src.skills import list_skills
        from src.fetcher import fetch_all
        from src.analysis import build_report
        from src import qacache
        from src.symbols import SYMBOL_MAP

        log("江门金量化 · 自检报告")
        log("=" * 60)
        log("打包模式 frozen : %s" % is_frozen())
        log("资源目录        : %s" % resources_dir())
        log("用户数据目录    : %s" % data_dir())

        idx = resource_path("web", "index.html")
        log("前端页面存在    : %s (%s)" % (os.path.isfile(idx), idx))

        try:
            sk = list_skills()
            log("技能数量        : %d  %s" % (len(sk), [s["name"] for s in sk]))
        except Exception as e:
            log("技能检查失败    : %s" % e)

        log("")
        log("---- 行情抓取 ----")
        try:
            quotes = fetch_all()
            ok = sum(1 for v in quotes.values() if v)
            log("成功: %d / %d" % (ok, len(SYMBOL_MAP)))
            for name in SYMBOL_MAP:
                v = quotes.get(name)
                log("  %-12s %s" % (name, ("价格=%s 涨跌=%s" % (v["price"], v["change"])) if v else "❌ 无数据"))
        except Exception as e:
            log("行情抓取异常: %r" % e)
            import traceback
            log(traceback.format_exc())

        log("")
        log("---- K线与指标 ----")
        for nm in ["螺纹钢", "现货黄金", "美元指数"]:
            try:
                txt, used = build_report(nm)
                log("  %-8s 周期=%s 报告长度=%d" % (nm, used, len(txt) if txt else 0))
            except Exception as e:
                log("  %-8s ❌ %r" % (nm, e))

        log("")
        log("---- AI 工具（函数调用） ----")
        try:
            from src.tools import TOOL_SCHEMAS, execute

            log("  已定义工具: %s" % "、".join(t["function"]["name"] for t in TOOL_SCHEMAS))
            r1 = execute("get_kline", '{"symbol":"螺纹钢","period":"D","limit":3}')
            log("  get_kline   : %s" % r1.split("\n")[0])
            r2 = execute("get_indicators", '{"symbol":"现货黄金","period":"D"}')
            log("  get_indicators: %s" % r2.split("\n")[0][:90])
            r3 = execute("list_symbols", "{}")
            log("  list_symbols: %s" % r3.split("\n")[1])
            r4 = execute("get_kline", '{"symbol":"现货黄金","period":"12H"}')
            log("  不支持周期校验: %s" % r4[:60])
        except Exception as e:
            log("  工具测试失败: %r" % e)
            import traceback
            log(traceback.format_exc())

        log("")
        log("---- 金十数据（阶段 7 · MCP）----")
        try:
            from src import jin10

            st = jin10.status()
            log("  启用开关        : %s" % st["enabled"])
            log("  已填 API Key    : %s" % st["has_key"])
            log("  功能可用        : %s" % st["available"])
            if st["reason"]:
                log("  说明            : %s" % st["reason"])
            log("  端点            : %s" % st["base_url"])
            log("  覆盖报价品种    : %d 个" % st["codes_count"])
            q = st["quota"]
            log("  今日已用额度    : %d / %d 次（%s）" % (q["total"], q["limit"], q["date"]))

            r = jin10.selftest()
            for ln in (r.get("line") or "").split("\n"):
                if ln.strip():
                    log("  连通性          : %s" % ln)
            for ln in (r.get("detail") or "").split("\n"):
                if ln.strip():
                    log("                    %s" % ln)
        except Exception as e:
            log("  金十检查失败    : %r" % e)
            import traceback
            log(traceback.format_exc())

        log("")
        log("---- 缓存 ----")
        try:
            log("  %s" % qacache.stats())
        except Exception as e:
            log("  ❌ %r" % e)

        log("")
        log("自检完成")
    except Exception:
        import traceback
        lines.append("自检过程异常：")
        lines.append(traceback.format_exc())

    out = data_path("selftest.log")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return
    try:
        _run()
    except Exception:
        log_path = _write_crash_log()
        # 有控制台时同时打印出来
        traceback.print_exc()
        if log_path:
            sys.stderr.write("\n错误详情已写入：%s\n" % log_path)
        raise


if __name__ == "__main__":
    main()
