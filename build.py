# -*- coding: utf-8 -*-
"""
江门金量化 · 打包脚本

用法（在项目根目录执行）：
    .venv\\Scripts\\python.exe build.py              # 打包成文件夹（推荐：启动快、稳定）
    .venv\\Scripts\\python.exe build.py --onefile    # 打包成单个 exe（启动较慢，体积大）
    .venv\\Scripts\\python.exe build.py --console    # 保留控制台窗口（排查问题用）

产物：
    dist\\江门金量化\\江门金量化.exe        （文件夹模式，直接双击里面的 exe）
    dist\\江门金量化.exe                    （单文件模式）

注意：
    skills/ 目录会在打包后**复制到程序旁边**，方便用户自行增删技能文件。
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "江门金量化"
DIST = os.path.join(ROOT, "dist")
ICON = os.path.join(ROOT, "assets", "app.ico")


def _pyinstaller_args(onefile, console):
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", NAME,
        # 前端页面打包进程序
        "--add-data", "web%sweb" % os.pathsep,
        # akshare 大量动态导入，整体收集最稳妥
        "--collect-all", "akshare",
        # 关键：akshare 的 futures_zh_spot 依赖 py_mini_racer（V8 JS 引擎），
        # 它带有原生 mini_racer.dll 与 icudtl.dat，不收集会导致国内期货实时行情全部失败
        "--collect-all", "py_mini_racer",
        "--collect-all", "webview",
        "--collect-all", "pythonnet",
        "--collect-all", "clr_loader",
        "--collect-all", "curl_cffi",
        # 阶段 9：分析图表。matplotlib 有大量数据文件（字体度量、样式），整体收集
        # （中文字体不打包：直接读 C:\Windows\Fonts\，Windows 自带）
        "--collect-all", "matplotlib",
        "--hidden-import", "webview.platforms.edgechromium",
        "--hidden-import", "webview.platforms.winforms",
        "--hidden-import", "sqlite3",
        "--onefile" if onefile else "--onedir",
        "--console" if console else "--windowed",
    ]
    # 图标（可选，来自 assets/app.ico）
    if os.path.isfile(ICON):
        args += ["--icon", ICON]
    else:
        print("[提示] 未找到图标 %s，将使用默认图标（可运行 tools/make_icon.py 生成）" % ICON)
    args.append("main.py")
    return args


def _copy_user_files(target_dir, onefile):
    """把 skills/ 复制到程序旁边，并生成使用说明。"""
    src_skills = os.path.join(ROOT, "skills")
    if not os.path.isdir(src_skills):
        print("[警告] 未找到 skills 目录，跳过复制")
        return
    dst_skills = os.path.join(target_dir, "skills")
    if os.path.isdir(dst_skills):
        shutil.rmtree(dst_skills, ignore_errors=True)
    shutil.copytree(src_skills, dst_skills)
    print("[OK] 已复制 skills/ -> %s" % dst_skills)

    readme = os.path.join(target_dir, "使用说明.txt")
    with open(readme, "w", encoding="utf-8") as f:
        f.write(
            "江门金量化 · 使用说明\n"
            "========================================\n\n"
            "1. 双击「%s.exe」启动程序。\n\n"
            "2. 首次使用请点右上角 ⚙ 填写 AI 接口信息：\n"
            "   - 服务商：DeepSeek / 智谱 / Kimi / 通义千问 / OpenAI\n"
            "   - API Key：填你自己的密钥\n"
            "   - 模型：如 deepseek-reasoner（带思考过程）\n"
            "   配置会保存在同目录的 config.json 中。\n\n"
            "3. skills 文件夹里是 AI 的分析技能模板（.txt / .md）。\n"
            "   你可以直接往里面放自己的技能文件，重新打开程序即自动加载；\n"
            "   也可以在程序里点 ⚙ → 导入技能文件。\n\n"
            "4. cache.db 是相似问题缓存，删掉即可清空缓存。\n\n"
            "5. reports 文件夹是导出的分析报告（.md 可编辑、.html 双击即看/可打印成 PDF）。\n"
            "   在对话区点「生成研报」可一键出报告，或点「导出报告」把当前回答落成文件。\n\n"
            "6. 若程序无法启动，请看同目录下的 error.log。\n"
            % NAME
        )
    print("[OK] 已生成 使用说明.txt")


def main():
    onefile = "--onefile" in sys.argv
    console = "--console" in sys.argv

    print("=" * 64)
    print("打包：%s  模式：%s" % (NAME, "单文件" if onefile else "文件夹"))
    print("=" * 64)

    args = _pyinstaller_args(onefile, console)
    print("执行：%s\n" % " ".join('"%s"' % a if " " in a else a for a in args))
    code = subprocess.call(args, cwd=ROOT)
    if code != 0:
        print("\n[失败] PyInstaller 退出码 %s" % code)
        return code

    target_dir = DIST if onefile else os.path.join(DIST, NAME)
    if not os.path.isdir(target_dir):
        print("\n[失败] 未找到产物目录：%s" % target_dir)
        return 1

    _copy_user_files(target_dir, onefile)

    exe = os.path.join(target_dir, NAME + ".exe")
    size_mb = 0
    if os.path.isfile(exe):
        size_mb = os.path.getsize(exe) / 1024 / 1024

    print("\n" + "=" * 64)
    print("打包完成")
    print("产物目录：%s" % target_dir)
    print("可执行文件：%s  （%.1f MB）" % (exe, size_mb))
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
