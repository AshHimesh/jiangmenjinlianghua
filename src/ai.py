# -*- coding: utf-8 -*-
"""
江门金量化 · AI 调用

直连任意 OpenAI 兼容接口的 /chat/completions，流式(SSE)返回。
- 自动识别思考过程字段：reasoning_content（DeepSeek / 智谱 / 千问 等）
- 支持 Function Calling：自动累积流式下发的 tool_calls 并循环执行，直到模型给出最终答案
"""
import json

import requests


class AIError(Exception):
    """AI 调用相关的可读错误。"""


class ToolsUnsupportedError(AIError):
    """当前模型/接口不支持函数调用，调用方可降级为纯文本模式重试。"""


# 判定"不支持工具"的关键词
_UNSUPPORTED_HINTS = ("tool", "function", "tools", "functions", "tool_choice")


def _build_payload(model, messages, stream=True, tools=None):
    payload = {"model": model, "messages": messages, "stream": stream}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return payload


def _post(base_url, api_key, payload, timeout):
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, stream=True, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise AIError("网络连接失败：%s" % e)

    if resp.status_code != 200:
        detail = ""
        try:
            detail = resp.text[:600]
        except Exception:
            pass
        resp.close()
        if resp.status_code in (401, 403):
            raise AIError("认证失败（HTTP %s），请检查 API Key 是否正确" % resp.status_code)
        low = detail.lower()
        if payload.get("tools") and any(h in low for h in _UNSUPPORTED_HINTS):
            raise ToolsUnsupportedError("该模型不支持函数调用：%s" % detail[:200])
        raise AIError("接口返回错误 HTTP %s：%s" % (resp.status_code, detail))
    resp.encoding = "utf-8"
    return resp


def _iter_deltas(resp):
    """逐行解析 SSE，产出每个 delta 字典。"""
    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        line = line.strip()
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            obj = json.loads(data)
        except ValueError:
            continue
        choices = obj.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        if delta:
            yield delta


def _accumulate_tool_calls(slot_map, delta):
    """把流式分片的 tool_calls 按 index 拼装完整。"""
    for tc in delta.get("tool_calls") or []:
        try:
            idx = int(tc.get("index", 0))
        except (TypeError, ValueError):
            idx = 0
        slot = slot_map.setdefault(idx, {"id": "", "name": "", "arguments": ""})
        if tc.get("id"):
            slot["id"] = tc["id"]
        fn = tc.get("function") or {}
        if fn.get("name"):
            slot["name"] += fn["name"]
        if fn.get("arguments"):
            slot["arguments"] += fn["arguments"]


def stream_completion(base_url, api_key, model, messages, on_delta,
                      tools=None, tool_executor=None, on_tool=None,
                      timeout=180, max_rounds=6):
    """
    流式调用对话接口，并在需要时自动执行函数调用。

    :param on_delta: 回调，收到正文/思考增量时调用，参数为 delta 字典
                     （可能含 "content" 或 "reasoning_content"）
    :param tools: 工具定义列表；为空则退化为普通对话
    :param tool_executor: callable(name, arguments) -> str，执行工具
    :param on_tool: callable(event, name, arguments, result)，用于界面展示工具进度
    :param max_rounds: 最多几轮工具调用，防止死循环
    """
    if not base_url:
        raise AIError("未配置接口地址（Base URL），请点右上角 ⚙ 设置")
    if not api_key:
        raise AIError("未配置 API Key，请点右上角 ⚙ 设置")
    if not model:
        raise AIError("未配置模型名称，请点右上角 ⚙ 设置")

    use_tools = bool(tools and tool_executor)

    for _round in range(max_rounds):
        payload = _build_payload(model, messages, tools=tools if use_tools else None)
        resp = _post(base_url, api_key, payload, timeout)

        slots = {}
        round_text = []
        try:
            for delta in _iter_deltas(resp):
                on_delta(delta)
                if delta.get("content"):
                    round_text.append(delta["content"])
                if use_tools and delta.get("tool_calls"):
                    _accumulate_tool_calls(slots, delta)
        finally:
            resp.close()

        if not slots:
            return  # 没有工具调用，本轮即最终答案

        # ---- 有工具调用：先记录 assistant 的 tool_calls，再逐个执行 ----
        ordered = [slots[k] for k in sorted(slots)]
        call_list = []
        for i, tc in enumerate(ordered):
            call_list.append({
                "id": tc["id"] or ("call_%d" % i),
                "type": "function",
                "function": {"name": tc["name"], "arguments": tc["arguments"] or "{}"},
            })
        messages.append({
            "role": "assistant",
            "content": "".join(round_text) or None,
            "tool_calls": call_list,
        })

        for call in call_list:
            name = call["function"]["name"]
            args = call["function"]["arguments"]
            if on_tool:
                on_tool("start", name, args, None)
            try:
                result = tool_executor(name, args)
            except Exception as e:
                result = "工具执行失败：%r" % e
            if on_tool:
                on_tool("done", name, args, result)
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": str(result),
            })

    # 轮数用尽
    raise AIError("工具调用轮数超出上限（%d），已停止。请把问题问得更具体一些。" % max_rounds)
