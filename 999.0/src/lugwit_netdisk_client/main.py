# -*- coding: utf-8 -*-
"""Lugwit 网盘 PC 客户端主程序。

无边框标题栏（l_qframelesswindow，与 l_notepad 同一套外壳）+ QWebEngineView
承载现成网页（/baidu/depot、/baidu/files、/baidu/transfer）。
页面一套两用：浏览器直接访问，客户端里通过 QWebChannel 额外拿到本地能力。

启动：
    wuwor lugwit_netdisk_client -- netdisk_client
    wuwor lugwit_netdisk_client -- netdisk_client --url http://127.0.0.1:1027 --page /baidu/files
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import qt_boot

qt_boot.setup()  # 必须在 import PySide6 之前

from PySide6.QtCore import QTimer, QUrl, Qt  # noqa: E402
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap  # noqa: E402
from PySide6.QtWebChannel import QWebChannel  # noqa: E402
from PySide6.QtWebEngineCore import (  # noqa: E402
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
)
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
)

from l_qframelesswindow import L_FramelessMainWindow  # noqa: E402

from .bridge import Bridge  # noqa: E402

DEFAULT_URL = "http://127.0.0.1:1027"
PAGES = [
    ("🗂 版本库", "/baidu/depot"),
    ("📁 文件管理", "/baidu/files"),
    ("🔀 传输列表", "/baidu/transfer"),
    ("☁️ 网盘首页", "/baidu/"),
]

_NAV_QSS = """
QPushButton#navBtn {
    color: #E8EAED; background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.10); border-radius: 7px;
    padding: 0 11px; min-height: 24px; max-height: 24px; font-size: 12px;
}
QPushButton#navBtn:hover   { border-color: #5b9cff; color: #ffffff; }
QPushButton#navBtn:checked { border-color: #5b9cff; color: #5b9cff;
                             background: rgba(91,156,255,0.14); }
QPushButton#iconBtn {
    color: #E8EAED; background: transparent;
    border: 1px solid rgba(255,255,255,0.10); border-radius: 7px;
    min-width: 26px; max-width: 26px; min-height: 24px; max-height: 24px; font-size: 12px;
}
QPushButton#iconBtn:hover     { border-color: #5b9cff; color: #ffffff; }
QPushButton#iconBtn:disabled  { color: rgba(255,255,255,0.25); }
QLabel#userChip {
    color: rgba(255,255,255,0.62); font-size: 11.5px; padding: 0 8px;
    border: 1px solid rgba(255,255,255,0.10); border-radius: 999px; min-height: 22px;
}
"""

# 页面里用 window.lugwitBridge 做特性检测；浏览器中该对象不存在。
_INJECT_JS = """
(function () {
  if (typeof QWebChannel === 'undefined') return;
  new QWebChannel(qt.webChannelTransport, function (channel) {
    window.lugwitBridge = channel.objects.bridge;
    window.dispatchEvent(new Event('lugwit-bridge-ready'));
  });
})();
"""

# 标题栏用户名从页面里捞：三个页面各自的登录标识元素不同，挨个试。
_WHOAMI_JS = """
(function () {
  var ids = ['ownerLabel', 'userLabel'];
  for (var i = 0; i < ids.length; i++) {
    var e = document.getElementById(ids[i]);
    if (e && e.innerText.trim()) return e.innerText.trim();
  }
  return '';
})()
"""


def _make_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#5b9cff"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 14, 14)
    p.setPen(QColor("white"))
    f = p.font()
    f.setPointSize(30)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, "云")
    p.end()
    return QIcon(pm)


class MainWindow(L_FramelessMainWindow):
    """无边框外壳：标题栏放页面导航，内容区是整块网页。"""

    def __init__(self, base_url: str, page: str) -> None:
        super().__init__(vertical_threshold=820)
        self.base_url = base_url.rstrip("/")
        self.setWindowTitle("Lugwit 网盘")
        self.resize(1360, 860)
        self.setMinimumSize(900, 560)
        self.setWindowIcon(_make_icon())
        self.setStyleSheet(self.styleSheet() + _NAV_QSS)

        doc_dir = Path(__file__).resolve().parent / "doc"
        if doc_dir.is_dir():
            self.setHelpDocumentDir(str(doc_dir))

        profile_dir = Path.home() / ".lugwit" / "netdisk_client" / "webprofile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        self.profile = QWebEngineProfile("lugwit_netdisk", self)
        self.profile.setPersistentStoragePath(str(profile_dir))
        self.profile.setCachePath(str(profile_dir / "cache"))
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.ForcePersistentCookies
        )

        self.view = QWebEngineView(self)
        # 必须显式建 page 绑定自定义 profile，否则 view 用的是默认 profile，
        # 上面那份持久化 cookie 配置形同虚设（登录态每次重启都丢）。
        page_obj = QWebEnginePage(self.profile, self.view)
        self.view.setPage(page_obj)
        self.bridge = Bridge(self)
        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", self.bridge)
        page_obj.setWebChannel(self.channel)

        script = QWebEngineScript()
        script.setName("lugwit_bridge")
        script.setInjectionPoint(QWebEngineScript.DocumentCreation)
        script.setWorldId(QWebEngineScript.MainWorld)
        script.setRunsOnSubFrames(False)
        script.setSourceCode(_qwebchannel_js() + _INJECT_JS)
        page_obj.scripts().insert(script)

        page_obj.renderProcessTerminated.connect(self._on_render_dead)
        self.view.loadFinished.connect(self._on_load)

        self._build_titlebar()
        self.setContentWidget(self.view)
        self.goto(page)

    # ── 标题栏 ──
    def _build_titlebar(self) -> None:
        self._nav_btns: dict[str, QPushButton] = {}
        nav: list[QPushButton] = []
        for label, path in PAGES:
            b = QPushButton(label)
            b.setObjectName("navBtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(self.base_url + path)
            b.clicked.connect(lambda _c=False, p=path: self.goto(p))
            self._nav_btns[path] = b
            nav.append(b)
        self.setStartWidgets(nav)

        self.btn_back = self._icon_btn("◀", "后退", self.view.back)
        self.btn_fwd = self._icon_btn("▶", "前进", self.view.forward)
        self.btn_reload = self._icon_btn("⟳", "重新加载 (F5)", self.view.reload)
        self.user_chip = QLabel("👤 未登录")
        self.user_chip.setObjectName("userChip")
        self.user_chip.setAlignment(Qt.AlignCenter)
        self.setEndWidgets(
            [self.btn_back, self.btn_fwd, self.btn_reload, self.user_chip]
        )

        hist = self.view.history()
        self.view.urlChanged.connect(
            lambda _u: (
                self.btn_back.setEnabled(hist.canGoBack()),
                self.btn_fwd.setEnabled(hist.canGoForward()),
            )
        )
        self.btn_back.setEnabled(False)
        self.btn_fwd.setEnabled(False)

    def _icon_btn(self, text: str, tip: str, slot) -> QPushButton:  # noqa: ANN001
        b = QPushButton(text)
        b.setObjectName("iconBtn")
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    def goto(self, page: str) -> None:
        self._mark_nav(page)
        self.view.load(QUrl(self.base_url + page))

    def _mark_nav(self, path: str) -> None:
        """最长前缀命中才算——否则 /baidu/depot 会把 /baidu/ 也点亮。"""
        best = ""
        for p in self._nav_btns:
            if path == p or path.startswith(p.rstrip("/") + "/"):
                if len(p) > len(best):
                    best = p
        for p, b in self._nav_btns.items():
            b.setChecked(p == best)

    def _on_load(self, ok: bool) -> None:
        if not ok:
            self.setWindowTitle("Lugwit 网盘 — 打不开服务，确认 lugwit_auth 已启动")
            return
        self.setWindowTitle(f"Lugwit 网盘 — {self.view.title()}")
        self._mark_nav(self.view.url().path() or "/")
        # 用户名是页面 JS 拉完接口才填上的，loadFinished 时还是占位符，得等一下再问
        self._who_tries = 4
        QTimer.singleShot(900, self._ask_whoami)

    def _ask_whoami(self) -> None:
        self.view.page().runJavaScript(_WHOAMI_JS, self._on_whoami)

    def _on_whoami(self, who) -> None:  # noqa: ANN001
        text = str(who or "").strip()
        if text and text not in ("👤 —", "👤", "—"):
            self.user_chip.setText(text)
            return
        self._who_tries -= 1
        if self._who_tries > 0:
            QTimer.singleShot(1200, self._ask_whoami)
        else:
            self.user_chip.setText("👤 未登录")

    def _on_render_dead(self, status, code) -> None:  # noqa: ANN001
        QMessageBox.warning(self, "渲染进程退出", f"status={status} code={code}\n将尝试重新加载。")
        self.view.reload()

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802
        """关窗只隐藏，保持托盘常驻。"""
        event.ignore()
        self.hide()

    def show_from_hotkey(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()


def _qwebchannel_js() -> str:
    """Qt 自带的 qwebchannel.js（qrc 里那份取不到时退化为空串）。"""
    from PySide6.QtCore import QFile, QIODevice

    f = QFile(":/qtwebchannel/qwebchannel.js")
    if not f.open(QIODevice.ReadOnly):
        return ""
    try:
        return bytes(f.readAll().data()).decode("utf-8")
    finally:
        f.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lugwit 网盘 PC 客户端")
    parser.add_argument("--url", default=DEFAULT_URL, help="lugwit_auth 服务地址")
    parser.add_argument("--page", default="/baidu/depot", help="启动页")
    parser.add_argument("--minimized", action="store_true", help="启动即最小化到托盘")
    args = parser.parse_args(argv)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    win = MainWindow(args.url, args.page)
    if not args.minimized:
        win.show()

    tray = QSystemTrayIcon(_make_icon(), app)
    tray.setToolTip("Lugwit 网盘")
    menu = QMenu()
    for label, path in PAGES:
        act = QAction(label, menu)
        act.triggered.connect(
            lambda _c=False, p=path: (win.goto(p), win.show_from_hotkey())
        )
        menu.addAction(act)
    menu.addSeparator()
    act_reload = QAction("🔄 重新加载", menu)
    act_reload.triggered.connect(win.view.reload)
    menu.addAction(act_reload)
    act_quit = QAction("退出", menu)
    act_quit.triggered.connect(app.quit)
    menu.addAction(act_quit)
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: win.show_from_hotkey()
        if reason == QSystemTrayIcon.Trigger
        else None
    )
    tray.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
