# -*- coding: utf-8 -*-
"""
江门金量化 · 报告导出（阶段 9）

把一次 AI 回答整理成**可复制 / 可导出**的分析报告，落到 exe 旁边的 reports/ 目录。
两种格式都给（需求 5.3.3 的「Markdown + PNG」与「自包含 HTML」二选一，这里直接两个都出）：
  - .md   —— 便于二次编辑、贴进笔记；图片用同目录相对路径引用
  - .html —— 图片 base64 内嵌，单文件双击即看，可浏览器打印成 PDF

报告头部自动附元信息（需求 5.3.1）：生成时间、品种、当前价、各周期数据时间戳、
启用的 skill、模型、数据来源。
"""
import base64
import html as _html
import os
from datetime import datetime

from .kline import PERIOD_NAME, get_kline
from .paths import data_path
from .symbols import periods_of


def reports_dir():
    d = data_path("reports")
    os.makedirs(d, exist_ok=True)
    return d


def _fmt_num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "-"
    if abs(f - int(f)) < 1e-9:
        return "%d" % int(f)
    return ("%.4f" % f).rstrip("0").rstrip(".")


def kline_stamps(symbol):
    """该品种各周期最新一根K线的时间，作为报告的「数据时间戳」。"""
    out = []
    for p in periods_of(symbol):
        try:
            df = get_kline(symbol, p)
        except Exception:
            df = None
        if df is None or len(df) == 0:
            continue
        d = df.iloc[-1]["datetime"]
        text = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
        out.append("%s %s" % (PERIOD_NAME.get(p, p), text))
    return out


def source_of(name):
    from .fetcher import _source_of
    return _source_of(name)


def export(symbol, question, answer, charts=None, model="", skills=None,
           quotes=None, focus=None):
    """
    导出一份报告。

    :param charts: 本轮回答生成的图表 PNG 绝对路径列表
    :return: dict(ok, md, html, pngs, error)
    """
    try:
        symbol = (symbol or "").strip() or "未指定品种"
        answer = (answer or "").strip()
        question = (question or "").strip()
        charts = [c for c in (charts or []) if c and os.path.exists(c)]
        if not answer:
            return {"ok": False, "error": "还没有可导出的回答。"}

        quotes = quotes or {}
        q = quotes.get(symbol) or {}
        price = q.get("price")
        change = q.get("change")
        unit = ""
        from .symbols import SYMBOL_MAP
        if symbol in SYMBOL_MAP:
            unit = SYMBOL_MAP[symbol].get("unit", "")

        if price is not None:
            sign = "+" if (change or 0) >= 0 else ""
            price_text = "%s %s（%s%.2f%%）" % (_fmt_num(price), unit, sign, float(change or 0))
        else:
            price_text = "暂无数据"

        meta = [
            ("生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            ("品种", symbol),
            ("当前价", price_text),
            ("数据来源", source_of(symbol)),
            ("数据时间戳", "；".join(kline_stamps(symbol)) or "—"),
            ("启用技能", "、".join(skills or []) or "无"),
            ("模型", model or "—"),
            ("风险提示", _RISK_NOTE()),
        ]

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        base = "%s-%s" % (stamp, _safe(symbol))
        md_path = os.path.join(reports_dir(), base + ".md")
        html_path = os.path.join(reports_dir(), base + ".html")

        _write_markdown(md_path, symbol, question, answer, charts, meta)
        _write_html(html_path, symbol, question, answer, charts, meta)

        return {"ok": True, "md": md_path, "html": html_path, "pngs": charts,
                "dir": reports_dir()}
    except Exception as e:
        return {"ok": False, "error": "导出报告失败：%s: %s" % (type(e).__name__, e)}


def symbols_iter():
    from .symbols import SYMBOL_MAP
    return SYMBOL_MAP.values()


def _safe(name):
    return "".join(c if c not in '\\/:*?"<>|' else "_" for c in name).strip()


def _RISK_NOTE():
    return "本报告由 AI 依据公开行情生成，仅供参考，不构成投资建议。"


def _meta_rows(meta):
    rows = []
    for k, v in meta:
        rows.append("| %s | %s |" % (k, v))
    return "\n".join(rows)


def _write_markdown(path, symbol, question, answer, charts, meta):
    parts = ["# 江门金量化 · 分析报告", ""]
    parts.append("| 项目 | 内容 |")
    parts.append("| --- | --- |")
    parts.append(_meta_rows(meta))
    parts += ["", "## 我的问题", "", question or "（未记录）", "",
              "## 分析结论", "", answer, ""]
    if charts:
        parts += ["## 图表", ""]
        for p in charts:
            name = os.path.basename(p)
            parts.append("![%s](%s)" % (name, name))
        parts.append("")
    parts += ["---", "",
              "*%s ｜ 报告文件：`%s`*" % (_RISK_NOTE(), os.path.basename(path))]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))


def _img_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _write_html(path, symbol, question, answer, charts, meta):
    rows = "".join(
        "<tr><td>%s</td><td>%s</td></tr>" % (_html.escape(str(k)), _html.escape(str(v)))
        for k, v in meta)

    imgs = "".join(
        '<figure><img src="data:image/png;base64,%s" alt="%s"><figcaption>%s</figcaption></figure>'
        % (_img_b64(p), _html.escape(os.path.basename(p)), _html.escape(os.path.basename(p)))
        for p in charts)

    tpl = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>江门金量化 · 分析报告 · {sym}</title>
<style>
  body {{ font-family: "Segoe UI", "Microsoft YaHei", sans-serif; color: #1A1A1A;
         max-width: 880px; margin: 32px auto; padding: 0 20px; line-height: 1.75; }}
  h1 {{ font-size: 21px; border-bottom: 2px solid #EBEBEB; padding-bottom: 10px; }}
  h2 {{ font-size: 15px; margin-top: 28px; color: #1A1A1A; }}
  table {{ border-collapse: collapse; font-size: 13px; width: 100%; }}
  td, th {{ border: 1px solid #EBEBEB; padding: 6px 10px; vertical-align: top; }}
  td:first-child {{ color: #8A8A8A; background: #F7F8FA; white-space: nowrap; width: 110px; }}
  .q {{ background: #F7F8FA; border: 1px solid #EBEBEB; border-radius: 8px;
       padding: 12px 14px; font-size: 14px; }}
  .a {{ background: #FFFFFF; border: 1px solid #EBEBEB; border-radius: 8px;
       padding: 16px; font-size: 14px; white-space: pre-wrap; word-break: break-word; }}
  figure {{ margin: 16px 0; }}
  img {{ max-width: 100%; border: 1px solid #EBEBEB; border-radius: 8px; }}
  figcaption {{ font-size: 12px; color: #8A8A8A; margin-top: 6px; }}
  .foot {{ margin-top: 28px; font-size: 12px; color: #8A8A8A; }}
  @media print {{ body {{ margin: 0; }} .a {{ white-space: pre-wrap; }} }}
</style>
</head>
<body>
<h1>江门金量化 · 分析报告（{sym}）</h1>
<table>{rows}</table>
<h2>我的问题</h2>
<div class="q">{q}</div>
<h2>分析结论</h2>
<div class="a">{a}</div>
<h2>图表</h2>
{imgs}
<p class="foot">提示：本页为自包含 HTML，图片已内嵌，可离线查看或直接打印成 PDF。</p>
</body>
</html>
"""
    content = tpl.format(
        sym=_html.escape(symbol),
        rows=rows,
        q=_html.escape(question or "（未记录）"),
        a=_html.escape(answer),
        imgs=imgs or '<p class="foot">本轮未生成图表。</p>',
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def list_reports(limit=30):
    """最近的报告文件（给界面列出用）。"""
    d = reports_dir()
    files = [os.path.join(d, n) for n in os.listdir(d)
             if n.lower().endswith((".md", ".html", ".png"))]
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return [{"path": p, "name": os.path.basename(p),
             "mtime": datetime.fromtimestamp(os.path.getmtime(p)).strftime("%m-%d %H:%M")}
            for p in files[:limit]]


def open_reports_dir():
    """用资源管理器打开 reports 目录（Windows）。"""
    d = reports_dir()
    try:
        os.startfile(d)          # noqa: S606  Windows 专属，仅本机使用
        return {"ok": True, "dir": d}
    except Exception as e:
        return {"ok": False, "error": "打开目录失败：%s" % e}


def open_report(path):
    """用系统默认程序打开单个报告文件。仅允许打开 reports/ 目录里的文件。"""
    try:
        path = os.path.abspath(path)
        root = os.path.abspath(reports_dir())
        if not path.startswith(root):
            return {"ok": False, "error": "只允许打开 reports 目录里的文件。"}
        if not os.path.exists(path):
            return {"ok": False, "error": "文件不存在：%s" % os.path.basename(path)}
        os.startfile(path)       # noqa: S606  Windows 专属，仅本机使用
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": "打开失败：%s" % e}
