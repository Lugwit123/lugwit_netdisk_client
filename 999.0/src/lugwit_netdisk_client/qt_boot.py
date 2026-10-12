# -*- coding: utf-8 -*-
"""QtWebEngine 启动修复。

rez 把 PySide6 拆成三个包（essentials / addons / shiboken6），各自一个
`PySide6` 目录。PySide6 是普通包（带 __init__.py），PYTHONPATH 上只有第一个
生效，于是 QtWebEngine 全套（在 addons 里）加载不到，报：

    ImportError: DLL load failed while importing QtWebEngineCore
    ERROR:icu_util.cc] Invalid file descriptor to ICU data received.

解决：把三个目录**硬链接**合并成一个 PySide6 目录（同盘符零拷贝、零额外占用），
在 import PySide6 之前插到 sys.path 最前面。

另外 QtWebEngine 的沙箱子进程在 rez 环境下起不来（0xC0000135 找不到 DLL），
必须加 `--no-sandbox`，否则渲染进程直接 crash、页面白屏。

合并结果与是否命中缓存会在启动时打印（`[netdisk_client] PySide6 合并完成: ...`）；
环境换了 pyside6 版本、或页面白屏怀疑 Qt 环境时，删掉 `rez-package-3rd/.pyside6_merged`
再启动即可强制重新合并。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_STAMP = "_lugwit_merged.ok"
_DEFAULT_FLAGS = "--no-sandbox --disable-gpu"
_READY: "Path | None" = None

# Windows 任务栏 / 通知 / 跳转列表的身份（AppUserModelID）。
# 不设的话，所有 python.exe 起的窗口都归到同一个任务栏分组、显示 python 图标，
# 钉到任务栏钉的也是 python；设了才按本应用单独分组、吃自己的图标。
# 必须在**创建窗口之前**设置，所以放在 qt_boot.setup() 里（早于 PySide6 导入）。
# 可用 LUGWIT_NETDISK_APP_ID 覆盖。
APP_ID = os.environ.get("LUGWIT_NETDISK_APP_ID", "").strip() or "Lugwit.NetdiskClient"


def set_app_id(app_id: str = "") -> bool:
    """设置进程的 AppUserModelID（仅 Windows；非 Windows 或不支持时返回 False）。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        shell32 = ctypes.windll.shell32
        shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
        shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_int32
        # S_OK(0) = 设置成功
        return shell32.SetCurrentProcessExplicitAppUserModelID(app_id or APP_ID) == 0
    except Exception:  # noqa: BLE001
        return False


def _pkg_python_dir(root: str) -> str:
    """rez 包根 -> 内含 PySide6/shiboken6 的 python 目录。"""
    if not root:
        return ""
    for cand in (
        Path(root) / "platform-windows" / "arch-AMD64" / "python-3.12" / "python",
        Path(root) / "python",
    ):
        if cand.is_dir():
            return str(cand)
    return ""


def _sources() -> list[str]:
    keys = ("REZ_PYSIDE6_ESSENTIALS_ROOT", "REZ_PYSIDE6_ADDONS_ROOT", "REZ_SHIBOKEN6_ROOT")
    dirs = [_pkg_python_dir(os.environ.get(k, "")) for k in keys]
    return [d for d in dirs if d]


def _merged_dir() -> Path:
    """合并目录放在 rez 三方包同盘同根下，保证硬链接可用。"""
    override = os.environ.get("LUGWIT_PYSIDE6_MERGED_DIR", "").strip()
    if override:
        return Path(override)
    ver = os.environ.get("REZ_PYSIDE6_ESSENTIALS_VERSION", "unknown")
    ess = os.environ.get("REZ_PYSIDE6_ESSENTIALS_ROOT", "")
    for parent in Path(ess).resolve().parents if ess else []:
        if parent.name == "rez-package-3rd":
            return parent / ".pyside6_merged" / ver
    return Path(os.environ.get("TEMP", ".")) / "_pyside6_merged" / ver


def merge(force: bool = False) -> Path:
    """硬链接合并三个 PySide6 包目录，返回合并后的目录。"""
    dst = _merged_dir()
    stamp = dst / _STAMP
    srcs = _sources()
    if not srcs:
        raise RuntimeError("未找到 pyside6 rez 包，请在含 pyside6 的环境中运行")
    want = "\n".join(srcs)
    if not force and stamp.is_file() and stamp.read_text(encoding="utf-8") == want:
        return dst

    if force and dst.is_dir():
        shutil.rmtree(dst, ignore_errors=True)
    dst.mkdir(parents=True, exist_ok=True)
    linked = copied = 0
    for src in srcs:
        base = Path(src)
        for dirpath, _dirnames, filenames in os.walk(base):
            rel = Path(dirpath).relative_to(base)
            out = dst / rel
            out.mkdir(parents=True, exist_ok=True)
            for fn in filenames:
                s, d = Path(dirpath) / fn, out / fn
                if d.exists():
                    continue
                try:
                    os.link(s, d)
                    linked += 1
                except OSError:
                    shutil.copy2(s, d)
                    copied += 1
    stamp.write_text(want, encoding="utf-8")
    print(f"[netdisk_client] PySide6 合并完成: 硬链接 {linked} / 复制 {copied} -> {dst}")
    return dst


def setup(force_merge: bool = False) -> Path:
    """必须在 import PySide6 之前调用；重复调用无副作用。"""
    global _READY
    set_app_id()  # 越早越好：窗口一出现任务栏分组就定死了
    if _READY is not None and not force_merge:
        return _READY
    mod = sys.modules.get("PySide6")
    dst = merge(force=force_merge)
    if mod is not None:
        # 已导入过：只有导入自合并目录才算正常，否则 QtWebEngine 必定加载失败
        if Path(mod.__file__).resolve().parent.parent != dst.resolve():
            raise RuntimeError(
                f"PySide6 已从 {Path(mod.__file__).parent} 导入，"
                "qt_boot.setup() 必须在 import PySide6 之前调用"
            )
        _READY = dst
        return dst
    p = str(dst)
    if p not in sys.path:
        sys.path.insert(0, p)
    os.add_dll_directory(str(dst / "PySide6"))
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", _DEFAULT_FLAGS)
    # l_qframelesswindow 走 qtpy；不钉死 binding 的话 qtpy 会去试 PyQt5/PySide2，
    # 试错过程可能撞上环境里别的 Qt，导致和这里合并出来的 PySide6 打架。
    os.environ.setdefault("QT_API", "pyside6")
    _READY = dst
    return dst
