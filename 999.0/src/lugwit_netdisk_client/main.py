# -*- coding: utf-8 -*-
"""Lugwit 网盘 PC 客户端主程序。

无边框标题栏（l_qframelesswindow，与 l_notepad 同一套外壳）+ QWebEngineView
承载现成网页（/baidu/depot、/baidu/files、/baidu/transfer）。
页面一套两用：浏览器直接访问，客户端里通过 QWebChannel 额外拿到本地能力。

启动：
    wuwor lugwit_netdisk_client -- netdisk_client
    wuwor lugwit_netdisk_client -- netdisk_client --url http://127.0.0.1:8080 --page /baidu/files
"""
from __future__ import annotations


from l_app_ready.paths import pkg_data_dir as _lugwit_pkg_root
import argparse
import os
import sys
from pathlib import Path

from . import qt_boot

qt_boot.setup()  # 必须在 import PySide6 之前

from PySide6.QtCore import QDateTime, QFileSystemWatcher, QObject, QTimer, QUrl, Qt, Slot  # noqa: E402
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPainter, QPixmap, QShortcut  # noqa: E402
from PySide6.QtWebChannel import QWebChannel  # noqa: E402
from PySide6.QtWebEngineCore import (  # noqa: E402
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
)
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
)

from l_qframelesswindow import L_FramelessMainWindow  # noqa: E402
from l_qframelesswindow import LoginStore  # noqa: E402
from l_qframelesswindow import ServerConfigStore  # noqa: E402
from l_qframelesswindow.login_store import verify_token  # noqa: E402

from .bridge import Bridge  # noqa: E402

def _default_url() -> str:
    """统一入口：开发机走本机 nginx，公网部署机走域名（兜底服务器 IP）。

    nginx 同时提供 /baidu/（反代网盘服务 :1028）与 /api/v1/（认证服务 :1027），
    页面与接口同源，cookie 才带得过去。

    注意别指到 1027：那是 lugwit_auth 自己的端口，只有 auth 进程内 mount 了
    /baidu 子应用才有该路径（见 lugwit_auth/auth_server.py 的 _mount_baidu_netdisk），
    开发机默认没 mount，直连会 404 → 页面打不开。
    """
    if os.environ.get("Lugwit_deploy", "0").strip().lower() in ("1", "true", "yes", "on"):
        return os.environ.get("LUGWIT_DOMAIN_URL") or "https://121.196.144.88"
    return "http://127.0.0.1:8080"


DEFAULT_URL = _default_url()
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

def _hot_reload_enabled() -> bool:
    """页面热重载开关（默认开；LUGWIT_NETDISK_HOT_RELOAD=0 关掉）。"""
    return os.environ.get("LUGWIT_NETDISK_HOT_RELOAD", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def _page_watch_dirs() -> list[Path]:
    """监听哪些目录的页面源文件变化。

    本端承载的是网页（`lugwit_baidu_netdisk` 服务发的 HTML），改页面后不想重启客户端。
    优先用显式环境变量 `LUGWIT_NETDISK_WATCH_DIRS`（`os.pathsep` 分隔）；否则按 rez
    目录约定从兄弟包推：`<rez-package-source>/lugwit_baidu_netdisk/999.0/src/lugwit_baidu_netdisk`。
    """
    raw = os.environ.get("LUGWIT_NETDISK_WATCH_DIRS", "").strip()
    if raw:
        return [Path(p) for p in raw.split(os.pathsep) if p.strip()]

    cands: list[Path] = []
    netdisk_root = os.environ.get("LUGWIT_BAIDU_NETDISK_ROOT", "").strip()
    if netdisk_root:
        cands.append(Path(netdisk_root) / "src" / "lugwit_baidu_netdisk")
    # main.py → lugwit_netdisk_client/ → src/ → 999.0/ → lugwit_netdisk_client/ → rez-package-source/
    me = Path(__file__).resolve()
    if len(me.parents) > 4:
        cands.append(me.parents[4] / "lugwit_baidu_netdisk" / "999.0" / "src"
                     / "lugwit_baidu_netdisk")
    return [p for p in cands if p.is_dir()]


class _PageHotReload(QObject):
    """页面源文件一变就硬刷新承载的网页（开发用）。

    桌面端不是原生 UI，而是 QWebEngineView 里的网页：改 `web_*.html` 后只要让
    WebEngine 绕过缓存重取即可，不必重启客户端。监听目录（编辑器存盘常是
    「写临时文件 + 改名」，监听目录比监听单个文件可靠），400ms 去抖，避免一次保存
    触发多次刷新。
    """

    def __init__(self, reload_cb, watched: list[Path], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._reload_cb = reload_cb
        self._dirs = [str(p) for p in watched]
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_changed)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._reload_cb)
        self._watcher.addPaths(self._dirs)

    @property
    def dirs(self) -> list[str]:
        return list(self._dirs)

    def _on_changed(self, _path: str) -> None:
        self._timer.start()


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

    def __init__(self, base_url: str, page: str, url_explicit: bool = False) -> None:
        super().__init__(vertical_threshold=820)
        self.base_url = base_url.rstrip("/")
        # 显式给了 --url 就尊重它；否则页面基址跟随「服务器设置」（本机/远程）
        self._url_arg = self.base_url
        self._url_explicit = bool(url_explicit)
        self._current_page = page
        self._server_store = None
        self._login_store = None
        self.setWindowTitle("Lugwit 网盘")
        self.resize(1360, 860)
        self.setMinimumSize(900, 560)
        self.setWindowIcon(_make_icon())
        self.setStyleSheet(self.styleSheet() + _NAV_QSS)

        doc_dir = Path(__file__).resolve().parent / "doc"
        if doc_dir.is_dir():
            self.setHelpDocumentDir(str(doc_dir))

        profile_dir = _lugwit_pkg_root("netdisk_client") / "webprofile"
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
        # 把持久化 profile 的 cookie 交给桥：网页里的登录 cookie（lugwit_token）抓到后，
        # 桥就能带着它直连本机 depot 服务取版本库内容（本地获取，不经托盘 / 网关）。
        self.bridge.attachProfile(self.profile)

        script = QWebEngineScript()
        script.setName("lugwit_bridge")
        script.setInjectionPoint(QWebEngineScript.DocumentCreation)
        script.setWorldId(QWebEngineScript.MainWorld)
        script.setRunsOnSubFrames(False)
        script.setSourceCode(_qwebchannel_js() + _INJECT_JS)
        page_obj.scripts().insert(script)

        page_obj.renderProcessTerminated.connect(self._on_render_dead)
        self.view.loadFinished.connect(self._on_load)
        # 右键菜单：QtWebEngine 默认什么都不弹（桌面端右键等于没反应）。
        # 页面内部自己处理 contextmenu 的地方会先吃掉事件，这里只兜底。
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._show_web_menu)

        self._build_titlebar()
        self.setContentWidget(self.view)
        self._setup_server_config()
        self._setup_login()
        self.goto(page)

        # 开发用热重载：改了服务端页面源文件就自动硬刷新，不必重启客户端或手点 ⟳
        self._hot_reload = None
        if _hot_reload_enabled():
            dirs = _page_watch_dirs()
            if dirs:
                self._hot_reload = _PageHotReload(self.hard_reload, dirs, self)
                print("[netdisk_client] 页面热重载已开，监听： "
                      + ", ".join(self._hot_reload.dirs)
                      + "（LUGWIT_NETDISK_HOT_RELOAD=0 关闭）")
            else:
                print("[netdisk_client] 页面热重载未开：没找到页面目录"
                      "（可用 LUGWIT_NETDISK_WATCH_DIRS 指定）")

    # ── 服务器设置（本机 / 远程切换：登录地址与网盘页面一起切）──
    LOCAL_PAGE_BASE = "http://127.0.0.1:8080/baidu"
    REMOTE_PAGE_SUFFIX = "/baidu"

    def _setup_server_config(self) -> None:
        """注入 ServerConfigStore → 标题栏出现 🌐「服务器设置」。

        配置落在客户端自己的数据目录（~/.Lugwit/lugwit_netdisk_client），
        登录对话框按它解析认证地址；保存后经 `serverConfigChanged` 同步切换
        网盘页面基址（本机 → 127.0.0.1:8080/baidu，远程 → 网关/auth_url + /baidu）。
        """
        data_dir = Path.home() / ".Lugwit" / "lugwit_netdisk_client"
        data_dir.mkdir(parents=True, exist_ok=True)
        self._server_store = ServerConfigStore(data_dir=data_dir)
        self.setServerConfigStore(self._server_store)
        self.serverConfigChanged.connect(self._on_server_config_changed)
        self._apply_page_base(reload=False)

    def _page_base_for(self) -> str:
        """按服务器设置解析网盘页面基址。

        - 本机模式 → `LOCAL_PAGE_BASE`（本机 nginx 网关，明文 http，WebEngine 可用）
        - 显式 `--url` → 尊重它
        - 否则跟随 `auth_url`；但若推导出的是 **https 自签**网关，则仍沿用启动参数
          （QtWebEngine 用 Chromium 自有信任库，Python 侧的 ca_bundle 对它无效，
          自签 https 页面会白屏 —— 见 Rez-Docs 证书文档里的已知缺口）
        """
        store = self._server_store
        if store is not None and store.local_mode():
            return self.LOCAL_PAGE_BASE
        if self._url_explicit:
            return self._url_arg
        base = (store.auth_url() if store is not None else "").rstrip("/")
        if not base or base.startswith("https://"):
            return self._url_arg
        return base + self.REMOTE_PAGE_SUFFIX

    def _apply_page_base(self, *, reload: bool = True) -> None:
        """把页面基址切到设置对应的地址（变化时才动，附带刷新导航提示）。"""
        base = self._page_base_for()
        if base == self.base_url:
            return
        self.base_url = base
        for path, btn in self._nav_btns.items():
            btn.setToolTip(self.base_url + path)
        print(f"[netdisk_client] 服务器设置变更 → 网盘页面基址: {self.base_url}")
        if reload:
            self.view.load(QUrl(self.base_url + self._current_page))

    @Slot(dict)
    def _on_server_config_changed(self, cfg: dict) -> None:
        """设置保存后：切页面基址；原登录态对新服务器无效则清掉并重新弹登录窗。"""
        self._apply_page_base(reload=True)
        tok = (self._login_store.load_token() or {}).get("token") if self._login_store else ""
        if not tok or self._server_store is None:
            return
        try:
            valid = verify_token(tok, self._server_store)
        except Exception:  # noqa: BLE001
            return                      # 服务不可达：不动登录态，交给后续操作暴露
        if not valid:
            print("[netdisk_client] 换了服务器，原登录态对该服务器无效 → 清除并重新登录")
            self._login_store.clear_token()
            if self.bridge is not None:
                self.bridge.setToken("")
            self.user_chip.setText("👤 未登录")
            QTimer.singleShot(300, self.showLoginDialog)

    # ── 登录（复用标题栏库能力，和 l_notepad 同一套）──
    def _setup_login(self) -> None:
        """注入 LoginStore → 标题栏出现「登录」按钮；启动未登录则自动弹登录窗。

        登录成功后把 token 注入 WebEngine 的 cookie（`lugwit_token`），
        这样页面本身与桥的 depot 调用都带上了同一份登录态。
        """
        data_dir = Path.home() / ".Lugwit" / "lugwit_netdisk_client"
        data_dir.mkdir(parents=True, exist_ok=True)
        self._login_store = LoginStore(data_dir=data_dir)
        self.setLoginStore(self._login_store, show_button=True, restore=True)
        self.loginSuccess.connect(self._on_login_success)
        self.logoutSuccess.connect(self._on_logout_success)
        # P5：启动即用 SDK 的持久化登录态（DPAPI 里的 refresh）续期出一个可用 access，
        # 注入 cookie + 桥 —— 这样页面（网盘 UI）一打开就带登录态，且 access 过期也能自动续。
        restored = None
        try:
            restored = self._login_store.restore_session(self._server_store)
        except Exception as exc:  # noqa: BLE001
            print(f"[netdisk_client] 恢复登录态失败（需重新登录）: {exc}")
        if restored:
            token, _username = restored
            self._set_token_cookie(token)
            print("[netdisk_client] 启动即注入续期后的登录态（cookie + 桥）")
        else:
            # 没有持久化登录态 → 启动时直接弹登录窗（有则让 restoreSavedLogin 静默恢复）
            QTimer.singleShot(400, self.showLoginDialog)

    def _set_token_cookie(self, token: str) -> None:
        """把 token 写进 WebEngine 的 `lugwit_token` cookie（页面与桥共用同一登录态）。

        页面侧 `pageToken()` 读的就是这张 cookie（document.cookie，非 HttpOnly）；
        不注入的话页面的 `/api/depot/*` 会因缺凭据失败（工作区列表走托盘还能显示，
        但文件树会空）。
        """
        from PySide6.QtNetwork import QNetworkCookie

        if self.bridge is not None:
            self.bridge.setToken(token)
        if not token:
            return
        cookie = QNetworkCookie(b"lugwit_token", token.encode("utf-8"))
        cookie.setDomain(QUrl(self.base_url).host())
        cookie.setPath("/")
        self.profile.cookieStore().setCookie(cookie, QUrl(self.base_url))

    @Slot(str, str)
    def _on_login_success(self, token: str, username: str) -> None:
        self._set_token_cookie(token)
        if token:
            print(f"[netdisk_client] 已登录 {username}，token 已注入 WebEngine cookie")
        self.view.reload()

    @Slot()
    def _on_logout_success(self) -> None:
        from PySide6.QtNetwork import QNetworkCookie

        if self.bridge is not None:
            self.bridge.setToken("")
        expired = QNetworkCookie(b"lugwit_token", b"")
        expired.setDomain(QUrl(self.base_url).host())
        expired.setPath("/")
        expired.setExpirationDate(QDateTime.currentDateTime().addSecs(-3600))
        self.profile.cookieStore().setCookie(expired, QUrl(self.base_url))
        self.view.reload()

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
        self.btn_reload = self._icon_btn("⟳", "彻底刷新（绕过缓存，Ctrl+F5）", self.hard_reload)
        # 登录入口不加在这里：框架的 setLoginStore 会在结束区追加内置「登录」按钮
        # （登录后自动显示用户名），此处再加一个会重复。
        self.setEndWidgets([self.btn_back, self.btn_fwd, self.btn_reload])
        QShortcut(QKeySequence("Ctrl+F5"), self, activated=self.hard_reload)

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
        self._current_page = page
        self._mark_nav(page)
        self.view.load(QUrl(self.base_url + page))

    def hard_reload(self) -> None:
        """彻底刷新：绕过 HTTP 缓存重新取页面。

        普通 ``view.reload()`` 会复用缓存里的 HTML/JS，改了页面看不到效果；
        标题栏 ⟳ 与 Ctrl+F5 都走这里。
        """
        action = getattr(QWebEnginePage.WebAction, "ReloadAndBypassCache", None)
        if action is None:  # 枚举没有这一项时退化为普通重新加载
            self.view.reload()
            return
        self.view.page().triggerAction(action)

    def _show_web_menu(self, pos) -> None:  # noqa: ANN001
        """网页右键菜单：用 WebEngine 的标准菜单（后退/前进/刷新/复制/粘贴/另存为…）。

        QtWebEngine 默认一个菜单都不弹，桌面端右键等于没反应；页面里自己做了
        contextmenu 的地方（如版本库的目录/文件右键、其它页的通用右键菜单）会先
        吃掉事件，这里只在页面没处理时兜底。
        """
        maker = getattr(self.view, "createStandardContextMenu", None)
        menu = maker() if maker else None
        if menu is None:  # 老版本没有这个 API：不弹，保持原行为
            return
        menu.exec(self.view.mapToGlobal(pos))
        menu.deleteLater()

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
    parser.add_argument("--url", default=DEFAULT_URL, help="统一入口地址（nginx；默认开发机 8080 / 部署机域名）")
    parser.add_argument("--page", default="/baidu/depot", help="启动页")
    parser.add_argument("--minimized", action="store_true", help="启动即最小化到托盘")
    # 是否显式给了 --url：显式 → 尊重它；否则页面基址跟随「服务器设置」（本机/远程）
    _raw = list(argv) if argv is not None else sys.argv[1:]
    url_explicit = any(a == "--url" or a.startswith("--url=") for a in _raw)
    args = parser.parse_args(argv)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    win = MainWindow(args.url, args.page, url_explicit=url_explicit)
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
    act_reload = QAction("🔄 彻底刷新 (Ctrl+F5)", menu)
    act_reload.triggered.connect(win.hard_reload)
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
