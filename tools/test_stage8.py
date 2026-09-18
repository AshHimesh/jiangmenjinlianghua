# -*- coding: utf-8 -*-
"""
阶段 8 自测：品种扩充后的实时行情 / K线可用性 + 别名识别 + 慢速源隔离

    .venv\\Scripts\\python.exe tools\\test_stage8.py

结果写 tools/_stage8_result.txt（UTF-8），**不要**用 shell 管道接输出。

覆盖两类断言（这是「不可得的如实标注」的机器化保证）：
  1. 声明支持的周期 → 必须真能取到（防虚报）
  2. 声明不支持的周期 → 必须真取不到（防漏报/谎报，漏报更危险）
"""
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OUT = []
PASS, FAIL = [], []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    log("  %s %s%s" % ("✅" if cond else "❌", name, ("  —— " + extra) if extra else ""))


def run(fn, label):
    log("")
    log("=" * 64)
    log(label)
    log("=" * 64)
    try:
        fn()
    except Exception:
        FAIL.append(label + " 抛异常")
        log("❌ 本节异常：")
        log(traceback.format_exc())


# ==================== A. 结构一致性（离线）====================

def t_structure():
    from src import fetcher
    from src.symbols import GROUPS, SYMBOL_MAP
    from src.tools import PERIODS_BY_SOURCE, available_periods
    from src.kline import PERIODS

    log("  品种总数：%d，分组：%s" % (len(SYMBOL_MAP), [g["name"] for g in GROUPS]))
    check("品种数在 22~25（需求 5.2.3 上限附近）", 22 <= len(SYMBOL_MAP) <= 25,
          "%d 个" % len(SYMBOL_MAP))

    # 每个 source 都要有：实时抓取函数 + K线周期声明
    srcs = sorted({it["source"] for it in SYMBOL_MAP.values()})
    log("  用到的数据源：%s" % srcs)
    missing_periods = [s for s in srcs if s not in PERIODS_BY_SOURCE]
    check("每个数据源都有周期声明", not missing_periods, str(missing_periods))

    # 实时抓取：每个 source 必须有对应 fetch_* 分支
    fetch_fns = {
        "sina_index": "fetch_sina_index", "sina_futures": "fetch_sina_futures",
        "sina_global": "fetch_sina_global", "sina_foreign": "fetch_sina_foreign",
        "sina_hk": "fetch_sina_hk", "sina_fx": "fetch_sina_fx", "sge": "fetch_sge",
    }
    missing_fetch = [s for s in srcs if not hasattr(fetcher, fetch_fns.get(s, ""))]
    check("每个数据源都有实时抓取函数", not missing_fetch, str(missing_fetch))

    # 周期声明必须都是合法周期
    bad = {s: [p for p in ps if p not in PERIODS] for s, ps in PERIODS_BY_SOURCE.items()}
    bad = {k: v for k, v in bad.items() if v}
    check("周期声明都是合法周期", not bad, str(bad))

    # 每个品种都能算出一组可用周期
    empty = [n for n in SYMBOL_MAP if not available_periods(n)]
    check("每个品种都能解析出可用周期", not empty, str(empty))

    # 新增品种必须在别名表里（否则 detect_symbols 只能靠品种名本身命中）
    from src.analysis import ALIASES
    no_alias = [n for n in SYMBOL_MAP if n not in ALIASES]
    check("每个品种都有别名表", not no_alias, str(no_alias))

    # 慢速源声明
    check("上金所被声明为慢速源（不进 2 秒循环）", "sge" in srcs and fetcher.SLOW_INTERVAL >= 30,
          "SLOW_INTERVAL=%s" % fetcher.SLOW_INTERVAL)


# ==================== B. 别名识别（离线，防短别名抢长别名）====================

def t_aliases():
    from src.analysis import detect_symbols

    cases = [
        ("黄金ETF 现在能买吗", "黄金ETF"),
        ("布伦特原油和WTI的价差", "布伦特原油"),
        ("美元兑离岸人民币走势", "美元兑离岸人民币"),
        ("美元指数怎么看", "美元指数"),
        ("沪金主力支撑位", "沪金AU"),
        ("沪银怎么样", "沪银AG"),
        ("上海金基准价多少", "上海金"),
        ("沪深300估值", "沪深300"),
        ("创业板指跌了没", "创业板指"),
        ("恒生指数今天如何", "恒生指数"),
        ("铁矿石和螺纹钢的关系", "铁矿石"),
        ("玻璃纯碱价差", "玻璃"),
    ]
    for q, want in cases:
        got = detect_symbols(q, None, limit=1)
        check("识别「%s」→ %s" % (q, want), got[:1] == [want], "实际 %s" % got)

    # focus 永远排第一
    got = detect_symbols("螺纹钢怎么样", "现货黄金", limit=1)
    check("focus 优先于问题里提到的品种", got[:1] == ["现货黄金"], "实际 %s" % got)


# ==================== C. 实时行情（联网）====================

def t_realtime():
    from src import fetcher
    from src.symbols import SYMBOL_MAP

    quotes = fetcher.fetch_all(slow=True)
    ok = [n for n in SYMBOL_MAP if quotes.get(n)]
    bad = [n for n in SYMBOL_MAP if not quotes.get(n)]
    check("全部品种都能取到实时价", not bad, "失败：%s" % bad)

    log("")
    log("  实时行情明细（价格 / 涨跌幅% / 来源）：")
    for n in SYMBOL_MAP:
        q = quotes.get(n)
        if q:
            log("    %-12s %-12s %-8s %s" % (n, q["price"], q["change"], fetcher._source_of(n)))
        else:
            log("    %-12s ❌ 无数据" % n)

    # 上海金必须标注为交易所来源，不能混成新浪
    check("上海金来源标注为上金所", quotes.get("上海金") and
          fetcher._source_of("上海金") == "上海黄金交易所",
          fetcher._source_of("上海金"))

    # 慢速源不参与快速轮
    fast = fetcher.fetch_all(slow=False)
    check("快速轮（slow=False）不含慢速源品种", "上海金" not in fast,
          "含上海金" if "上海金" in fast else "不含")


# ==================== D. K线与周期矩阵（联网）====================

def t_kline_matrix():
    from src.kline import get_kline
    from src.symbols import SYMBOL_MAP
    from src.tools import PERIODS_BY_SOURCE

    # 声明支持的周期里，抽样验证「真能取到」
    def one(name, period):
        try:
            df = get_kline(name, period)
            return name, period, None if df is None else len(df)
        except Exception as e:
            return name, period, "异常 %r" % e

    jobs = []
    for name, it in SYMBOL_MAP.items():
        ps = PERIODS_BY_SOURCE.get(it["source"], [])
        for p in ps:
            jobs.append((name, p))

    log("  并发拉取 %d 组（品种 × 声明周期）…" % len(jobs))
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda a: one(*a), jobs))

    # 日线/周线必须全部可用；分钟线只要求「多数可用」（外盘分钟仅当日、非交易时段可能为空）
    hard = [(n, p, c) for n, p, c in results if p in ("W", "D")]
    bad_hard = [(n, p, c) for n, p, c in hard if not isinstance(c, int) or c < 5]
    check("声明支持的 周线/日线 全部可取到（≥5 根）", not bad_hard, str(bad_hard[:6]))

    soft = [(n, p, c) for n, p, c in results if p not in ("W", "D")]
    ok_soft = [1 for _n, _p, c in soft if isinstance(c, int) and c >= 5]
    ratio = len(ok_soft) / len(soft) if soft else 1.0
    check("分钟线大体可用（能取到 ≥70%）", ratio >= 0.7,
          "%d/%d = %.0f%%" % (len(ok_soft), len(soft), ratio * 100))

    log("")
    log("  可用周期矩阵（实际取到的根数，'—' 表示取不到）：")
    by = {}
    for n, p, c in results:
        by.setdefault(n, {})[p] = c
    for name in SYMBOL_MAP:
        row = by.get(name, {})
        log("    %-12s %s" % (name, "  ".join(
            "%s=%s" % (p, row.get(p) if isinstance(row.get(p), int) else "—")
            for p in ["W", "D", "12H", "4H", "1H", "15M", "5M"])))

    # 反向断言：声明不支持的周期必须真取不到（防谎报）
    negatives = [
        ("恒生指数", "1H", "港股分时接口已下线"),
        ("恒生指数", "5M", "同上"),
        ("美元兑离岸人民币", "1H", "外汇分时接口要 ticktime"),
        ("上海金", "1H", "上金所无分时"),
        ("上海金", "5M", "同上"),
        ("纳斯达克100", "1H", "国际指数分钟线免费源取不到"),
        ("现货黄金", "12H", "外盘无 12H"),
        ("现货黄金", "4H", "外盘只有当日分时，重采样 4H 仅约 5 根，不足以算指标"),
    ]
    for name, period, why in negatives:
        n, p, c = one(name, period)
        check("如实标注：%s 无 %s（%s）" % (name, period, why), not isinstance(c, int),
              "实际取到 %s 根" % c)


# ==================== 主流程 ====================

run(t_structure, "A. 结构一致性（品种 / 数据源 / 别名 / 慢速源声明）")
run(t_aliases, "B. 品种别名识别（防短别名抢长别名）")
run(t_realtime, "C. 实时行情（含来源标注与慢速源隔离）")
run(t_kline_matrix, "D. K线可用周期矩阵（双向断言：支持的要能取、不支持的要取不到）")

log("")
log("=" * 64)
log("汇总：通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
if FAIL:
    log("失败项：")
    for f in FAIL:
        log("  - " + f)
log("=" * 64)

out_path = os.path.join(ROOT, "tools", "_stage8_result.txt")
with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("done: pass=%d fail=%d -> %s" % (len(PASS), len(FAIL), out_path))
sys.exit(1 if FAIL else 0)
