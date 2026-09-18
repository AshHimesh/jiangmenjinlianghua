# -*- coding: utf-8 -*-
"""
金十数据 MCP 服务探测（标准 MCP 流程）。

用途：阶段 7 开发期的联调验证。运行后会生成 tools/_jin10_mcp.txt。

    .venv\\Scripts\\python.exe tools\\check_jin10_mcp.py

已实测到的服务行为（2026-09-18）：
- initialize / notifications/initialized / tools/call 正常
- **tools/list 与 resources/list 均返回空列表**：该服务端不提供能力发现，
  因此客户端必须**硬编码**工具名与参数，不能依赖 tools/list
- resources/read（quote://codes）取不到内容
- 响应若为 SSE，中文必须显式按 UTF-8 解码（requests 默认按 ISO-8859-1 解 text/*，会变乱码）
"""
import json
import os
import sys

import requests

BASE = "https://mcp.jin10.com/mcp"
PROTOCOL = "2025-11-25"


def _load_token():
    """
    开发期临时 token（交付程序里绝不出现）。

    优先级：环境变量 JIN10_DEV_TOKEN → 本地未跟踪文件 tools/_jin10_token.txt
    （`_*.txt` 已被 .gitignore 覆盖）。**不要把 token 写回本文件**。

        PowerShell:  $env:JIN10_DEV_TOKEN="sk-..."
        或       :  echo sk-... > tools\\_jin10_token.txt
    """
    t = (os.environ.get("JIN10_DEV_TOKEN") or "").strip()
    if t:
        return t
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_jin10_token.txt")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""
    return ""


TOKEN = _load_token()

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "Authorization": "Bearer " + TOKEN,
}

# 待探测的品种代码（金十的 code 与新浪不同，需实测确认）
PROBE_CODES = [
    "XAUUSD", "XAGUSD", "HG", "CL", "OIL",
    "NDX", "NAS100", "SPX", "SP500", "USDX", "DINIW",
    "USDCNH", "AU", "AG", "XAU", "XAG",
]

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
        # 关键：SSE 响应不带 charset，requests 会默认按 ISO-8859-1 解码 text/*，中文会乱码
        resp.encoding = "utf-8"
        ct = (resp.headers.get("content-type") or "").lower()
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

    def raw(self, method, params=None, timeout=30):
        """返回原始 (HTTP 状态码, 响应文本前 300 字)，用于排查「解析不出来」的情况。"""
        body = {"jsonrpc": "2.0", "method": method, "id": self._next_id()}
        if params is not None:
            body["params"] = params
        headers = dict(HEADERS)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        resp = self.session.post(BASE, headers=headers, json=body, timeout=timeout)
        resp.encoding = "utf-8"
        return resp.status_code, resp.text[:300]


if not TOKEN:
    print("未提供开发期金十 token。请设置环境变量 JIN10_DEV_TOKEN，"
          "或把 token 写进 tools/_jin10_token.txt（该文件不入库）。已退出。")
    sys.exit(2)

c = McpClient()

log("=== 1. initialize ===")
code, data = c.post("initialize", {
    "protocolVersion": PROTOCOL,
    "capabilities": {},
    "clientInfo": {"name": "jiangmen-jinlianghua", "version": "1.0.0"},
})
log("HTTP %s   session=%s" % (code, (c.session_id or "(无)")[:24]))
if data:
    res = data.get("result") or {}
    log("协议版本  : %s" % res.get("protocolVersion"))
    log("服务端信息: %s" % json.dumps(res.get("serverInfo"), ensure_ascii=False))
    log("能力      : %s" % json.dumps(res.get("capabilities"), ensure_ascii=False))

log("")
log("=== 2. notifications/initialized ===")
log("HTTP %s" % c.post("notifications/initialized", {}, notify=True)[0])

log("")
log("=== 3. tools/list（实测该服务端返回空，故客户端需硬编码工具名）===")
code, data = c.post("tools/list", {})
tools = ((data or {}).get("result") or {}).get("tools") or []
log("HTTP %s  工具数量: %d" % (code, len(tools)))
log("原始响应: %s" % json.dumps(data, ensure_ascii=False)[:300] if data else "(无返回)")

log("")
log("=== 4. resources/list ===")
code, data = c.post("resources/list", {})
res_list = ((data or {}).get("result") or {}).get("resources") or []
log("HTTP %s  资源数量: %d" % (code, len(res_list)))

log("")
log("=== 5. resources/read quote://codes ===")
code, raw = c.raw("resources/read", {"uri": "quote://codes"})
log("HTTP %s" % code)
log("原始: %s" % raw.replace("\n", " | ")[:300])


def call_tool(name, args, label="", wide=False):
    log("")
    log("--- tools/call %s %s ---" % (name, label))
    _, data = c.post("tools/call", {"name": name, "arguments": args})
    if data is None:
        log("  (解析不出返回体，见下方原始响应)")
        code, raw = c.raw("tools/call", {"name": name, "arguments": args})
        log("  HTTP %s 原始: %s" % (code, raw.replace("\n", " | ")[:300]))
        return
    if data.get("error"):
        log("  JSON-RPC 错误: %s" % json.dumps(data["error"], ensure_ascii=False)[:300])
        return
    result = data.get("result") or {}
    log("  isError: %s" % result.get("isError"))
    sc = result.get("structuredContent")
    if sc is not None:
        n = 1200 if wide else 500
        log("  structuredContent: %s" % json.dumps(sc, ensure_ascii=False)[:n])
    else:
        content = result.get("content") or []
        txt = content[0].get("text") if content else ""
        log("  (无 structuredContent) content[0]: %s" % (txt or "")[:300].replace("\n", " "))


# 逐个验证文档里列出的 8 个工具真实可用性
call_tool("get_quote", {"code": "XAUUSD"}, "(行情)")
call_tool("get_kline", {"code": "XAUUSD", "count": 3}, "(K线)")
call_tool("list_flash", {}, "(快讯列表)")
call_tool("search_flash", {"keyword": "黄金"}, "(快讯搜索)")
call_tool("list_news", {}, "(资讯列表)")
call_tool("search_news", {"keyword": "黄金"}, "(资讯搜索)")
call_tool("list_calendar", {}, "(财经日历)")

log("")
log("=== 6. 品种代码探测（逐个小额试探，确认支持哪些 code）===")
ok, bad = [], []
for code_ in PROBE_CODES:
    _, data = c.post("tools/call", {"name": "get_quote", "arguments": {"code": code_}})
    result = (data or {}).get("result") or {}
    sc = result.get("structuredContent") or {}
    d = sc.get("data")
    if d and d.get("name"):
        ok.append("%s -> %s  %s" % (code_, d.get("name"), d.get("close")))
    else:
        bad.append("%s -> %s" % (code_, (sc.get("message") or "")[:40]))
log("支持 %d 个：" % len(ok))
for line in ok:
    log("  " + line)
log("不支持 %d 个：" % len(bad))
for line in bad:
    log("  " + line)

with open("tools/_jin10_mcp.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("done")
