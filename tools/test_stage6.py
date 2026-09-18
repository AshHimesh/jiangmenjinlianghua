# -*- coding: utf-8 -*-
"""阶段6 测试：AI 工具调用（Function Calling）循环。"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import ai as ai_mod
from src import chat as chat_mod
from src import tools as tools_mod
from src.chat import ChatSession, build_system_prompt
from src.tools import TOOL_SCHEMAS, execute

OUT = []
CAPTURED = {}


def log(*args):
    OUT.append(" ".join(str(a) for a in args))


# ================= 1. 工具定义与执行器 =================
log("=== 1. 工具定义 ===")
for t in TOOL_SCHEMAS:
    fn = t["function"]
    log("  %-16s %s" % (fn["name"], fn["description"][:52].replace("\n", " ")))

log("")
log("=== 2. 工具执行器直接测试 ===")
r = execute("get_kline", json.dumps({"symbol": "螺纹钢", "period": "D", "limit": 3}))
log("  get_kline(螺纹钢, 日线, 3根):")
for line in r.split("\n"):
    log("     " + line)

r2 = execute("get_indicators", json.dumps({"symbol": "现货黄金", "period": "12H"}))
log("  get_indicators(现货黄金, 12小时) —— 该周期不可用时的返回:")
log("     " + r2)

r3 = execute("get_indicators", json.dumps({"symbol": "现货黄金", "period": "D"}))
log("  get_indicators(现货黄金, 日线) 前 3 行:")
for line in r3.split("\n")[:3]:
    log("     " + line)

log("  错误处理:")
log("     未知品种 -> " + execute("get_kline", '{"symbol":"比特币","period":"D"}'))
log("     坏JSON   -> " + execute("get_kline", "not-json"))
log("     未知工具 -> " + execute("no_such_tool", "{}"))

r4 = execute("list_symbols", "{}")
log("  list_symbols 前 4 行:")
for line in r4.split("\n")[:4]:
    log("     " + line)

# ================= 3. 模拟「先调工具、再回答」的流式循环 =================
log("")
log("=== 3. 工具调用循环（模拟）===")


class FakeResp:
    def __init__(self, lines, status=200, text=""):
        self._lines = lines
        self.status_code = status
        self.encoding = "utf-8"
        self.text = text

    def iter_lines(self, decode_unicode=True):
        for ln in self._lines:
            yield ln

    def close(self):
        pass


def sse(obj):
    return "data: " + json.dumps(obj, ensure_ascii=False)


# 第1轮：模型要求调用 get_kline（参数分两片下发，测试拼接）
ROUND1 = [
    sse({"choices": [{"delta": {"reasoning_content": "用户问螺纹钢，我先取日线数据。"}}]}),
    sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                                "function": {"name": "get_kline",
                                                             "arguments": '{"symbol":"螺纹钢","period":"D",'}}]}}]}),
    sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"limit":5}'}}]}}]}),
    "data: [DONE]",
]
# 第2轮：模型拿到工具结果后给出最终答案
ROUND2 = [
    sse({"choices": [{"delta": {"reasoning_content": "数据拿到了，开始分析。"}}]}),
    sse({"choices": [{"delta": {"content": "【模拟最终答案】螺纹钢日线最近5根已读取。"}}]}),
    "data: [DONE]",
]

calls = {"n": 0, "payloads": []}


def fake_post(url, headers=None, json=None, stream=True, timeout=None):
    calls["n"] += 1
    calls["payloads"].append(json)
    return FakeResp(ROUND1 if calls["n"] == 1 else ROUND2)


ai_mod.requests.post = fake_post

from src import qacache
qacache.clear()   # 清掉历史缓存，否则会命中缓存而不发请求

session = ChatSession()
quotes = {"螺纹钢": {"price": 3139.0, "change": -0.25}}
cfg = {"base_url": "http://x/v1", "api_key": "k", "model": "glm-4-plus",
       "inject_market": True, "enable_tools": True, "active_skills": None}

r = session.ask("螺纹钢最近5根日线什么情况", cfg, quotes, "螺纹钢")
log("  ask 返回: %s" % r)
st = None
for _ in range(120):
    st = session.get_stream(r["id"])
    if st["done"]:
        break
    time.sleep(0.2)

log("  HTTP 请求次数: %d （期望 2：先调工具，再出答案）" % calls["n"])
log("  第1轮是否带 tools: %s" % ("tools" in calls["payloads"][0]))
log("  第2轮是否带 tools: %s" % ("tools" in calls["payloads"][1]))
log("  工具调用记录: %s" % st["tools"])
log("  思考内容: %s" % st["thinking"])
log("  最终答案: %s" % st["content"])
log("  错误: %s" % st["error"])
log("  历史条数: %d （期望 2）" % len(session.history))

# 检查第2轮发给模型的 messages 里是否含 assistant.tool_calls 与 tool 结果
msgs = calls["payloads"][1]["messages"]
roles = [m["role"] for m in msgs]
log("  第2轮 messages 角色序列: %s" % roles)
tool_msg = [m for m in msgs if m["role"] == "tool"]
if tool_msg:
    log("  tool 结果前 2 行:")
    for line in tool_msg[0]["content"].split("\n")[:2]:
        log("     " + line)

# ================= 4. 不支持工具时的降级 =================
log("")
log("=== 4. 模型不支持函数调用时的自动降级 ===")
calls["n"] = 0


def fake_post_unsupported(url, headers=None, json=None, stream=True, timeout=None):
    calls["n"] += 1
    if json.get("tools"):
        return FakeResp([], status=400,
                        text='{"error":{"message":"This model does not support tools","type":"invalid_request_error"}}')
    return FakeResp(ROUND2)


ai_mod.requests.post = fake_post_unsupported
chat_mod._TOOLS_UNSUPPORTED.clear()
qacache.clear()
s2 = ChatSession()
cfg2 = dict(cfg, model="deepseek-reasoner")
r2 = s2.ask("螺纹钢怎么看", cfg2, quotes, "螺纹钢")
st2 = None
for _ in range(120):
    st2 = s2.get_stream(r2["id"])
    if st2["done"]:
        break
    time.sleep(0.2)
log("  请求次数: %d （期望 2：先带工具失败，再降级重试）" % calls["n"])
log("  最终答案: %s" % st2["content"])
log("  错误: %s" % st2["error"])
log("  已记入不支持列表: %s" % list(chat_mod._TOOLS_UNSUPPORTED))

# 第二次问同一模型，应直接不带工具
calls["n"] = 0
qacache.clear()
s3 = ChatSession()
r3 = s3.ask("纯碱怎么看", cfg2, quotes, "纯碱")
for _ in range(60):
    if s3.get_stream(r3["id"])["done"]:
        break
    time.sleep(0.2)
log("  再次提问的请求次数: %d （期望 1，已直接降级）" % calls["n"])

# ================= 5. 系统提示词 =================
log("")
log("=== 5. 系统提示词 ===")
with_tools = build_system_prompt({"enable_tools": True, "active_skills": None})
without = build_system_prompt({"enable_tools": False, "active_skills": None})
log("  启用工具 system 长度: %d" % len(with_tools))
log("  关闭工具 system 长度: %d" % len(without))
log("  含工具说明: %s" % ("你可以主动读取数据" in with_tools))
log("  关闭时不含工具说明: %s" % ("你可以主动读取数据" not in without))

with open("tools/_stage6_test.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("done")
