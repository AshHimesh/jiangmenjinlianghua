# -*- coding: utf-8 -*-
"""
江门金量化 · 对话会话

- 维护多轮对话历史
- 每次提问自动附带实时行情快照（可在设置中关闭）
- 后台线程流式接收，前端轮询读取（思考过程 + 正文分开累积）
"""
import threading
import time

from .ai import AIError, ToolsUnsupportedError, stream_completion
from .analysis import build_reports, detect_symbols
from . import qacache
from .skills import build_skill_prompt
from .symbols import GROUPS
from .tools import TOOL_SCHEMAS, execute as tool_execute, summarize_call

# 记录哪些模型不支持函数调用，避免每次都白试一轮
_TOOLS_UNSUPPORTED = set()

# 最多保留的历史消息条数（防止无限增长）
MAX_HISTORY = 20

SYSTEM_PROMPT = """你是「江门金量化」内置的行情分析助手，服务于关注多市场联动的中文投资者。

用户关注这些品种：现货黄金、现货白银、铜、WTI原油、纳斯达克100、标普500、美元指数、螺纹钢、焦煤、甲醇、乙二醇、纯碱、科创50、上证指数。

你会收到两类数据：
1.【实时行情快照】—— 全部品种的最新价与涨跌幅。
2.【多周期技术面】—— 相关品种各周期的均线、MACD、RSI、KDJ、布林带、斐波那契回撤、近期结构高低点。

分析要求：
1. 只依据给出的数据说话，绝不编造价格或指标数字；数据缺失就如实说「暂无该周期数据」。
2. 【周期权重】从高到低：周线 > 日线 > 12小时 > 4小时 > 1小时 > 15分钟 > 5分钟。
   - 大周期定方向，小周期找时机；判断趋势必须先看靠前的大周期。
   - 多周期方向一致时可靠性更高（共振）；若大小周期冲突，以大周期为准，小周期视为回调或反弹。
3. 综合运用指标：均线排列与价格相对位置、MACD 金叉死叉与柱体变化、RSI 超买超卖、KDJ 位置、
   布林带开口与价格所处位置、斐波那契回撤位、近期结构的高低点。
4. 明确给出**关键支撑位与阻力位**（用具体数字），并说明依据。
5. 回答简洁、条理清晰，用短段落或要点列表，避免长篇大论。
6. 涉及操作建议时必须提示风险，不做任何收益承诺。
7. 一律使用简体中文回答。"""

# 工具能力说明（仅在启用工具时附加）
TOOL_HINT = """
【你可以主动读取数据】
除了上面给出的行情快照与技术面摘要，你还**可以调用工具按需获取更多数据**：
- `get_kline`：读取任意品种、任意周期的原始K线（含精确历史价位，最多 120 根）
- `get_indicators`：读取任意品种、任意周期的完整技术指标
- `list_symbols`：查询品种清单与各自支持的周期

使用原则：
1. 上述【多周期技术面】已覆盖的品种与周期，直接用给定数据，**不必重复读取**。
2. 当需要分析的品种/周期**不在**已有数据中、或需要精确历史价位、逐根K线形态、
   跳空缺口、更长的历史时，**主动调用工具**去取，不要凭猜测作答。
3. 需要多个品种或多个周期时，可以在一次回答里连续调用多次工具。
4. 工具返回「暂无数据」时，如实告知用户该周期不可用，不要编造。
"""

# 技能注入说明（放在 skill 全文之前）
SKILL_HEADER = """
════════════════════════════════════════
【必须遵循的分析技能 Skill】
以下是用户启用的分析技能。**你必须完整、认真地阅读全文，并严格按其角色定位、
分析框架、执行步骤和输出格式来回答**——这不是参考资料，而是你本次回答必须遵守的工作规程。
技能中的评分表、检查清单、输出模板，都要逐项落实到你的回答里。
════════════════════════════════════════
"""


def build_system_prompt(cfg):
    """系统提示词 = 基础人设 + 工具说明 + 用户启用的 Skill 全文（稳定前缀，可命中服务商缓存）。"""
    base = SYSTEM_PROMPT
    cfg = cfg or {}
    if cfg.get("enable_tools"):
        base += "\n" + TOOL_HINT
    try:
        skill_text = build_skill_prompt(cfg.get("active_skills"))
    except Exception:
        skill_text = ""
    if skill_text:
        base += "\n" + SKILL_HEADER + "\n" + skill_text
    return base


def build_market_snapshot(quotes, focus=None):
    """把当前行情整理成一段文本，供 AI 参考。"""
    lines = []
    for g in GROUPS:
        for it in g["items"]:
            name = it["name"]
            q = quotes.get(name) if quotes else None
            if q and q.get("price") is not None:
                sign = "+" if float(q.get("change") or 0) >= 0 else ""
                mark = "  ←用户正在查看" if name == focus else ""
                lines.append("- %s：%s %s（%s%.2f%%）%s" % (
                    name, q["price"], it["unit"], sign, float(q.get("change") or 0), mark))
            else:
                lines.append("- %s：暂无数据" % name)
    return "\n".join(lines)


class ChatSession:
    def __init__(self):
        self.history = []          # [{"role": "user"/"assistant", "content": str}]
        self._lock = threading.Lock()
        self._state = None         # 当前流式状态
        self._seq = 0

    # ---------- 提问 ----------
    def ask(self, question, cfg, quotes, focus=None, force=False):
        question = (question or "").strip()
        if not question:
            return {"error": "请输入问题"}
        cfg = dict(cfg or {})

        with self._lock:
            if self._state is not None and not self._state["done"]:
                return {"error": "上一条还在回答中，请稍候"}

        # ---------- 1) 先查相似问题缓存（force=True 时跳过）----------
        sig = qacache.signature(cfg.get("model"), cfg.get("active_skills"))
        hit = None
        if not force:
            try:
                hit = qacache.lookup(question, focus, sig)
            except Exception:
                hit = None

        with self._lock:
            self._seq += 1
            req_id = "req-%d" % self._seq

            if hit:
                # 命中缓存：直接返回上次答案，不调用 AI
                self._state = {
                    "id": req_id,
                    "thinking": "",
                    "content": hit["answer"],
                    "thinking_done": True,
                    "thinking_seconds": 0.0,
                    "done": True,
                    "error": None,
                    "cached": True,
                    "cache_age": hit.get("age"),
                    "cache_similarity": hit.get("similarity"),
                    "tools": [],
                }
                self.history.append({"role": "user", "content": question})
                self.history.append({"role": "assistant", "content": hit["answer"]})
                return {"id": req_id, "cached": True}

            self._state = {
                "id": req_id,
                "thinking": "",
                "content": "",
                "thinking_done": False,
                "thinking_seconds": 0.0,
                "done": False,
                "error": None,
                "cached": False,
                "tools": [],
            }

        # ---------- 2) 未命中：调用 AI ----------
        t = threading.Thread(
            target=self._run,
            args=(req_id, question, cfg, quotes or {}, focus, sig),
            daemon=True,
        )
        t.start()
        return {"id": req_id, "cached": False}

    def _run(self, req_id, question, cfg, quotes, focus, sig=None):
        messages = [{"role": "system", "content": build_system_prompt(cfg)}]
        messages.extend(self.history[-MAX_HISTORY:])

        user_content = question
        if cfg.get("inject_market", True) and quotes:
            blocks = ["【实时行情快照】\n" + build_market_snapshot(quotes, focus)]

            # 多周期技术面：当前品种 + 问题中提到的品种
            try:
                names = detect_symbols(question, focus)
                report = build_reports(names)
                if report:
                    blocks.append(report)
            except Exception as e:
                blocks.append("（技术面数据获取失败：%s）" % e)

            blocks.append("【我的问题】\n" + question)
            user_content = "\n\n".join(blocks)
        messages.append({"role": "user", "content": user_content})

        started = time.time()
        answer_parts = []

        def on_delta(delta):
            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
            content = delta.get("content")
            with self._lock:
                if self._state is None or self._state["id"] != req_id:
                    return
                if reasoning:
                    self._state["thinking"] += reasoning
                if content:
                    if not self._state["thinking_done"]:
                        self._state["thinking_done"] = True
                        self._state["thinking_seconds"] = round(time.time() - started, 1)
                    self._state["content"] += content
                    answer_parts.append(content)

        try:
            model = cfg.get("model", "")
            use_tools = bool(cfg.get("enable_tools")) and model not in _TOOLS_UNSUPPORTED

            def on_tool(event, name, args, result):
                with self._lock:
                    if self._state is None or self._state["id"] != req_id:
                        return
                    items = self._state["tools"]
                    if event == "start":
                        items.append({"label": summarize_call(name, args), "status": "running"})
                    else:
                        for it in reversed(items):
                            if it["status"] == "running":
                                it["status"] = "done"
                                break

            def _run_stream(use_tool_schemas):
                return stream_completion(
                    cfg.get("base_url", ""), cfg.get("api_key", ""), model, messages, on_delta,
                    tools=TOOL_SCHEMAS if use_tool_schemas else None,
                    tool_executor=tool_execute if use_tool_schemas else None,
                    on_tool=on_tool if use_tool_schemas else None,
                )

            if use_tools:
                try:
                    _run_stream(True)
                except ToolsUnsupportedError:
                    # 模型不支持函数调用：记住并降级为纯文本模式重试一次
                    _TOOLS_UNSUPPORTED.add(model)
                    with self._lock:
                        if self._state is not None and self._state["id"] == req_id:
                            self._state["thinking"] = ""
                            self._state["content"] = ""
                            self._state["tools"] = []
                    answer_parts.clear()
                    _run_stream(False)
            else:
                _run_stream(False)

            answer = "".join(answer_parts).strip()
            if answer:
                with self._lock:
                    self.history.append({"role": "user", "content": question})
                    self.history.append({"role": "assistant", "content": answer})
                # 写入相似问题缓存
                try:
                    qacache.store(question, focus, sig, answer)
                except Exception:
                    pass
        except AIError as e:
            with self._lock:
                if self._state is not None and self._state["id"] == req_id:
                    self._state["error"] = str(e)
        except Exception as e:  # 兜底，避免线程静默退出
            with self._lock:
                if self._state is not None and self._state["id"] == req_id:
                    self._state["error"] = "发生未知错误：%s" % e
        finally:
            with self._lock:
                if self._state is not None and self._state["id"] == req_id:
                    self._state["done"] = True

    # ---------- 轮询 ----------
    def get_stream(self, req_id=None):
        with self._lock:
            if self._state is None:
                return {"id": None, "thinking": "", "content": "",
                        "thinking_done": False, "thinking_seconds": 0.0,
                        "done": True, "error": None}
            if req_id and self._state["id"] != req_id:
                # 请求已过期（用户已开始新一轮）
                return dict(self._state)
            return dict(self._state)

    def clear(self):
        with self._lock:
            self.history = []
            self._state = None
        return {"ok": True}
