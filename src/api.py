# -*- coding: utf-8 -*-
"""江门金量化 · 暴露给前端（pywebview js_api）的接口。"""
from . import jin10, qacache
from .analysis import warm
from .config import PROVIDERS, load_config, save_config
from .report import export as export_report_file, list_reports, open_reports_dir
from .skills import import_skill, list_skills, resolve_active, stats as skill_stats

# 一键研报的指令（阶段 9）。写成固定模板：AI 只负责按 skill 流程填内容，
# 价位一律要求来自给定数据，最后必须画图 —— 图是报告的必要组成。
REPORT_PROMPT = (
    "请对「%(symbol)s」做一次研报级分析，并严格按以下结构输出：\n"
    "一、多周期判读：先大周期定方向，再小周期找时机，写明你依据的周期。\n"
    "二、浪型计数：说明你怎么数的浪、依据是什么、当前处于第几浪。\n"
    "三、关键价位：支撑位至少 2 个、压力位至少 2 个，每个都说明依据。\n"
    "四、交易计划：入场位、止损位 SL、分档止盈 TP1/TP2/TP3，并算出盈亏比。\n"
    "五、事件风险：如已启用金十，先查本周财经日历，列出影响该品种的重大事件与公布时间。\n"
    "六、风险提示。\n"
    "最后**必须**调用 render_analysis_chart，把你数出的浪型与上述价位画成图，"
    "period 用你交易计划所在的主周期。\n"
    "所有价位必须来自给定数据或工具返回，不得编造；数据缺失就如实说明。"
)


class Api:
    def __init__(self, service, chat):
        self._service = service
        self._chat = chat

    # ---------- 行情 ----------
    def get_symbols(self):
        """返回品种分组（用于渲染左侧列表）。"""
        return self._service.get_symbols()

    def get_quotes(self):
        """返回全部品种的实时行情快照：{name: {price, change, updated, stale}}。"""
        return self._service.get_quotes()

    def prepare(self, name):
        """用户切换品种时调用：后台预热该品种的多周期K线缓存，避免提问时等待。"""
        warm(name)
        return {"ok": True}

    # ---------- 配置 ----------
    def get_config(self):
        """返回当前 AI 配置 + 可选服务商列表。"""
        return {"config": load_config(), "providers": PROVIDERS}

    def save_config(self, cfg):
        """保存 AI 配置，返回保存后的配置。"""
        saved = save_config(cfg)
        # Key / 端点变了要丢掉旧的金十会话，否则会拿着旧凭据继续用
        try:
            jin10.reset_client()
        except Exception:
            pass
        return saved

    # ---------- 金十数据（阶段 7）----------
    def get_jin10_status(self):
        """金十启用状态、今日额度用量、品种覆盖数（给 ⚙ 面板展示）。"""
        try:
            return jin10.status()
        except Exception as e:
            return {
                "enabled": False, "has_key": False, "available": False,
                "reason": "金十状态读取失败：%s" % e,
                "base_url": "", "quota": {"date": "", "limit": 0, "total": 0, "tools": {}},
                "codes_count": 0,
            }

    def jin10_selftest(self):
        """点「连接自检」时调用：真实握手 + 一次工具调用，结果直接展示给用户。"""
        try:
            return jin10.selftest()
        except Exception as e:
            return {"ok": False, "skipped": False, "line": "自检异常：%s" % e, "detail": ""}

    # ---------- 技能 ----------
    def get_skills(self):
        """返回全部技能、当前激活的技能，以及体量统计。"""
        cfg = load_config()
        active = resolve_active(cfg.get("active_skills"))
        items = []
        for s in list_skills():
            item = dict(s)
            item["active"] = s["filename"] in active
            items.append(item)
        return {
            "skills": items,
            "active": active,
            "stats": skill_stats(cfg.get("active_skills")),
        }

    def set_skills(self, active):
        """设置激活的技能文件列表（传空列表 = 全部激活）。"""
        cfg = load_config()
        cfg["active_skills"] = active or None
        save_config(cfg)
        return self.get_skills()

    def import_skill_dialog(self):
        """弹出系统文件选择框，导入 .txt / .md 技能文件。"""
        try:
            import webview
            if not webview.windows:
                return {"error": "窗口未就绪"}
            result = webview.windows[0].create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=("技能文件 (*.txt;*.md)", "所有文件 (*.*)"),
            )
        except Exception as e:
            return {"error": "打开文件框失败：%s" % e}

        if not result:
            return {"cancelled": True}
        path = result[0] if isinstance(result, (list, tuple)) else result
        res = import_skill(path)
        if res.get("ok"):
            res["data"] = self.get_skills()
        return res

    # ---------- 对话 ----------
    def ask(self, question, focus=None, force=False):
        """发起提问，立即返回请求 id（回答通过 get_stream 轮询获取）。

        force=True 时跳过相似问题缓存，强制调用 AI。
        """
        cfg = load_config()
        quotes = self._service.get_quotes()
        return self._chat.ask(question, cfg, quotes, focus, force=force)

    def get_stream(self, req_id=None):
        """读取当前流式状态：{thinking, content, done, error, thinking_seconds}。"""
        return self._chat.get_stream(req_id)

    def clear_chat(self):
        """清空对话历史。"""
        return self._chat.clear()

    # ---------- 报告（阶段 9）----------
    def make_report(self, symbol=None):
        """一键生成完整研报：按启用的 skill 流程分析，最后画K线标注图。

        实现方式 = 用固定指令发起一次提问，之后照常走 get_stream 轮询，
        答完后前端再调 export_report() 把回答落成文件。
        """
        symbol = (symbol or "").strip()
        if not symbol:
            return {"error": "请先在左侧选中一个品种。"}
        cfg = load_config()
        if not cfg.get("enable_tools"):
            return {"error": "生成研报需要开启「允许 AI 主动读取数据（工具调用）」，请到 ⚙ 设置里打开。"}
        if not (cfg.get("api_key") or "").strip():
            return {"error": "还没配置 AI 的 API Key，请到 ⚙ 设置里填写。"}
        return self.ask(REPORT_PROMPT % {"symbol": symbol}, focus=symbol, force=True)

    def export_report(self):
        """把最近一条回答导出为报告（.md + 自包含 .html），返回文件路径。"""
        st = self._chat.get_stream()
        if not st or not st.get("content"):
            return {"error": "还没有可导出的回答。"}
        if st.get("error"):
            return {"error": "上一条回答出错，无法导出：%s" % st["error"]}
        cfg = load_config()
        active = resolve_active(cfg.get("active_skills"))
        res = export_report_file(
            symbol=st.get("focus") or "",
            question=st.get("question") or "",
            answer=st.get("content") or "",
            charts=st.get("charts") or [],
            model=cfg.get("model", ""),
            skills=active,
            quotes=self._service.get_quotes(),
        )
        return res

    def list_reports(self):
        """最近导出的报告文件列表。"""
        return list_reports()

    def open_reports_dir(self):
        """用资源管理器打开 reports 目录。"""
        return open_reports_dir()

    def open_report(self, path):
        """用系统默认程序打开某个报告文件（.html → 浏览器，.md → 记事本）。"""
        from .report import open_report as _open
        return _open(path)

    # ---------- 相似问题缓存 ----------
    def get_cache_stats(self):
        """返回缓存统计。"""
        return qacache.stats()

    def clear_cache(self):
        """清空相似问题缓存。"""
        return qacache.clear()
