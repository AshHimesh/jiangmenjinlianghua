# -*- coding: utf-8 -*-
"""
江门金量化 · 后端包

导入本包时自动安装全局网络超时保护：akshare 等库内部的 requests 调用没有超时，
不加以保护会在数据源无响应时永久阻塞（行情冻结、自检挂起）。详见 src/netguard.py。
"""
from .netguard import install as _install_netguard

_install_netguard()
