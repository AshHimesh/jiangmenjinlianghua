# -*- coding: utf-8 -*-
"""阶段4 测试：Skill 加载 + 相似问题缓存。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import chat as chat_mod
from src import qacache
from src.chat import ChatSession, build_system_prompt
from src.skills import list_skills, stats

OUT = []
CAPTURED = {}
CALLS = {"n": 0}


def log(*args):
    OUT.append(" ".join(str(a) for a in args))


# ---------- 1. 技能加载 ----------
log("=== 1. 技能加载 ===")
for s in list_skills():
    log("  %-26s 文件=%-30s %d 字符 (.%s)" % (s["name"], s["filename"], s["chars"], s["ext"]))
st = stats(None)
log("  默认全部激活：%d 个，共 %d 字符" % (st["count"], st["chars"]))
log("  仅激活 1 个：%s" % stats(["斐波那契短线入场专家skill.txt"]))
log("  全不激活：%s" % stats(["不存在的.txt"]))

log("")
log("=== 2. 系统提示词构成 ===")
p_none = build_system_prompt({"active_skills": ["不存在的.txt"]})
p_all = build_system_prompt({"active_skills": None})
log("  无技能 system 长度: %d 字符" % len(p_none))
log("  全技能 system 长度: %d 字符（约 %d tokens，稳定前缀可命中缓存）" % (len(p_all), len(p_all) // 2))
log("  含技能声明头: %s" % ("【必须遵循的分析技能 Skill】" in p_all))
log("  含技能1: %s   含技能2: %s" % ("十年实盘经验的黄金外汇交易专家" in p_all,
                                     "艾略特波浪理论" in p_all))

log("")
log("=== 3. 相似度算法验证（归一化后 + 混合评分）===")
pairs = [
    ("螺纹钢支撑位在哪", "螺纹钢的支撑位在哪里？", True),
    ("螺纹钢现在怎么看？", "螺纹钢现在怎么看", True),
    ("黄金怎么看", "黄金现在怎么看？", True),
    ("螺纹钢支撑位在哪", "螺纹钢压力位在哪", False),
    ("螺纹钢怎么看", "纯碱怎么看", False),
    ("今天天气怎么样", "螺纹钢支撑位在哪", False),
    ("黄金支撑位", "白银支撑位", False),
]
for a, b, expect in pairs:
    na, nb = qacache.normalize(a), qacache.normalize(b)
    s = qacache.similarity(na, nb)
    hit = s >= qacache.SIM_THRESHOLD
    mark = "✅" if hit == expect else "❌"
    log("  %s %.3f (期望%s) 「%s」vs「%s」" % (mark, s, "命中" if expect else "不命中", a, b))

# ---------- 4. 缓存读写 ----------
log("")
log("=== 4. 缓存读写 ===")
qacache.clear()
sig = qacache.signature("deepseek-reasoner", None)
qacache.store("螺纹钢现在怎么看？", "螺纹钢", sig, "【缓存答案A】螺纹钢日线收3146...")
qacache.store("黄金支撑位在哪里", "现货黄金", sig, "【缓存答案B】黄金支撑4340...")
log("  统计: %s" % qacache.stats())
for q, f, desc in [("螺纹钢现在怎么看？", "螺纹钢", "完全相同"),
                   ("螺纹钢现在怎么看", "螺纹钢", "少个问号"),
                   ("螺纹钢现在怎么看的", "螺纹钢", "多个字"),
                   ("螺纹钢现在怎么看？", "纯碱", "同问题不同品种"),
                   ("黄金支撑位在哪里", "现货黄金", "完全相同"),
                   ("今天天气怎么样", "螺纹钢", "完全无关")]:
    hit = qacache.lookup(q, f, sig)
    log("  %s [%s]「%s」%s" % ("✅命中" if hit else "⬜未命中", desc, q,
                              (" 相似度%.3f" % hit["similarity"]) if hit else ""))

# ---------- 5. 对话流程 ----------
log("")
log("=== 5. 对话流程：命中缓存则不调 AI ===")


def fake_stream(base_url, api_key, model, messages, on_delta, timeout=180):
    CALLS["n"] += 1
    CAPTURED["sys"] = messages[0]["content"]
    on_delta({"reasoning_content": "思考中…"})
    on_delta({"content": "【AI生成答案 第%d次】" % CALLS["n"]})


chat_mod.stream_completion = fake_stream
session = ChatSession()
quotes = {"螺纹钢": {"price": 3146.0, "change": -0.57}}
cfg = {"base_url": "x", "api_key": "y", "model": "deepseek-reasoner",
       "inject_market": True, "active_skills": None}


def ask_and_wait(q, focus):
    r = session.ask(q, cfg, quotes, focus)
    if "id" not in r:
        return r, None
    st = None
    for _ in range(600):
        st = session.get_stream(r["id"])
        if st["done"]:
            break
        time.sleep(0.05)
    return r, st


qacache.clear()
for q, f, desc in [("螺纹钢支撑位在哪", "螺纹钢", "第1次(新问题)"),
                   ("螺纹钢的支撑位在哪里？", "螺纹钢", "第2次(相似问题)"),
                   ("纯碱现在怎么看", "纯碱", "第3次(新问题)"),
                   ("纯碱现在怎么看？", "纯碱", "第4次(相似问题)")]:
    r, st = ask_and_wait(q, f)
    log("  %-18s cached=%-5s 内容=%s" % (desc, r.get("cached"), (st["content"] if st else r)[:36]))
log("  实际调用 AI 次数: %d （期望 2）" % CALLS["n"])
log("  历史条数: %d （4轮问答，期望 8）" % len(session.history))

log("")
log("=== 6. 模型变化后缓存自动失效 ===")
sig2 = qacache.signature("deepseek-chat", None)
log("  换模型查同一问题: %s" % ("❌命中(不应)" if qacache.lookup("螺纹钢支撑位在哪", "螺纹钢", sig2)
                                else "✅未命中"))
log("  system 提示词含技能: %s" % ("【必须遵循的分析技能 Skill】" in CAPTURED.get("sys", "")))

with open("tools/_stage4_test.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("done")
