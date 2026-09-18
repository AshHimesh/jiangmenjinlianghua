# -*- coding: utf-8 -*-
"""
江门金量化 · 标准 MCP 客户端

用于接入 MCP（Model Context Protocol）协议的数据服务，
当前用于金十数据：https://mcp.jin10.com/mcp

设计要点（均为实测踩过的坑，改动请勿破坏）
------------------------------------------
1. 握手顺序必须是
       initialize  ->  notifications/initialized  ->  之后才能 tools/call
   服务端在 initialize 的**响应头**里返回 Mcp-Session-Id，后续每个请求都要原样带回，
   否则服务端会当成新会话。

2. 响应可能是 SSE（Content-Type: text/event-stream），也可能是普通 JSON。
   SSE 不带 charset，requests 对 text/* 默认按 ISO-8859-1 解码，中文会全变乱码，
   因此这里**强制** resp.encoding = 'utf-8'，不能省。

3. 结果优先取 result.structuredContent（已经结构化的 dict），
   result.content 只是一段给模型看的可读文本，仅作补充。

4. 分页统一用 cursor：请求带 cursor，响应里读 data.next_cursor / data.has_more。

5. 本模块只负责协议本身，不含任何金十业务逻辑、不读配置、不记额度。
   业务层见 src/jin10.py。
"""

import json
import threading

import requests

# 协议版本（金十服务端 2026-09-18 实测返回 2025-11-25）
PROTOCOL_VERSION = "2025-11-25"

DEFAULT_BASE_URL = "https://mcp.jin10.com/mcp"

CLIENT_NAME = "jiangmen-jinlianghua"
CLIENT_VERSION = "1.0.0"

DEFAULT_TIMEOUT = 20


class McpError(Exception):
    """MCP 调用失败（网络、HTTP、JSON-RPC 错误统一抛这个）。"""

    def __init__(self, message, code=None, data=None):
        super().__init__(message)
        self.code = code
        self.data = data


class McpClient:
    """一个最小可用的 MCP 客户端（HTTP + SSE 传输）。"""

    def __init__(self, token, base_url=DEFAULT_BASE_URL, timeout=DEFAULT_TIMEOUT):
        token = (token or "").strip()
        if not token:
            raise McpError("未配置 API Key")
        self.token = token
        self.base_url = (base_url or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
        self.timeout = timeout

        self.session_id = None
        self.server_info = None
        self.protocol_version = None
        self.capabilities = None

        self._id = 0
        self._lock = threading.Lock()
        self._http = requests.Session()
        self._ready = False

    # ---------------- 底层 ----------------

    def _next_id(self):
        with self._lock:
            self._id += 1
            return self._id

    def _headers(self):
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer " + self.token,
        }
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    @staticmethod
    def _parse_response(resp):
        """把响应体解析成 dict：支持 SSE 和普通 JSON 两种。"""
        # 关键：SSE 不带 charset，不强制 utf-8 中文必乱码
        resp.encoding = "utf-8"
        ctype = (resp.headers.get("content-type") or "").lower()

        if "text/event-stream" in ctype:
            for line in resp.text.splitlines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload:
                    continue
                try:
                    return json.loads(payload)
                except ValueError:
                    continue
            return None

        if not resp.text.strip():
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    def _post(self, method, params=None, notify=False):
        """
        发一个 JSON-RPC 请求。

        :param notify: True 时发通知（不带 id），服务端通常返回 202 且无响应体
        :return: (http_status, parsed_json_or_None)
        """
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            body["id"] = self._next_id()

        try:
            resp = self._http.post(
                self.base_url, headers=self._headers(), json=body, timeout=self.timeout
            )
        except requests.RequestException as e:
            raise McpError("网络请求失败：%s" % e)

        # 会话头可能在任意一次响应里首次出现
        sid = resp.headers.get("Mcp-Session-Id")
        if sid:
            self.session_id = sid

        if notify:
            return resp.status_code, None

        data = self._parse_response(resp)

        if resp.status_code >= 400:
            msg = ""
            if isinstance(data, dict):
                msg = (data.get("error") or {}).get("message") or ""
            raise McpError(
                "HTTP %d%s" % (resp.status_code, ("：" + msg) if msg else ""),
                code=resp.status_code,
            )

        if data is None:
            raise McpError("服务端返回了无法解析的内容（HTTP %d）" % resp.status_code)

        err = data.get("error")
        if err:
            raise McpError(
                err.get("message") or "JSON-RPC 错误",
                code=err.get("code"),
                data=err.get("data"),
            )

        return resp.status_code, data

    def _result(self, method, params=None):
        """发请求并直接返回 result 部分。"""
        _, data = self._post(method, params)
        return (data or {}).get("result") or {}

    # ---------------- 握手 ----------------

    def initialize(self):
        """initialize + notifications/initialized；重复调用是幂等的。"""
        if self._ready:
            return self

        result = self._result(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            },
        )
        self.protocol_version = result.get("protocolVersion")
        self.server_info = result.get("serverInfo") or {}
        self.capabilities = result.get("capabilities") or {}

        # 通知：按协议必须在 initialize 之后发，服务端返回 202
        self._post("notifications/initialized", {}, notify=True)

        self._ready = True
        return self

    def ensure_ready(self):
        if not self._ready:
            self.initialize()
        return self

    # ---------------- 能力发现 ----------------

    def list_tools(self):
        """tools/list。注意：部分服务端此接口可能返回空，调用方需有静态兜底。"""
        self.ensure_ready()
        result = self._result("tools/list", {})
        return result.get("tools") or []

    def list_resources(self):
        """resources/list。"""
        self.ensure_ready()
        result = self._result("resources/list", {})
        return result.get("resources") or []

    def read_resource(self, uri):
        """resources/read，返回 contents 列表。"""
        self.ensure_ready()
        result = self._result("resources/read", {"uri": uri})
        return result.get("contents") or []

    def read_resource_json(self, uri):
        """读一个 JSON 资源并解析成对象（金十的 quote://codes 就是这种）。"""
        for item in self.read_resource(uri):
            text = item.get("text")
            if not text:
                continue
            try:
                return json.loads(text)
            except ValueError:
                continue
        return None

    # ---------------- 调用工具 ----------------

    def call_tool(self, name, arguments=None):
        """
        调用一个工具，返回统一结构：
            {
              "is_error": bool,
              "structured": dict|None,   # result.structuredContent
              "content": str,            # result.content 里的可读文本
              "raw": dict,               # 完整 result，排查用
            }
        """
        self.ensure_ready()
        result = self._result(
            "tools/call", {"name": name, "arguments": arguments or {}}
        )

        # content 是一组 [{type, text}]，拼出可读文本
        texts = []
        for item in result.get("content") or []:
            if isinstance(item, dict) and item.get("text"):
                texts.append(item["text"])

        return {
            "is_error": bool(result.get("isError")),
            "structured": result.get("structuredContent"),
            "content": "\n".join(texts),
            "raw": result,
        }

    def call_tool_data(self, name, arguments=None):
        """
        调用工具并直接返回业务数据（structuredContent.data）。

        服务端约定：structuredContent = {"data": ..., "message": ..., "status": 200}
        出错时 data 为空、message 是中文说明，这里直接抛成 McpError，调用方不必判空。
        """
        out = self.call_tool(name, arguments)
        sc = out.get("structured") or {}
        status = sc.get("status")
        data = sc.get("data")
        message = sc.get("message") or ""

        if out["is_error"] or (status not in (None, 200)) or data is None:
            raise McpError(message or ("工具 %s 调用失败" % name), code=status)
        return data

    def close(self):
        try:
            self._http.close()
        except Exception:
            pass


def probe(token, base_url=DEFAULT_BASE_URL, timeout=DEFAULT_TIMEOUT):
    """
    连通性自检：握手 + 拉一次工具清单 + 读一次 codes 资源。

    :return: dict(name, title, version, protocol, tools, resources, codes_count, error)
    """
    info = {
        "ok": False,
        "name": "",
        "title": "",
        "version": "",
        "protocol": "",
        "tools": [],
        "resources": [],
        "codes_count": 0,
        "error": "",
    }
    client = None
    try:
        client = McpClient(token, base_url, timeout)
        client.initialize()
        si = client.server_info or {}
        info["name"] = si.get("name") or ""
        info["title"] = si.get("title") or ""
        info["version"] = si.get("version") or ""
        info["protocol"] = client.protocol_version or ""

        try:
            info["tools"] = [t.get("name") for t in client.list_tools() if t.get("name")]
        except McpError:
            info["tools"] = []
        try:
            info["resources"] = [r.get("uri") for r in client.list_resources()]
        except McpError:
            info["resources"] = []
        try:
            codes = client.read_resource_json("quote://codes")
            if isinstance(codes, dict):
                codes = codes.get("data") or []
            info["codes_count"] = len(codes) if isinstance(codes, list) else 0
        except McpError:
            info["codes_count"] = 0

        info["ok"] = True
    except McpError as e:
        info["error"] = str(e)
    except Exception as e:  # 兜底，自检绝不能让主程序崩
        info["error"] = "%s: %s" % (type(e).__name__, e)
    finally:
        if client is not None:
            client.close()
    return info
