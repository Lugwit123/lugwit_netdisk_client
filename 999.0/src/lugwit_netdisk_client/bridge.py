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

from . import depot_local

_CHUNK = 4 * 1024 * 1024


class Bridge(QObject):
    """暴露给网页的本地能力。所有方法都必须是 @Slot 才可见。"""

    progress = Signal(str, int, int)  # (tag, done, total)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._explicit_token = ""   # 主窗口登录成功后显式设置
        self._cookie_token = ""     # 从 WebEngine cookie 抓到的
        self._profile = None

    # ── 登录态（网页 cookie → 桥，供本地 depot 访问带凭据）──────────

    def attachProfile(self, profile) -> None:
        """挂上 QWebEngineProfile，抓取 lugwit_token cookie 供 depot 调用使用。

        网页（网盘 UI）在 WebEngine 里登录后，登录态表现为持久化 cookie；把它缓存到
        进程内即可让桥以同一身份直连本机 depot 服务，无需再走托盘 / nginx /baidu。
        """
        try:
            self._profile = profile
            store = profile.cookieStore()
            store.cookieAdded.connect(self._on_cookie_added)
            store.loadAllCookies()
        except Exception:  # noqa: BLE001
            pass

    def _on_cookie_added(self, cookie) -> None:
        try:
            if cookie.name() == "lugwit_token":
                value = bytes(cookie.value()).decode("utf-8", "replace")
                if value:
                    self._cookie_token = value
        except Exception:  # noqa: BLE001
            pass

    def setToken(self, token: str) -> None:
        """主窗口登录成功/登出时同步登录态（优先于 cookie 抓取）。"""
        self._explicit_token = str(token or "")

    def token(self) -> str:
        """当前可用的 lugwit_auth 登录态：显式设置 > 抓到的 cookie > 环境变量。"""
        return (self._explicit_token
                or self._cookie_token
                or os.environ.get("LUGWIT_ACCESS_TOKEN", "").strip())

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

    # ── 版本库（百度云 depot）本地能力 ──────────────────────────
    # 页面在客户端里运行时（window.lugwitBridge 存在）可直接从**本地**读版本库，
    # 不必绕「托盘中转」或 nginx /baidu 网关；实现见 depot_local.py。
    # 所有槽都返回 JSON 字符串：{"ok": true, ...} / {"ok": false, "error": "..."}

    @Slot(result=str)
    def depotBase(self) -> str:
        """当前 depot 服务基址 + 本地登录态情况（页面可用于显示 / 排查）。"""
        try:
            info = depot_local.base_info()
            info["has_token"] = bool(self.token())
            return json.dumps(info, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, str, result=str)
    def depotList(self, dir: str, ws: str = "") -> str:
        """列版本库目录（dir 为绝对逻辑路径，如 /notes/rez_pkg）。"""
        try:
            return json.dumps(depot_local.list_dir(dir, ws, token=self.token()),
                              ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, int, result=str)
    def depotDownload(self, path: str, rev: int = 0) -> str:
        """取版本库文件：文本回 text，二进制回 base64（rev=0 取最新）。"""
        try:
            return json.dumps(depot_local.download(path, rev, token=self.token()),
                              ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, str, result=str)
    def depotVersions(self, path: str, ws: str = "") -> str:
        """某文件的版本历史。"""
        try:
            return json.dumps(depot_local.versions(path, ws, token=self.token()),
                              ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


__all__ = ["Bridge"]
