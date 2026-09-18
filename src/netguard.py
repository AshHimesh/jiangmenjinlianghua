# -*- coding: utf-8 -*-
"""
江门金量化 · 全局网络超时保护

**为什么需要这个模块**

akshare 及部分第三方库内部的 `requests.get(...)` 调用**不设置超时**。
一旦某个数据源不响应（网络抖动、服务端挂起），请求会**永久阻塞**：
- 行情刷新线程被卡死 → 界面价格停止更新
- 自检 / 分析流程挂起 → 没有任何错误提示，用户只看到"卡住"

本项目实测就踩到过这个坑：打包后的自检进程运行 7 分钟仍无输出。

**做法**

给 `requests.Session.request` 打一个幂等补丁：凡是没有显式传 `timeout` 的请求，
一律注入 (连接超时, 读取超时)。`requests.get/post(...)` 内部都走 Session.request，
因此 akshare 等库的所有调用都会被覆盖。

本模块在 `src/__init__.py` 中被自动安装，任何入口（main.py、测试脚本）都会生效。
"""
import requests

DEFAULT_CONNECT_TIMEOUT = 10   # 建立连接超时（秒）
DEFAULT_READ_TIMEOUT = 25      # 等待响应超时（秒）

_installed = False
_original_request = None


def install(connect=None, read=None):
    """安装超时补丁（可重复调用，只会生效一次）。"""
    global _installed, _original_request
    if _installed:
        return False

    connect = DEFAULT_CONNECT_TIMEOUT if connect is None else connect
    read = DEFAULT_READ_TIMEOUT if read is None else read
    _original_request = requests.Session.request

    def request_with_timeout(self, method, url, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = (connect, read)
        return _original_request(self, method, url, **kwargs)

    request_with_timeout.__doc__ = "带默认超时的 Session.request"
    requests.Session.request = request_with_timeout
    _installed = True
    return True


def is_installed():
    return _installed
