# -*- coding: utf-8 -*-
"""
江门金量化 · 品种定义与数据源映射

每个品种包含：
  name   —— 界面显示名称（也用作 AI 工具参数与缓存键，改名要同步 docs）
  source —— 数据源类型，决定「实时行情」与「K线」走哪条取数分支：
            sina_futures  新浪期货（国内商品期货）
            sina_index    新浪指数 / ETF（国内指数与场内基金）
            sina_global   新浪国际指数（纳指、标普、美元指数）
            sina_foreign  新浪外盘商品（金、银、铜、原油）
            sina_hk       新浪港股指数（恒指）
            sina_fx       新浪外汇（离岸人民币）
            sge           上海黄金交易所（上海金基准价）
  symbol —— 数据源中的代码
  unit   —— 单位（界面展示）
  scale  —— 价格缩放系数（部分源返回的价格需要换算单位）

数据源可用周期（2026-09-18 阶段 8 逐一实测，不可得的如实标注）：
  sina_futures → 周/日/12H/4H/1H/15M/5M   （12H、4H 由 1 小时线重采样）
  sina_index   → 周/日/12H/4H/1H/15M/5M   （同上）
  sina_foreign → 周/日/1H/15M/5M           （分钟线仅当日；不声明 12H/4H —— 见下）
  sina_global  → 周/日                     （国际指数分钟线免费源取不到）
  sina_hk      → 周/日                     （新浪港股分时接口已下线，无分钟线）
  sina_fx      → 周/日                     （新浪外汇分时接口要求 ticktime，取不到）
  sge          → 周/日                     （上金所只提供日频历史与实时快照）

不声明外盘 12H/4H 的原因：外盘只有当日分时（约 70 根 1 分钟），重采样成 4H 只剩约 5 根，
达不到计算 MA20 等指标所需的数据量，声明了反而会诱导 AI 用 5 根K线下结论。
"""

GROUPS = [
    {
        "name": "贵金属",
        "items": [
            {"name": "现货黄金", "source": "sina_foreign", "symbol": "XAU", "unit": "美元/盎司", "scale": 1.0},
            {"name": "现货白银", "source": "sina_foreign", "symbol": "XAG", "unit": "美元/盎司", "scale": 1.0},
            # 上金所上海金基准价，银行积存金的定价基准（需求 5.2.1）
            {"name": "上海金",   "source": "sge",          "symbol": "Au99.99", "unit": "元/克", "scale": 1.0},
            {"name": "沪金AU",   "source": "sina_futures", "symbol": "AU0", "unit": "元/克", "scale": 1.0},
            {"name": "沪银AG",   "source": "sina_futures", "symbol": "AG0", "unit": "元/千克", "scale": 1.0},
        ],
    },
    {
        "name": "国际与港股",
        "items": [
            {"name": "铜",          "source": "sina_foreign", "symbol": "HG",  "unit": "美元/磅", "scale": 0.01},
            {"name": "WTI原油",     "source": "sina_foreign", "symbol": "CL",  "unit": "美元/桶", "scale": 1.0},
            {"name": "布伦特原油",   "source": "sina_foreign", "symbol": "OIL", "unit": "美元/桶", "scale": 1.0},
            {"name": "纳斯达克100",  "source": "sina_global",  "symbol": "gb_ndx", "unit": "点", "scale": 1.0},
            {"name": "标普500",     "source": "sina_global",  "symbol": "gb_inx", "unit": "点", "scale": 1.0},
            {"name": "美元指数",     "source": "sina_global",  "symbol": "DINIW",  "unit": "点", "scale": 1.0},
            {"name": "恒生指数",     "source": "sina_hk",      "symbol": "rt_hkHSI", "unit": "点", "scale": 1.0},
        ],
    },
    {
        "name": "国内商品期货",
        "items": [
            {"name": "螺纹钢", "source": "sina_futures", "symbol": "RB0", "unit": "元/吨", "scale": 1.0},
            {"name": "铁矿石", "source": "sina_futures", "symbol": "I0",  "unit": "元/吨", "scale": 1.0},
            {"name": "焦煤",   "source": "sina_futures", "symbol": "JM0", "unit": "元/吨", "scale": 1.0},
            {"name": "玻璃",   "source": "sina_futures", "symbol": "FG0", "unit": "元/吨", "scale": 1.0},
            {"name": "纯碱",   "source": "sina_futures", "symbol": "SA0", "unit": "元/吨", "scale": 1.0},
            {"name": "甲醇",   "source": "sina_futures", "symbol": "MA0", "unit": "元/吨", "scale": 1.0},
            {"name": "乙二醇", "source": "sina_futures", "symbol": "EG0", "unit": "元/吨", "scale": 1.0},
        ],
    },
    {
        "name": "国内指数与 ETF",
        "items": [
            {"name": "上证指数", "source": "sina_index", "symbol": "sh000001", "unit": "点",  "scale": 1.0},
            {"name": "沪深300",  "source": "sina_index", "symbol": "sh000300", "unit": "点",  "scale": 1.0},
            {"name": "创业板指", "source": "sina_index", "symbol": "sz399006", "unit": "点",  "scale": 1.0},
            {"name": "科创50",   "source": "sina_index", "symbol": "sh000688", "unit": "点",  "scale": 1.0},
            # 场内最普及的黄金投资工具，代码 518880
            {"name": "黄金ETF",  "source": "sina_index", "symbol": "sh518880", "unit": "元/份", "scale": 1.0},
        ],
    },
    {
        "name": "汇率",
        "items": [
            {"name": "美元兑离岸人民币", "source": "sina_fx", "symbol": "fx_susdcnh", "unit": "", "scale": 1.0},
        ],
    },
]

# 名称 -> 配置 快速查找表
SYMBOL_MAP = {}
for _g in GROUPS:
    for _it in _g["items"]:
        SYMBOL_MAP[_it["name"]] = _it

# 各数据源实际可用的周期（唯一事实源，2026-09-18 阶段 8 实测）
# 声明必须与实测一致：声明支持的要真能取到（防虚报），声明不支持的要真取不到（防谎报）。
PERIODS_BY_SOURCE = {
    "sina_futures": ["W", "D", "12H", "4H", "1H", "15M", "5M"],
    "sina_index": ["W", "D", "12H", "4H", "1H", "15M", "5M"],
    "sina_foreign": ["W", "D", "1H", "15M", "5M"],
    "sina_global": ["W", "D"],
    # 港股指数：新浪分时接口已下线（Service not valid），东财在本机被风控 → 只有周/日
    "sina_hk": ["W", "D"],
    # 外汇：新浪外汇分时接口要 ticktime 参数，试过 scale/datalen 组合仍返回 null → 只有周/日
    "sina_fx": ["W", "D"],
    # 上金所：只有日频历史 + 实时快照
    "sge": ["W", "D"],
}


def periods_of(name):
    """该品种声明支持的周期列表（按数据源）。"""
    item = SYMBOL_MAP.get(name)
    if not item:
        return []
    return list(PERIODS_BY_SOURCE.get(item["source"], []))


def names():
    return list(SYMBOL_MAP.keys())


def items_of(source):
    return [it for it in SYMBOL_MAP.values() if it["source"] == source]
