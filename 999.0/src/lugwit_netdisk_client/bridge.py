# -*- coding: utf-8 -*-
"""QWebChannel 桥：网页 -> 本地能力。

网页里通过 `window.lugwitBridge` 调用，浏览器中该对象不存在，
页面据此做特性检测即可（同一套页面浏览器 / 客户端两用）。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QFileDialog

_CHUNK = 4 * 1024 * 1024


class Bridge(QObject):
    """暴露给网页的本地能力。所有方法都必须是 @Slot 才可见。"""

    progress = Signal(str, int, int)  # (tag, done, total)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    @Slot(result=str)
    def platform(self) -> str:
        return f"{sys.platform}|lugwit_netdisk_client"

    @Slot(result=str)
    def pickFolder(self) -> str:
        return QFileDialog.getExistingDirectory(None, "选择文件夹") or ""

    @Slot(result=str)
    def pickFiles(self) -> str:
        files, _ = QFileDialog.getOpenFileNames(None, "选择文件")
        return json.dumps(files, ensure_ascii=False)

    @Slot(str)
    def revealInExplorer(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            return
        if p.is_dir():
            subprocess.Popen(["explorer", str(p)])
        else:
            subprocess.Popen(["explorer", "/select,", str(p)])

    @Slot(str, result=str)
    def fileMd5(self, path: str) -> str:
        """整文件 md5，用于上传前探秒传（命中则完全不传）。"""
        p = Path(path)
        if not p.is_file():
            return ""
        h = hashlib.md5()
        total = p.stat().st_size
        done = 0
        with open(p, "rb") as fh:
            while True:
                chunk = fh.read(_CHUNK)
                if not chunk:
                    break
                h.update(chunk)
                done += len(chunk)
                self.progress.emit(p.name, done, total)
        return h.hexdigest()

    @Slot(str, result=str)
    def fileInfo(self, path: str) -> str:
        p = Path(path)
        if not p.exists():
            return json.dumps({"exists": False})
        st = p.stat()
        return json.dumps(
            {"exists": True, "isdir": p.is_dir(), "name": p.name,
             "size": st.st_size, "mtime": int(st.st_mtime)},
            ensure_ascii=False,
        )

    @Slot(str, result=str)
    def listDir(self, path: str) -> str:
        p = Path(path)
        if not p.is_dir():
            return json.dumps([])
        out = []
        for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            try:
                st = child.stat()
            except OSError:
                continue
            out.append({"name": child.name, "path": str(child), "isdir": child.is_dir(),
                        "size": st.st_size, "mtime": int(st.st_mtime)})
        return json.dumps(out, ensure_ascii=False)

    @Slot(str, int, int, result=str)
    def treeDir(self, path: str, max_depth: int = 3, max_items: int = 2000) -> str:
        """递归列目录树，给前端 Workspace 标签用。

        限制深度和条目总数，避免用户选到 C:\\ 这种超大目录时卡死界面。
        """
        p = Path(path)
        if not p.is_dir():
            return json.dumps([])

        budget = {"n": 0, "hit": False}

        def walk(cur: Path, depth: int) -> list[dict]:
            if depth > max_depth or budget["hit"]:
                return []
            children: list[dict] = []
            try:
                entries = sorted(cur.iterdir(),
                                 key=lambda x: (not x.is_dir(), x.name.lower()))
            except OSError:
                return []
            for child in entries:
                if budget["hit"]:
                    break
                budget["n"] += 1
                if budget["n"] > max_items:
                    budget["hit"] = True
                    break
                try:
                    st = child.stat()
                except OSError:
                    continue
                node = {"name": child.name, "path": str(child),
                        "isdir": child.is_dir(), "size": st.st_size,
                        "mtime": int(st.st_mtime), "kids": None}
                if child.is_dir():
                    node["kids"] = walk(child, depth + 1)
                children.append(node)
            return children

        tree = walk(p, 1)
        result = tree
        if budget["hit"]:
            result = result or []
        return json.dumps({"root": str(p), "tree": result,
                           "truncated": budget["hit"]}, ensure_ascii=False)

    @Slot(result=str)
    def homeDir(self) -> str:
        return str(Path.home())

    @Slot(str)
    def openExternal(self, url: str) -> None:
        os.startfile(url)  # noqa: S606


__all__ = ["Bridge"]
