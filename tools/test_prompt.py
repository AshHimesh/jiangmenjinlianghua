# -*- coding: utf-8 -*-
"""验证：AI 实际收到的提示词内容（多周期技术面是否注入成功）。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import chat as chat_mod
from src.chat import ChatSession
from src.fetcher import fetch_all

OUT = []
CAPTURED = {}


def log(*args):
    OUT.append(" ".join(str(a) for a in args))


def fake_stream(base_url, api_key, model, messages, on_delta, timeout=180):
    CAPTURED["messages"] = messages
    on_delta({"reasoning_content": "（模拟思考）"})
    on_delta({"content": "（模拟回答）"})


chat_mod.stream_completion = fake_stream

log("=== 抓取实时行情 ===")
quotes = fetch_all()
log("品种数: %d" % len(quotes))

cfg = {"base_url": "x", "api_key": "y", "model": "z", "inject_market": True}

for question, focus in [("螺纹钢现在怎么看？", "螺纹钢"),
                        ("黄金和白银哪个强？", "现货黄金")]:
    log("")
    log("=" * 70)
    log("提问: %s   （当前查看: %s）" % (question, focus))
    log("=" * 70)

    session = ChatSession()
    t0 = time.time()
    r = session.ask(question, cfg, quotes, focus)
    for _ in range(600):
        st = session.get_stream(r["id"])
        if st["done"]:
            break
        time.sleep(0.05)
    cost = time.time() - t0

    msgs = CAPTURED.get("messages") or []
    log("准备提示词耗时: %.1f 秒" % cost)
    log("消息条数: %d（system=%d）" % (len(msgs), sum(1 for m in msgs if m["role"] == "system")))
    for m in msgs:
        if m["role"] == "system":
            log("  [system] 长度 %d 字符" % len(m["content"]))
        else:
            log("  [%s] 长度 %d 字符" % (m["role"], len(m["content"])))
    user = [m for m in msgs if m["role"] == "user"][-1]["content"]
    log("")
    log("--- 用户消息全文（AI 实际看到的内容）---")
    log(user[:4000])
    log("--- 全文长度: %d 字符，约 %d tokens ---" % (len(user), len(user) // 2))

with open("tools/_prompt_test.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("done")
