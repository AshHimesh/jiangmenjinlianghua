# -*- coding: utf-8 -*-
"""
江门金量化 · 相似问题缓存

用户问过的、或与历史问题高度相似的问题，直接返回上次答案：
- 省 API 费用、响应秒回
- 新问题才真正调用 AI，答完自动写入缓存

存储：项目根目录 cache.db（SQLite）
"""
import hashlib
import os
import re
import sqlite3
import threading
import time
from difflib import SequenceMatcher

from .paths import data_path

DB_PATH = data_path("cache.db")

TTL = 20 * 60          # 缓存有效期（秒），行情会变，不宜过长
SIM_THRESHOLD = 0.85   # 相似度阈值（0~1，越高越严格）
MAX_SCAN = 300         # 每次最多比对多少条历史记录
MIN_LEN = 4            # 过短的问题不参与模糊匹配

# 比较前先剔除的中文虚词（不影响语义，但会显著拉低相似度）
PARTICLES = "的了吗呢吧啊呀么嘛"

_lock = threading.Lock()
_conn = None


def _db():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.execute(
            """CREATE TABLE IF NOT EXISTS qa_cache (
                   id        INTEGER PRIMARY KEY AUTOINCREMENT,
                   norm_q    TEXT NOT NULL,
                   focus     TEXT,
                   signature TEXT NOT NULL,
                   question  TEXT,
                   answer    TEXT,
                   ts        REAL
               )"""
        )
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_lookup ON qa_cache(signature, focus)")
        _conn.commit()
    return _conn


def normalize(q):
    """问题归一化：统一小写、去空白与标点、剔除虚词。"""
    q = (q or "").lower()
    q = re.sub(r"[\s，。？！、,\.\?!;；:：\"'“”‘’（）()\[\]【】<>《》~\-—_]+", "", q)
    q = re.sub("[" + PARTICLES + "]+", "", q)
    return q


def similarity(a, b):
    """
    混合相似度：编辑比 + 包含度。
    包含度对"多加/少加几个字"很宽容，编辑比对"换词"更敏感，两者结合更贴合中文短句。
    """
    if not a or not b:
        return 0.0
    sm = SequenceMatcher(None, a, b)
    ratio = sm.ratio()
    lcs = sum(bl.size for bl in sm.get_matching_blocks())
    contain = lcs / min(len(a), len(b))
    return 0.6 * contain + 0.4 * ratio


def signature(model, active_skills):
    """模型 + 技能组合的指纹；任一变化则旧缓存不再命中。"""
    key = "%s||%s" % (model or "", ",".join(sorted(active_skills or [])))
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:12]


def lookup(question, focus, sig):
    """查找缓存。返回 {"answer":..., "question":..., "age":秒, "similarity":...} 或 None。"""
    norm = normalize(question)
    if not norm:
        return None
    now = time.time()
    try:
        with _lock:
            conn = _db()
            rows = conn.execute(
                """SELECT norm_q, question, answer, ts FROM qa_cache
                   WHERE signature = ? AND IFNULL(focus,'') = IFNULL(?,'')
                   ORDER BY ts DESC LIMIT ?""",
                (sig, focus, MAX_SCAN),
            ).fetchall()
    except Exception:
        return None

    best = None
    best_ratio = 0.0
    for r_norm, r_q, r_ans, r_ts in rows:
        if now - r_ts > TTL:
            continue
        if r_norm == norm:
            return {"answer": r_ans, "question": r_q, "age": int(now - r_ts),
                    "similarity": 1.0, "exact": True}
        if len(norm) < MIN_LEN or len(r_norm) < MIN_LEN:
            continue
        # 长度差太大直接跳过（省算力）
        if abs(len(norm) - len(r_norm)) / max(len(norm), len(r_norm)) > 0.5:
            continue
        score = similarity(norm, r_norm)
        if score > best_ratio:
            best_ratio, best = score, {"answer": r_ans, "question": r_q,
                                       "age": int(now - r_ts), "similarity": round(score, 3),
                                       "exact": False}
    if best and best_ratio >= SIM_THRESHOLD:
        return best
    return None


def store(question, focus, sig, answer):
    """写入缓存。"""
    norm = normalize(question)
    if not norm or not answer or not answer.strip():
        return
    try:
        with _lock:
            conn = _db()
            conn.execute(
                "INSERT INTO qa_cache (norm_q, focus, signature, question, answer, ts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (norm, focus, sig, question, answer.strip(), time.time()),
            )
            # 只保留最近 2000 条
            conn.execute(
                "DELETE FROM qa_cache WHERE id NOT IN "
                "(SELECT id FROM qa_cache ORDER BY ts DESC LIMIT 2000)"
            )
            conn.commit()
    except Exception:
        pass


def clear():
    """清空缓存。"""
    try:
        with _lock:
            conn = _db()
            conn.execute("DELETE FROM qa_cache")
            conn.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}


def stats():
    """缓存统计：条数、有效条数。"""
    try:
        with _lock:
            conn = _db()
            total = conn.execute("SELECT COUNT(*) FROM qa_cache").fetchone()[0]
            fresh = conn.execute("SELECT COUNT(*) FROM qa_cache WHERE ts > ?",
                                 (time.time() - TTL,)).fetchone()[0]
        return {"total": total, "fresh": fresh, "ttl_minutes": TTL // 60}
    except Exception:
        return {"total": 0, "fresh": 0, "ttl_minutes": TTL // 60}
