# -*- coding: utf-8 -*-
"""对话流式逻辑测试：用 mock 模拟「边思考边回答」的模型。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import chat as chat_mod
from src.chat import ChatSession

OUT = []


def log(*args):
    OUT.append(" ".join(str(a) for a in args))


# ---------- 1. 正常流式（含思考过程） ----------
def fake_stream(base_url, api_key, model, messages, on_delta, timeout=180):
    for t in ["用户问的是黄金。", "当前价格 4393.53 美元/盎司。", "需要结合美元指数一起看。"]:
        on_delta({"reasoning_content": t})
        time.sleep(0.06)
    for c in ["根据当前行情，", "黄金报 4393.53 美元/盎司，", "跌幅 0.19%。"]:
        on_delta({"content": c})
        time.sleep(0.06)


chat_mod.stream_completion = fake_stream

log("=== 1. 思考 + 正文 流式测试 ===")
session = ChatSession()
quotes = {"现货黄金": {"price": 4393.53, "change": -0.19}}
res = session.ask("黄金怎么看？",
                  {"base_url": "x", "api_key": "y", "model": "z", "inject_market": True},
                  quotes, "现货黄金")
log("ask 返回:", res)

req_id = res["id"]
seen = []
while True:
    st = session.get_stream(req_id)
    seen.append((len(st["thinking"]), len(st["content"]), st["done"]))
    if st["done"]:
        break
    time.sleep(0.08)

log("思考内容:", st["thinking"])
log("回答内容:", st["content"])
log("思考用时:", st["thinking_seconds"], "秒")
log("thinking_done:", st["thinking_done"], "  最终 done:", st["done"], "  error:", st["error"])
log("轮询次数:", len(seen), " 增量变化:", seen[:6], "...")
log("历史条数:", len(session.history))
for m in session.history:
    log("   ", m["role"], "->", m["content"][:40])

# ---------- 2. 真实 stream_completion：缺 Key 的友好报错 ----------
log("")
log("=== 2. 未配置 Key 的报错测试 ===")
import importlib
from src.ai import stream_completion as real_stream_completion
chat_mod.stream_completion = real_stream_completion
s2 = ChatSession()
r2 = s2.ask("测试", {"base_url": "", "api_key": "", "model": "", "inject_market": True}, quotes, None)
for _ in range(30):
    st2 = s2.get_stream(r2["id"])
    if st2["done"]:
        break
    time.sleep(0.05)
log("错误提示:", st2["error"])
log("历史条数(应为0):", len(s2.history))

# ---------- 3. 清空 ----------
log("")
log("=== 3. 清空对话 ===")
session.clear()
log("清空后历史条数:", len(session.history), " 状态:", session.get_stream()["id"])

with open("tools/_chat_test.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("done")
