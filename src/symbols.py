# -*- coding: utf-8 -*-
"""
江门金量化 · 品种定义与数据源映射

每个品种包含：
  name   —— 界面显示名称
  source —— 数据源类型（sina_foreign / em_index / sina_futures / sina_index）
  symbol —— 数据源中的代码
  unit   —— 单位（用于界面展示）
  scale  —— 价格缩放系数（部分源返回的价格需要换算单位）
"""

GROUPS = [
    {
        "name": "贵金属",
        "items": [
            {"name": "现货黄金", "source": "sina_foreign", "symbol": "XAU", "unit": "美元/盎司", "scale": 1.0},
            {"name": "现货白银", "source": "sina_foreign", "symbol": "XAG", "unit": "美元/盎司", "scale": 1.0},
        ],
    },
    {
        "name": "国际商品 / 指数",
        "items": [
            {"name": "铜",         "source": "sina_foreign", "symbol": "HG",  "unit": "美元/磅", "scale": 0.01},
            {"name": "WTI原油",    "source": "sina_foreign", "symbol": "CL",  "unit": "美元/桶", "scale": 1.0},
            {"name": "纳斯达克100", "source": "sina_global", "symbol": "gb_ndx", "unit": "点", "scale": 1.0},
            {"name": "标普500",    "source": "sina_global", "symbol": "gb_inx", "unit": "点", "scale": 1.0},
            {"name": "美元指数",    "source": "sina_global", "symbol": "DINIW",  "unit": "点", "scale": 1.0},
        ],
    },
    {
        "name": "国内商品期货",
        "items": [
            {"name": "螺纹钢", "source": "sina_futures", "symbol": "RB0", "unit": "元/吨", "scale": 1.0},
            {"name": "焦煤",   "source": "sina_futures", "symbol": "JM0", "unit": "元/吨", "scale": 1.0},
            {"name": "甲醇",   "source": "sina_futures", "symbol": "MA0", "unit": "元/吨", "scale": 1.0},
            {"name": "乙二醇", "source": "sina_futures", "symbol": "EG0", "unit": "元/吨", "scale": 1.0},
            {"name": "纯碱",   "source": "sina_futures", "symbol": "SA0", "unit": "元/吨", "scale": 1.0},
        ],
    },
    {
        "name": "国内指数",
        "items": [
            {"name": "科创50",  "source": "sina_index", "symbol": "sh000688", "unit": "点", "scale": 1.0},
            {"name": "上证指数", "source": "sina_index", "symbol": "sh000001", "unit": "点", "scale": 1.0},
        ],
    },
]

# 名称 -> 配置 快速查找表
SYMBOL_MAP = {}
for _g in GROUPS:
    for _it in _g["items"]:
        SYMBOL_MAP[_it["name"]] = _it
