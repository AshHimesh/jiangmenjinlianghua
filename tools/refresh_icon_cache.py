# -*- coding: utf-8 -*-
"""
重建 Windows 图标缓存

**什么时候需要它**

换了程序图标、重新打包之后，文件资源管理器（Explorer）有时仍然显示**旧图标**。
原因：Windows 的图标缓存以「文件路径」为键，exe 路径没变时不会重新读取图标资源。

**这个脚本做什么**

1. 结束资源管理器进程（任务栏会短暂消失）
2. 删除 `%LOCALAPPDATA%\\Microsoft\\Windows\\Explorer\\iconcache*.db` 等缓存文件
3. 重新启动资源管理器

用法：
    .venv\\Scripts\\python.exe tools\\refresh_icon_cache.py
    .venv\\Scripts\\python.exe tools\\refresh_icon_cache.py --yes   # 跳过确认

注意：运行期间已打开的文件资源管理器窗口会被关闭，几秒后自动恢复。
"""
import glob
import os
import subprocess
import sys
import time

CACHE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                         "Microsoft", "Windows", "Explorer")
CACHE_FILES = [
    os.path.join(CACHE_DIR, "iconcache*.db"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "IconCache.db"),
]


def _kill_explorer():
    subprocess.run(["taskkill", "/f", "/im", "explorer.exe"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _start_explorer():
    try:
        subprocess.Popen(["explorer.exe"], close_fds=True)
    except OSError:
        subprocess.run("start explorer.exe", shell=True)


def main():
    skip_ask = "--yes" in sys.argv

    print("=" * 60)
    print("重建 Windows 图标缓存")
    print("=" * 60)
    print("说明：任务栏会短暂消失，已打开的文件夹窗口会关闭，几秒后自动恢复。\n")

    if not skip_ask:
        try:
            ans = input("继续吗？(y/N) ").strip().lower()
        except EOFError:
            ans = "y"
        if ans not in ("y", "yes"):
            print("已取消。")
            return 0

    print("[1/3] 结束资源管理器 ...")
    _kill_explorer()
    time.sleep(3)

    print("[2/3] 删除图标缓存 ...")
    removed, failed = 0, 0
    for pattern in CACHE_FILES:
        for path in glob.glob(pattern):
            try:
                os.remove(path)
                removed += 1
            except OSError:
                failed += 1
    print("      删除成功 %d 个，占用中跳过 %d 个" % (removed, failed))

    print("[3/3] 重启资源管理器 ...")
    _start_explorer()
    time.sleep(4)

    print("\n完成。请重新打开 exe 所在文件夹查看图标效果。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
