# 江门金量化 · 项目总指引

> 本文件是项目的**唯一入口**。开发前先读本文件，再按索引进入对应标准文件。
> 项目：Windows 桌面「行情看板 + AI 对话」极简工具（Python + pywebview + AKShare）。

## 1. 标准文件路径索引

| 文档 | 路径 | 用途 |
| --- | --- | --- |
| 项目需求说明 | `docs/01-项目需求说明.md` | 做什么、不做什么 |
| 技术方案 | `docs/02-技术方案.md` | 数据源、AI、技能、缓存、打包 |
| 设计规范 | `docs/03-设计规范.md` | 界面长什么样、配色字体布局 |
| 开发执行步骤 | `docs/04-开发执行步骤.md` | 分几个阶段、每阶段做什么、怎么验收 |
| 开发日志规范 | `docs/05-开发日志规范.md` | 日志怎么写、怎么自动记录 |
| 开发日志目录 | `开发日志/` | 每天的开发记录 |
| 日志模板 | `开发日志/_模板.md` | 日志格式模板 |
| 每日日志脚本 | `tools/daily_log.py` | 自动创建当天日志 |

## 2. 目录结构

```
jiangmenjinlianghua/
├── deepseekproject.md        # 本文件：总指引
├── main.py                   # 程序入口（含 --selftest 自检模式）
├── build.py                  # 打包脚本（PyInstaller）
├── requirements.txt          # Python 依赖
├── config.json               # AI 配置（含 API Key，本地明文保存）
├── cache.db                  # 相似问题缓存（SQLite）
├── jin10_quota.json          # 金十额度计数（按北京时间自然日重置，运行时生成）
│
├── docs/                     # 标准文件
│   ├── 01-项目需求说明.md
│   ├── 02-技术方案.md
│   ├── 03-设计规范.md
│   ├── 04-开发执行步骤.md
│   └── 05-开发日志规范.md
│
├── src/                      # 后端
│   ├── paths.py              # 资源目录 / 用户数据目录解析
│   ├── netguard.py           # 全局网络超时保护（防止 akshare 请求永久阻塞）
│   ├── symbols.py            # 14 个品种与数据源映射
│   ├── fetcher.py            # 实时行情抓取 + 后台刷新服务
│   ├── kline.py              # 多周期K线（含重采样与缓存）
│   ├── indicators.py         # 技术指标计算
│   ├── analysis.py           # 多周期报告 + 品种识别 + 缓存预热
│   ├── ai.py                 # OpenAI 兼容流式调用 + 工具调用循环
│   ├── tools.py              # AI 可调用的工具（读K线/指标/品种；金十 8 个工具按需启用）
│   ├── mcp.py                # 标准 MCP 客户端（阶段 7，仅金十在用）
│   ├── jin10.py              # 金十业务层：8 个工具 + 额度保护 + 来源标注
│   ├── chat.py               # 对话会话 + 提示词组装
│   ├── skills.py             # 技能（Skill）加载
│   ├── qacache.py            # 相似问题缓存
│   ├── config.py             # 配置读写
│   └── api.py                # 暴露给前端的 js_api
│
├── web/                      # 前端（极简白色）
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   └── avatar.png            # 顶栏头像（由 tools/make_icon.py 生成）
│
├── assets/                   # 品牌素材
│   ├── icon.png              # 图标源图（换图标只需替换这个再跑 make_icon.py）
│   ├── app.ico               # 程序图标（打包用，多尺寸）
│   └── icon_preview.png      # 裁剪预览
│
├── skills/                   # AI 分析技能（.txt / .md，默认全部激活）
│
├── tools/                    # 辅助脚本
│   ├── daily_log.py          # 每日日志自动创建
│   ├── make_icon.py          # 生成程序图标与界面头像
│   ├── check_exe_icon.py     # 检查 exe 内图标资源尺寸
│   ├── refresh_icon_cache.py # 重建 Windows 图标缓存（换图标后 Explorer 不刷新时用）
│   ├── check_jin10_mcp.py    # 金十 MCP 探测（需 JIN10_DEV_TOKEN，不硬编码 token）
│   ├── test_stage7.py        # 阶段 7 自测（离线可跑；真连需 token）
│   └── test_*.py             # 其它模块测试脚本
│
│   ⚠️ 以 `_` 开头的脚本/产物（如 `_jin10_token.txt`）是开发期临时件，不入库
│
├── 开发日志/                  # 每日开发日志
│
└── dist/                     # 打包产物（build.py 生成）
    └── 江门金量化/
        ├── 江门金量化.exe
        ├── _internal/        # 依赖与前端资源
        ├── skills/           # 技能（用户可直接增删）
        └── 使用说明.txt
```

## 3. 常用命令

```powershell
# 开发模式运行
.\.venv\Scripts\python.exe main.py

# 功能自检（打包后无控制台时用于诊断，结果写 selftest.log）
.\.venv\Scripts\python.exe main.py --selftest
.\dist\江门金量化\江门金量化.exe --selftest

# 打包（文件夹模式，推荐）
.\.venv\Scripts\python.exe build.py
# 打包（单个 exe，启动较慢）
.\.venv\Scripts\python.exe build.py --onefile

# 创建当天开发日志
.\.venv\Scripts\python.exe tools\daily_log.py

# 阶段 7 自测（离线可跑；要真连金十先设环境变量 JIN10_DEV_TOKEN）
.\.venv\Scripts\python.exe tools\test_stage7.py
```

## 4. 工作说明（开发约定）

1. **先读再干**：开发前必读 `docs/04-开发执行步骤.md`，确认当前阶段。
2. **一次一个阶段**：严格遵守「一次只做一个阶段」原则，验收通过再进下一阶段。
3. **每日建日志**：每天首次开发前运行 `tools/daily_log.py` 创建当天日志。
4. **每日记日志**：每天结束更新当天日志的「已完成 / 待办」。
5. **标准即文档**：需求、技术、设计有变更时同步更新对应标准文件。
6. **阶段要验收**：按 `docs/04-开发执行步骤.md` 的验收标准检查。
7. **打包后必自检**：任何打包改动后，都要跑一次 `--selftest`，
   确认「14 品种行情 / 多周期K线 / 技能加载 / AI工具」四项正常
   （详见 `docs/02-技术方案.md` 第 7 节的踩坑记录：漏打包 `py_mini_racer` 会导致国内期货静默失败）。
8. **不写代码进日志**：日志只记事实与进度。
