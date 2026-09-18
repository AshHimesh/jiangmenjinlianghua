# -*- coding: utf-8 -*-
"""js_api 接口层测试：配置读写、品种、提问（无 Key 时应友好报错）。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api import Api
from src.chat import ChatSession
from src.fetcher import QuoteService

OUT = []


def log(*args):
    OUT.append(" ".join(str(a) for a in args))


service = QuoteService()          # 不启动后台线程，避免联网
service._cache = {
    "现货黄金": {"price": 4393.5, "change": -0.19, "updated": "12:00:00", "stale": False},
}
chat = ChatSession()
api = Api(service, chat)

log("=== get_symbols ===")
syms = api.get_symbols()
log("分组数:", len(syms), " 品种总数:", sum(len(g["items"]) for g in syms))
log("第一组:", syms[0]["name"], [i["name"] for i in syms[0]["items"]])

log("")
log("=== get_config ===")
c = api.get_config()
log("服务商数量:", len(c["providers"]))
log("服务商:", [p["name"] for p in c["providers"]])
log("当前配置:", c["config"])

log("")
log("=== save_config ===")
saved = api.save_config({
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "",
    "model": "deepseek-reasoner",
    "inject_market": True,
})
log("保存结果:", saved)
log("config.json 存在:", os.path.exists(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")))

log("")
log("=== ask（无 Key，应友好报错）===")
r = api.ask("黄金现在怎么看？", "现货黄金")
log("ask 返回:", r)
st = None
for _ in range(40):
    st = api.get_stream(r["id"])
    if st["done"]:
        break
    time.sleep(0.05)
log("流状态 done:", st["done"], " error:", st["error"])

log("")
log("=== clear_chat ===")
log("清空:", api.clear_chat())

with open("tools/_api_test.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("done")
