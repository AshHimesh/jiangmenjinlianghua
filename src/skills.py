# -*- coding: utf-8 -*-
"""
江门金量化 · Skill 技能管理

- 加载 `skills/` 目录下的 **.txt 与 .md** 文件作为 AI 分析技能模板。
- 默认**全部激活**；激活的 skill 全文会注入系统提示词，AI 必须遵循。
- 因为系统提示词是稳定前缀，可命中服务商（DeepSeek/OpenAI 等）的上下文缓存，成本很低。
"""
import os
import shutil

from .paths import data_path

# 技能目录放在「用户数据目录」（打包后即 exe 旁边，用户可自行增删技能文件）
SKILLS_DIR = data_path("skills")
SUPPORTED_EXT = (".txt", ".md")


def ensure_dir():
    os.makedirs(SKILLS_DIR, exist_ok=True)
    return SKILLS_DIR


def _safe_name(filename):
    """只接受纯文件名，防止路径穿越。"""
    return os.path.basename(str(filename or "").strip())


def _display_name(filename):
    """由文件名推导展示名：去掉扩展名与结尾的 skill 字样。"""
    base = os.path.splitext(filename)[0].strip()
    for suffix in ("skill", "Skill", "SKILL", "技能"):
        if base.endswith(suffix):
            base = base[:-len(suffix)]
    return base.strip(" -_") or os.path.splitext(filename)[0]


def list_skills():
    """列出 skills 目录下所有支持的技能文件。"""
    ensure_dir()
    out = []
    try:
        names = sorted(os.listdir(SKILLS_DIR))
    except OSError:
        return out
    for fn in names:
        if not fn.lower().endswith(SUPPORTED_EXT):
            continue
        path = os.path.join(SKILLS_DIR, fn)
        if not os.path.isfile(path):
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        out.append({
            "filename": fn,
            "name": _display_name(fn),
            "chars": size,
            "ext": os.path.splitext(fn)[1].lower().lstrip("."),
        })
    return out


def read_skill(filename):
    """读取技能文件全文。"""
    name = _safe_name(filename)
    if not name:
        return None
    path = os.path.join(SKILLS_DIR, name)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return None


def resolve_active(active):
    """把配置里的 active_skills 解析成实际生效的文件名列表（None = 全部）。"""
    alls = [s["filename"] for s in list_skills()]
    if not active:
        return alls
    wanted = {_safe_name(x) for x in active}
    return [f for f in alls if f in wanted]


def build_skill_prompt(active=None):
    """把激活的 skill 拼成一段文本，用于注入系统提示词。"""
    files = resolve_active(active)
    blocks = []
    for fn in files:
        text = read_skill(fn)
        if not text or not text.strip():
            continue
        blocks.append(
            "════════ 技能：%s（%s）════════\n%s" % (_display_name(fn), fn, text.strip())
        )
    return "\n\n".join(blocks)


def stats(active=None):
    """返回激活技能的数量与总字符数（用于界面提示 token 体量）。"""
    files = resolve_active(active)
    total = 0
    for fn in files:
        t = read_skill(fn) or ""
        total += len(t)
    return {"count": len(files), "chars": total}


def import_skill(src_path, overwrite=False):
    """把外部 .txt/.md 文件导入到 skills 目录。返回导入后的文件名。"""
    src_path = str(src_path or "").strip().strip('"')
    if not src_path or not os.path.isfile(src_path):
        return {"error": "文件不存在：%s" % src_path}
    ext = os.path.splitext(src_path)[1].lower()
    if ext not in SUPPORTED_EXT:
        return {"error": "只支持 .txt 和 .md 文件"}
    ensure_dir()
    dst = os.path.join(SKILLS_DIR, os.path.basename(src_path))
    if os.path.exists(dst) and not overwrite:
        return {"error": "同名技能已存在：%s" % os.path.basename(src_path)}
    try:
        shutil.copyfile(src_path, dst)
    except OSError as e:
        return {"error": "复制失败：%s" % e}
    return {"ok": True, "filename": os.path.basename(src_path)}
