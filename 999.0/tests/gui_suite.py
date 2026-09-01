# -*- coding: utf-8 -*-
"""客户端 GUI 自动测试（在客户端进程内执行）。

不要直接运行这个文件——它靠 l_script_editor 的 8764 接口注入到
运行中的 lugwit_netdisk_client 进程里跑，环境已注入 main_window。

用 tests/run_gui_tests.py 触发。
"""
import json
import time
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer

PASS = 0
FAIL = 0
FAILED = []

w = main_window  # noqa: F821
view = w.view
page = view.page()


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILED.append(name)
        print(f"  [FAIL] {name}  {detail}")
    return cond


def section(t):
    print(f"\n=== {t} ===")


def spin(ms):
    """让 Qt 事件循环转 ms 毫秒，不冻界面。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def run_js(code, timeout_ms=8000):
    """同步拿 runJavaScript 结果。"""
    box = {}
    loop = QEventLoop()

    def cb(v):
        box["v"] = v
        loop.quit()

    page.runJavaScript(code, cb)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return box.get("v")


def goto_wait(path, timeout_ms=15000):
    """切页并等 loadFinished。"""
    box = {}
    loop = QEventLoop()

    def on(ok):
        box["ok"] = ok
        loop.quit()

    view.loadFinished.connect(on)
    w.goto(path)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    try:
        view.loadFinished.disconnect(on)
    except (TypeError, RuntimeError):
        pass
    spin(1200)  # 留给页面 JS 拉接口
    return box.get("ok", False)


# ── 1. 窗口外壳 ──
def t_shell():
    section("01 无边框外壳")
    check("继承 L_FramelessMainWindow",
          any(c.__name__ == "L_FramelessMainWindow" for c in type(w).__mro__))
    for attr in ("helpBtn", "minBtn", "maxBtn", "closeBtn"):
        check(f"内置标题栏按钮 {attr}", hasattr(w, attr))
    check("导航按钮 4 个", len(w._nav_btns) == 4, str(list(w._nav_btns)))
    check("后退/前进/刷新就位",
          all(hasattr(w, x) for x in ("btn_back", "btn_fwd", "btn_reload")))
    check("用户名 chip 存在", hasattr(w, "user_chip"))
    check("内容区是 QWebEngineView", type(view).__name__ == "QWebEngineView")
    check("内容区可见且有尺寸",
          view.isVisible() and view.width() > 200 and view.height() > 200,
          f"{view.width()}x{view.height()}")
    # 注意：注入执行时 __file__ 是临时文件，只能从包本身推导
    import lugwit_netdisk_client
    doc = Path(lugwit_netdisk_client.__file__).resolve().parent / "doc"
    check("帮助文档目录存在", doc.is_dir() and any(doc.glob("*.md")), str(doc))


# ── 2. profile / cookie ──
def t_profile():
    section("02 独立 profile 与登录态持久化")
    prof = page.profile()
    check("view 用的是自定义 profile", prof is w.profile, prof.storageName())
    check("持久化目录已设置", bool(prof.persistentStoragePath()),
          prof.persistentStoragePath())
    from PySide6.QtWebEngineCore import QWebEngineProfile
    check("强制持久化 cookie",
          prof.persistentCookiesPolicy()
          == QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies,
          str(prof.persistentCookiesPolicy()))
    check("持久化目录真实存在", Path(prof.persistentStoragePath()).is_dir())


# ── 3. 四个页面都能打开 ──
def t_pages():
    section("03 四个页面逐个加载")
    expect = {
        "/baidu/depot": "版本库",
        "/baidu/files": "文件管理",
        "/baidu/transfer": "传输",
        "/baidu/": "",
    }
    for path, kw in expect.items():
        ok = goto_wait(path)
        title = view.title()
        check(f"{path} 加载成功", ok, f"title={title!r}")
        checked = [p for p, b in w._nav_btns.items() if b.isChecked()]
        check(f"{path} 导航高亮唯一", len(checked) == 1 and checked[0] == path,
              str(checked))
        body_len = run_js("(document.body.innerText||'').length")
        # JS 的数字回到 Python 是 float，别拿 int 判类型
        check(f"{path} 页面有内容",
              isinstance(body_len, (int, float)) and body_len > 20,
              f"{int(body_len or 0)} 字")


# ── 4. QWebChannel 桥 ──
def t_bridge():
    section("04 QWebChannel 本地能力桥")
    goto_wait("/baidu/depot")
    check("页面侧拿到 lugwitBridge", run_js("!!window.lugwitBridge") is True)

    fns = run_js(
        "JSON.stringify(Object.keys(window.lugwitBridge||{}).filter("
        "function(k){return typeof window.lugwitBridge[k]==='function';}))"
    )
    names = set(json.loads(fns or "[]"))
    for fn in ("platform", "fileMd5", "fileInfo", "listDir", "homeDir",
               "pickFolder", "pickFiles", "revealInExplorer", "openExternal"):
        check(f"桥方法暴露 {fn}", fn in names)

    b = w.bridge
    check("bridge.platform()", "win" in b.platform().lower(), b.platform())
    home = b.homeDir()
    check("bridge.homeDir() 可用", Path(home).is_dir(), home)

    tmp = Path(home) / ".lugwit_bridge_test.txt"
    tmp.write_bytes(b"bridge-selftest-1234567890")
    try:
        import hashlib
        want = hashlib.md5(tmp.read_bytes()).hexdigest()
        check("bridge.fileMd5() 正确", b.fileMd5(str(tmp)) == want, want[:12])
        info = json.loads(b.fileInfo(str(tmp)))
        check("bridge.fileInfo() 返回 size", info.get("size") == tmp.stat().st_size,
              str(info)[:100])
        lst = json.loads(b.listDir(home))
        check("bridge.listDir() 能列目录", isinstance(lst, list) and len(lst) > 0,
              f"{len(lst)} 项")
    finally:
        tmp.unlink(missing_ok=True)

    check("bridge.fileMd5() 对不存在文件不崩",
          b.fileMd5(r"C:\definitely\not\here.bin") == "")


# ── 5. 页面 JS 接口齐全 ──
def t_page_api():
    section("05 版本库页面 JS 函数")
    goto_wait("/baidu/depot")
    for fn in ("load", "openDir", "goUp", "pick", "loadHist", "revert",
               "toggleLock", "submitFiles", "delSelected",
               "moveSelected", "moveDir", "toggleChanges"):
        check(f"页面函数 {fn}", run_js(f"typeof window.{fn} === 'function'") is True)

    meta = run_js(
        "JSON.stringify({dot:(document.getElementById('dbDot')||{}).className,"
        "db:(document.getElementById('mDb')||{}).innerText,"
        "depot:(document.getElementById('mDepot')||{}).innerText,"
        "owner:(document.getElementById('ownerLabel')||{}).innerText})"
    )
    m = json.loads(meta or "{}")
    check("元数据库指示灯为绿", "on" in str(m.get("dot")), str(m.get("dot")))
    check("blob 仓路径显示正确", ".depot" in str(m.get("depot")), str(m.get("depot")))
    check("标题栏显示登录人", bool(str(m.get("owner", "")).strip()), str(m.get("owner")))
    check("客户端 chip 与页面一致",
          str(m.get("owner", "")).strip() in w.user_chip.text()
          or w.user_chip.text() in str(m.get("owner", "")),
          f"{w.user_chip.text()!r} vs {m.get('owner')!r}")


# ── 6. 导航前进后退 ──
def t_history_nav():
    section("06 前进 / 后退")
    goto_wait("/baidu/depot")
    goto_wait("/baidu/files")
    spin(400)
    check("后退按钮已可用", w.btn_back.isEnabled())

    loop = QEventLoop()
    view.loadFinished.connect(lambda _o: loop.quit())
    view.back()
    QTimer.singleShot(12000, loop.quit)
    loop.exec()
    spin(800)
    check("后退回到版本库", view.url().path() == "/baidu/depot", view.url().path())
    check("前进按钮变可用", w.btn_fwd.isEnabled())
    checked = [p for p, b in w._nav_btns.items() if b.isChecked()]
    check("后退后导航高亮跟随", checked == ["/baidu/depot"], str(checked))


# ── 7. 端到端：注入上传 → 页面可见 ──
def t_e2e_submit():
    section("07 端到端：本地文件 → depot → 界面可见")
    goto_wait("/baidu/depot")
    stamp = time.strftime("%H%M%S")
    dpath = f"/_autotest_gui/{stamp}/from_client.txt"
    raw = f"gui-autotest-{stamp}-".encode() + b"Z" * 300

    tmp = Path(w.bridge.homeDir()) / f".gui_autotest_{stamp}.txt"
    tmp.write_bytes(raw)
    try:
        import base64
        import hashlib
        want = hashlib.md5(raw).hexdigest()
        check("客户端算 md5 与本地一致", w.bridge.fileMd5(str(tmp)) == want, want[:12])

        js = """
        (function () {
          window.__t = null;
          var bin = atob("%s"), arr = new Uint8Array(bin.length);
          for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
          fetch((window.__API_BASE__||"") + "/api/depot/submit_stream?path=%s&description=gui_autotest", {
            method:"POST", headers:{"Content-Type":"application/octet-stream"}, body:arr
          }).then(function(r){return r.text().then(function(t){
              window.__t = JSON.stringify({s:r.status,b:t});});})
            .catch(function(e){window.__t = JSON.stringify({s:-1,b:String(e)});});
          return 1;
        })()
        """ % (base64.b64encode(raw).decode(), dpath.replace("/", "%2F"))
        run_js(js)

        res = None
        for _ in range(40):
            spin(300)
            res = run_js("window.__t")
            if res:
                break
        check("提交请求完成", bool(res), str(res)[:80])
        if res:
            d = json.loads(res)
            check("提交返回 200", d["s"] == 200, str(d)[:120])
            body = json.loads(d["b"])
            check("走的真实上传", body["stats"]["uploaded"] == 1, str(body["stats"]))
            check("md5 一致", body["files"][0]["md5"] == want)

        # 界面上能看到
        run_js(f"openDir('/_autotest_gui/{stamp}')")
        spin(2000)
        names = run_js(
            "JSON.stringify(Array.prototype.map.call("
            "document.querySelectorAll('#rows td.name'), function(e){return e.innerText;}))"
        )
        check("新文件出现在界面列表", "from_client.txt" in str(names), str(names)[:120])

        # 清理
        run_js(
            "fetch((window.__API_BASE__||'')+'/api/depot/delete',{method:'POST',"
            "headers:{'Content-Type':'application/json'},"
            "body:JSON.stringify({paths:['%s'],description:'gui_autotest 清理'})})" % dpath
        )
        spin(1500)
    finally:
        tmp.unlink(missing_ok=True)


# ── 8. 健壮性 ──
def t_robust():
    section("08 健壮性")
    ok = goto_wait("/baidu/depot")
    check("恢复到版本库页", ok)
    before = view.url().toString()
    loop = QEventLoop()
    view.loadFinished.connect(lambda _o: loop.quit())
    view.reload()
    QTimer.singleShot(15000, loop.quit)
    loop.exec()
    spin(800)
    check("刷新后 URL 不变", view.url().toString() == before, view.url().toString())
    check("刷新后桥仍在", run_js("!!window.lugwitBridge") is True)
    check("窗口仍然可见", w.isVisible())


def main():
    print("客户端 GUI 自动测试")
    # 窗口可能被收进托盘，几何/可见性断言之前先亮出来
    w.show()
    w.raise_()
    spin(400)
    t0 = time.time()
    for fn in (t_shell, t_profile, t_pages, t_bridge, t_page_api,
               t_history_nav, t_e2e_submit, t_robust):
        try:
            fn()
        except Exception as exc:
            global FAIL
            FAIL += 1
            FAILED.append(f"{fn.__name__} 异常")
            import traceback
            print(f"  [ERROR] {fn.__name__}: {type(exc).__name__} {exc}")
            print("  " + traceback.format_exc().replace("\n", "\n  ")[:900])
    goto_wait("/baidu/depot")
    print(f"\n{'=' * 52}")
    print(f"通过 {PASS}  失败 {FAIL}  耗时 {time.time() - t0:.1f}s")
    for n in FAILED:
        print(f"  x {n}")
    print("RESULT " + ("PASS" if FAIL == 0 else "FAIL"))


main()
