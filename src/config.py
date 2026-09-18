# -*- coding: utf-8 -*-
"""
江门金量化 · 配置读写

保存位置：项目根目录 config.json
注意：API Key 以明文保存在本地文件中，仅在本机使用。
"""
import json
import os

from .paths import data_path

# 配置文件放在「用户数据目录」（打包后即 exe 旁边，方便用户备份/修改）
CONFIG_PATH = data_path("config.json")

# 服务商预设（均为 OpenAI 兼容接口，用户也可选「自定义」手填）
PROVIDERS = [
    {
        "id": "deepseek",
        "name": "DeepSeek（深度求索）",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-reasoner", "deepseek-chat"],
        "hint": "deepseek-reasoner 支持思考过程展示",
    },
    {
        "id": "zhipu",
        "name": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4-plus", "glm-4-flash", "glm-z1-air"],
        "hint": "glm-z1 系列支持思考过程",
    },
    {
        "id": "moonshot",
        "name": "Kimi（月之暗面）",
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k"],
        "hint": "",
    },
    {
        "id": "qwen",
        "name": "通义千问（阿里云）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-plus", "qwen-max", "qwq-32b"],
        "hint": "qwq 系列支持思考过程",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini"],
        "hint": "",
    },
    {
        "id": "custom",
        "name": "自定义（任意 OpenAI 兼容接口）",
        "base_url": "",
        "models": [],
        "hint": "自行填写接口地址与模型名",
    },
]

DEFAULTS = {
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "",
    "model": "deepseek-reasoner",
    "inject_market": True,
    # 是否启用 AI 工具调用（让 AI 按需自己读取K线与指标；需模型支持函数调用）
    "enable_tools": True,
    # 激活的技能文件列表；None 或空 = skills 目录下全部激活
    "active_skills": None,
}


def load_config():
    """读取配置；文件不存在或损坏时返回默认值。"""
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                for k in DEFAULTS:
                    if k in saved:
                        cfg[k] = saved[k]
        except Exception:
            pass
    return cfg


def save_config(cfg):
    """保存配置（只接受已知字段），返回保存后的完整配置。"""
    data = dict(DEFAULTS)
    if isinstance(cfg, dict):
        for k in DEFAULTS:
            if k in cfg and cfg[k] is not None:
                data[k] = cfg[k]
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data
