# -*- coding: utf-8 -*-

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

    alias("netdisk_client", "python -m lugwit_netdisk_client.main")
    alias("netdisk_client_doctor", "python -m lugwit_netdisk_client.qt_boot")
