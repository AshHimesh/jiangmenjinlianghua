# -*- coding: utf-8 -*-
"""金十数据 MCP 服务连通性与能力探测（标准 MCP 流程）。"""
import json
import os
import sys

import requests

BASE = "https://mcp.jin10.com/mcp"
TOKEN = "sk-REDACTED-BY-AUTHOR"
PROTOCOL = "2025-11-25"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "Authorization": "Bearer " + TOKEN,
}

OUT = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


class McpClient:
    def __init__(self):
        self.session = requests.Session()
        self.session_id = None
        self._id = 0

    def _next_id(self):
        self._id += 1
        return self._id

    def _parse(self, resp):
        ct = resp.headers.get("content-type", "")
        if "text/event-stream" in ct:
            for line in resp.text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    try:
                        return json.loads(line[5:].strip())
                    except ValueError:
                        continue
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    def post(self, method, params=None, notify=False, timeout=30):
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            body["id"] = self._next_id()
        headers = dict(HEADERS)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        resp = self.session.post(BASE, headers=headers, json=body, timeout=timeout)
        if resp.headers.get("Mcp-Session-Id"):
            self.session_id = resp.headers["Mcp-Session-Id"]
        if notify:
            return resp.status_code, None
        return resp.status_code, self._parse(resp)


c = McpClient()

# ---------- 1. initialize ----------
log("=== 1. initialize ===")
code, data = c.post("initialize", {
    "protocolVersion": PROTOCOL,
    "capabilities": {},
    "clientInfo": {"name": "jiangmen-jinlianghua", "version": "1.0.0"},
})
log("HTTP %s   session=%s" % (code, (c.session_id or "")[:16] + "..."))
if data:
    res = data.get("result") or {}
    log("协议版本  : %s" % res.get("protocolVersion"))
    log("服务端信息: %s" % json.dumps(res.get("serverInfo"), ensure_ascii=False))
    log("能力      : %s" % json.dumps(res.get("capabilities"), ensure_ascii=False))

# ---------- 2. notifications/initialized ----------
log("")
log("=== 2. notifications/initialized ===")
log("HTTP %s" % c.post("notifications/initialized", {}, notify=True)[0])

# ---------- 3. tools/list ----------
log("")
log("=== 3. tools/list ===")
_, data = c.post("tools/list", {})
tools = ((data or {}).get("result") or {}).get("tools") or []
log("工具数量: %d" % len(tools))
for t in tools:
    schema = t.get("inputSchema") or {}
    props = list((schema.get("properties") or {}).keys())
    log("  %-16s %s" % (t.get("name"), (t.get("description") or "")[:56].replace("\n", " ")))
    log("      参数: %s   必填: %s" % (props, schema.get("required")))

# ---------- 4. resources/list ----------
log("")
log("=== 4. resources/list ===")
_, data = c.post("resources/list", {})
res_list = ((data or {}).get("result") or {}).get("resources") or []
log("资源数量: %d" % len(res_list))
for r in res_list:
    log("  %-22s %s" % (r.get("uri"), (r.get("name") or "")[:40]))

# ---------- 5. 读取 quote://codes ----------
log("")
log("=== 5. 读取资源 quote://codes ===")
_, data = c.post("resources/read", {"uri": "quote://codes"})
contents = ((data or {}).get("result") or {}).get("contents") or []
for ct in contents:
    text = ct.get("text") or ""
    log("  长度 %d" % len(text))
    try:
        obj = json.loads(text)
        log("  %s" % json.dumps(obj, ensure_ascii=False)[:1500])
    except ValueError:
        log("  %s" % text[:800])

# ---------- 6. tools/call 抽样 ----------
def call_tool(name, args, label=""):
    log("")
    log("--- tools/call %s %s ---" % (name, label))
    _, data = c.post("tools/call", {"name": name, "arguments": args})
    if data is None:
        log("  (无返回)")
        return
    if data.get("error"):
        log("  JSON-RPC 错误: %s" % json.dumps(data["error"], ensure_ascii=False)[:200])
        return
    result = data.get("result") or {}
    log("  isError: %s" % result.get("isError"))
    sc = result.get("structuredContent")
    if sc is not None:
        log("  structuredContent: %s" % json.dumps(sc, ensure_ascii=False)[:900])
    else:
        log("  (无 structuredContent)")
    content = result.get("content") or []
    if content:
        txt = content[0].get("text") or ""
        log("  content[0] 前200字: %s" % txt[:200].replace("\n", " "))


call_tool("get_quote", {"code": "XAUUSD"}, "(现货黄金)")
call_tool("get_kline", {"code": "XAUUSD", "count": 3}, "(现货黄金K线)")
call_tool("list_calendar", {}, "(财经日历)")
call_tool("search_flash", {"keyword": "黄金"}, "(黄金快讯)")
call_tool("get_quote", {"code": "RB0"}, "(测试国内期货代码)")

with open("tools/_jin10_mcp.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("done")
