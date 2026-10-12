# -*- coding: utf-8 -*-
# === wuwo doc_pkg BEGIN v7 (auto-generated, do not edit) ===
# 包：lugwit_netdisk_client 999.0  Lugwit 网盘 PC 客户端（PySide6 托盘 + QWebEngineView 承载网页 UI）
# 依赖：python-3.12+<3.13, pyside6, l_qframelesswindow
# 提供：PYTHONPATH {root}/src
#    env LUGWIT_NETDISK_CLIENT_ROOT, SCRIPT_EDITOR_HTTP_PORT, SCRIPT_EDITOR_HTTP_PORT_STRICT, SCRIPT_EDITOR_SERVICE_NAME
# 入口：netdisk_client
# 用法：wuwo lugwit_netdisk_client 进入该包环境；wuwor lugwit_netdisk_client -- netdisk_client 直接调用别名
# 目录：包自有代码根：src/lugwit_netdisk_client/
#    自有子目录：doc
#    不要在源码根下盲搜全量文件，先按上面目录定位；第三方库的问题不在本包职责内。
# 查文档：全量搜索（笔记+全部知识库）：curl "http://127.0.0.1:8765/api/search?q=<关键词>&limit=10" → hits[].kb_name / rel
#     只搜本仓文档：curl "http://127.0.0.1:8765/api/kb/rez_pkg/search?q=<关键词>&limit=10"
#     读正文：curl "http://127.0.0.1:8765/api/kb/<kb_name>/workspace/file?path=<rel>"（参数名 path，不是 rel）
#     本机直连 8765 免 token（仅 GET，勿经 nginx）；q 要 URL 编码；score < 1.0 多为向量噪声
#     接口全表与踩坑见 D:/TD_Depot/Software/Lugwit_syncPlug/lugwit_insapp/trayapp/rez-package-source/Rez-Docs/Rez_pkg/l_notepad_搜索接口使用文档.md
# 跑代码：远程连上宿主程序，用宿主解释器跑代码（依赖与 Qt 事件循环齐备），别自己另起解释器
#     探活：curl http://127.0.0.1:8764/status（多实例逐个试 8764 / 8769；editor_available=true 才可用）
#     执行：curl -H "Content-Type: application/json" -d "{\"code\": \"print(1)\"}" http://127.0.0.1:8764/execute
#     长代码先落盘再 exec(open(r'<abs.py>', encoding='utf-8').read())，避免 JSON 转义地狱
#     其它工具：/execute_async 异步、/upload /upload_folder /download 传文件、/tools 列 agent 工具
#     UI 自动化（Qt 版 Playwright）：/ui/tree 控件树、/ui/locate 定位、/ui/action click|set_text|press_key、/ui/wait auto-wait、/ui/screenshot 截图
#     全表见 D:/TD_Depot/Software/Lugwit_syncPlug/lugwit_insapp/trayapp/rez-package-source/Rez-Docs/Rez_pkg/l_script_editor.md
# 建包：新建/改包前先读 D:/TD_Depot/Software/Lugwit_syncPlug/lugwit_insapp/trayapp/rez-package-source/Rez-Docs/Rez包创建和启动指导文档.md
#    覆盖：目录布局 <包名>/<版本>/package.py、requires 写法、alias/env、变体哈希、修饰符与启动方式
# 规范：999.0 源码即环境（改源码即生效，无需 build）；依赖写进 requires 由 wuwo 自动补齐
#    修饰符 .dev_mod / .solo / .soloignore / .script_server 与建包规范见 Rez-Docs/Rez包创建和启动指导文档.md
# === wuwo doc_pkg END ===

name = "lugwit_netdisk_client"
version = "999.0"
description = "Lugwit 网盘 PC 客户端（PySide6 托盘 + QWebEngineView 承载网页 UI）"
authors = ["Lugwit Team"]

requires = [
    "python-3.12+<3.13",
    # QtWebEngine 在 pyside6_addons 里；pyside6 元包会同时带 essentials/addons/shiboken
    "pyside6",
    # 无边框标题栏外壳（与 l_notepad 同一套），自带暗色主题 + 帮助文档按钮
    "l_qframelesswindow",
]

build_command = False
cachable = True
relocatable = True


def commands():
    env.PYTHONPATH.prepend("{root}/src")
    env.LUGWIT_NETDISK_CLIENT_ROOT = "{root}"

    # 脚本编辑器 HTTP 服务：**首选端口 8769**（严格模式：不自动抢漂，但也不再"被占即失败"）
    #   - 被占用时依次：结束同程序旧实例（同 `-m` 模块 / 发现文件里记的 pid）→
    #     弹窗 / 控制台询问（结束 / 漂移 / 放弃）→ 都无法交互才漂到空闲端口；
    #   - 所以 GUI 启动（无控制台）也能起来，只是可能不在 8769；
    #     调用方以 ~/.Lugwit/run/netdisk_client.json 里的 url/port 为准，别写死端口。
    env.SCRIPT_EDITOR_HTTP_PORT = "8769"
    env.SCRIPT_EDITOR_HTTP_PORT_STRICT = "1"
    # 服务发现名：~/.Lugwit/run/netdisk_client.json 记录实际 url/port/pid/ipc 地址，
    # 调用方读它即可（不必写死 8769）；IPC 命名管道 \\.\pipe\lugwit-netdisk_client-<user>
    env.SCRIPT_EDITOR_SERVICE_NAME = "netdisk_client"

    alias("netdisk_client", "python -m lugwit_netdisk_client.main")
