# -*- coding: utf-8 -*-
"""
江门金量化 · 路径解析

区分两类目录：

1. 资源目录 resources_dir()
   —— 打包进 exe 的只读文件（web/ 前端页面）。
      开发时 = 项目根目录；打包后 = PyInstaller 解包目录(sys._MEIPASS)。

2. 用户数据目录 data_dir()
   —— 用户可以查看/编辑的文件（skills/、config.json、cache.db、日志）。
      开发时 = 项目根目录；打包后 = exe 所在目录（方便用户放自己的技能文件）。
"""
import os
import sys

# 开发模式下的项目根目录（本文件在 src/ 下）
_DEV_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_frozen():
    """是否运行在 PyInstaller 打包后的环境。"""
    return bool(getattr(sys, "frozen", False))


def resources_dir():
    """只读资源目录（web/ 等）。"""
    if is_frozen():
        base = getattr(sys, "_MEIPASS", None)
        if base:
            return base
        return os.path.dirname(os.path.abspath(sys.executable))
    return _DEV_ROOT


def data_dir():
    """可写的用户数据目录（skills/、config.json、cache.db）。"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return _DEV_ROOT


def resource_path(*parts):
    return os.path.join(resources_dir(), *parts)


def data_path(*parts):
    return os.path.join(data_dir(), *parts)
