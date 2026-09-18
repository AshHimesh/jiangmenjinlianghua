# -*- coding: utf-8 -*-
"""江门金量化 · 暴露给前端（pywebview js_api）的接口。"""
from . import qacache
from .analysis import warm
from .config import PROVIDERS, load_config, save_config
from .skills import import_skill, list_skills, resolve_active, stats as skill_stats


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
        return save_config(cfg)

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

    # ---------- 相似问题缓存 ----------
    def get_cache_stats(self):
        """返回缓存统计。"""
        return qacache.stats()

    def clear_cache(self):
        """清空相似问题缓存。"""
        return qacache.clear()
