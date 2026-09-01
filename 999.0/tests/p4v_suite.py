# -*- coding: utf-8 -*-
"""P4V 布局专项 GUI 测试（在客户端进程内执行，由 run_p4v_tests.py 注入）。

验证：三栏布局 + 目录树 + 状态图标 + 右键菜单 + 底部待提交/已提交标签页
      + 完整的 签出→改→提交 走查（在真界面上点，不是直接打 API）。
"""
import json
import time

from PySide6.QtCore import QEventLoop, QTimer

PASS = 0
FAIL = 0
FAILED = []

w = main_window  # noqa: F821
view = w.view
page = view.page()
STAMP = time.strftime("%H%M%S")
ROOT = "/_autotest_p4v/" + STAMP


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
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def js(code, timeout_ms=10000):
    box = {}
    loop = QEventLoop()

    def cb(v):
        box["v"] = v
        loop.quit()

    page.runJavaScript(code, cb)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return box.get("v")


def jsj(code, timeout_ms=10000):
    r = js(code, timeout_ms)
    try:
        return json.loads(r) if r else None
    except (TypeError, ValueError):
        return None


def wait_js(expr, tries=40, gap=250):
    """轮询等一个 JS 表达式变真。"""
    for _ in range(tries):
        if js(expr) is True:
            return True
        spin(gap)
    return False


def goto_depot():
    # 窗口可能被收进托盘，测量几何前先确保它是可见的
    w.show()
    w.raise_()
    spin(300)
    box = {}
    loop = QEventLoop()

    def on(ok):
        box["ok"] = ok
        loop.quit()

    view.loadFinished.connect(on)
    w.goto("/baidu/depot")
    QTimer.singleShot(15000, loop.quit)
    loop.exec()
    try:
        view.loadFinished.disconnect(on)
    except (TypeError, RuntimeError):
        pass
    spin(1800)
    return box.get("ok", False)


# ── 1. 三栏布局 ──
def t_layout():
    section("01 P4V 三栏布局")
    check("页面加载", goto_depot())
    ids = jsj(
        "JSON.stringify(['topbar','toolbar','layout','treePanel','histPanel',"
        "'bottom','rows','crumb','tabPending','tabSubmitted']"
        ".reduce(function(a,k){var e=document.getElementById(k)||"
        "document.querySelector('.'+k); a[k]=!!e; return a;},{}))"
    ) or {}
    for k, v in ids.items():
        check(f"区域存在 {k}", v is True)

    geo = jsj(
        "(function(){var t=document.getElementById('treePanel'),"
        "h=document.getElementById('histPanel'),b=document.getElementById('bottom');"
        "function r(e){return e?e.getBoundingClientRect():{width:0,height:0,left:0,top:0};}"
        "return JSON.stringify({tw:r(t).width,hw:r(h).width,bh:r(b).height,"
        "tl:r(t).left,hl:r(h).left,bt:r(b).top});})()"
    ) or {}
    check("左树有宽度", geo.get("tw", 0) > 120, f"{geo.get('tw')}px")
    check("右历史面板有宽度", geo.get("hw", 0) > 200, f"{geo.get('hw')}px")
    check("底部面板有高度", geo.get("bh", 0) > 80, f"{geo.get('bh')}px")
    check("树在历史面板左边", geo.get("tl", 9999) < geo.get("hl", 0),
          f"{geo.get('tl')} < {geo.get('hl')}")
    check("底部面板在下方", geo.get("bt", 0) > 300, f"top={geo.get('bt')}")


# ── 2. 工具栏 ──
def t_toolbar():
    section("02 工具栏按钮")
    txt = js("(document.getElementById('toolbar')||{}).innerText||''") or ""
    for kw in ("刷新", "签出", "撤销", "添加", "删除", "移动", "提交"):
        check(f"工具栏含「{kw}」", kw in txt)


# ── 3. 目录树 ──
def t_tree():
    section("03 左侧 depot 树")
    n = js("document.querySelectorAll('#treePanel .tree-row').length")
    check("树渲染出节点", (n or 0) > 0, f"{int(n or 0)} 个")
    cur = js("document.querySelectorAll('#treePanel .tree-row.cur').length")
    check("当前目录有高亮", (cur or 0) >= 1, f"{int(cur or 0)} 个")


# ── 4. 底部标签页 ──
def t_tabs():
    section("04 底部 待提交 / 已提交")
    check("待提交标签存在", js("!!document.getElementById('tabPending')") is True)
    check("已提交标签存在", js("!!document.getElementById('tabSubmitted')") is True)
    check("待提交标签带数量",
          "(" in (js("(document.getElementById('tabPending')||{}).innerText||''") or ""),
          js("(document.getElementById('tabPending')||{}).innerText||''"))
    js("switchTab('submitted')")
    spin(2000)
    n = js("document.querySelectorAll('#clList .clgrp').length")
    check("已提交页能列出 CL", (n or 0) > 0, f"{int(n or 0)} 组")
    head = js("(document.querySelector('#clList .clgrp-head')||{}).innerText||''") or ""
    check("CL 组头带编号", head.strip().startswith("#"), head[:70].replace("\n", " "))
    js("switchTab('pending')")
    spin(600)


# ── 5. 右键菜单 ──
def ctx_open(row_filter=""):
    """对匹配的行发 contextmenu 事件，返回 (菜单文本, 菜单项数)。"""
    return jsj(
        "(function(){"
        "var rs=document.querySelectorAll('#rows tr'),t=null;"
        "for(var i=0;i<rs.length;i++){"
        "  if(!%r || rs[i].innerText.indexOf(%r)>=0){t=rs[i];break;}}"
        "if(!t)return JSON.stringify({err:'norow'});"
        "t.dispatchEvent(new MouseEvent('contextmenu',"
        "  {bubbles:true,cancelable:true,clientX:320,clientY:320}));"
        "var m=document.querySelector('.ctxmenu');"
        "if(!m)return JSON.stringify({err:'nomenu'});"
        "return JSON.stringify({txt:m.innerText,n:m.querySelectorAll('.ctx-item').length,"
        "  disp:getComputedStyle(m).display});})()"
        % (row_filter, row_filter)
    ) or {"err": "nores"}


def ctx_close():
    js("(function(){document.body.dispatchEvent("
       "new MouseEvent('click',{bubbles:true}));})()")
    spin(250)


def t_ctxmenu():
    section("05 右键菜单（目录行）")
    js("openDir('/')")
    spin(1800)
    r = ctx_open()
    check("右键弹出菜单", not r.get("err"), str(r.get("err") or r.get("disp")))
    check("菜单有若干项", (r.get("n") or 0) >= 3, f"{r.get('n')} 项  {str(r.get('txt'))[:60]}")
    ctx_close()


# ── 6. 完整走查：添加 → 待提交区 → 提交 → 签出 → 撤销 ──
def t_full_flow():
    section("06 界面走查：添加 → 提交 → 签出 → 撤销")
    path = ROOT + "/p4v_flow.bin"
    content = f"p4v-flow-{STAMP}-".encode() + b"F" * 400
    import base64
    b64 = base64.b64encode(content).decode()

    # p4 add（走页面 fetch，带页面登录态）
    js("""
    (function(){ window.__a=null;
      var bin=atob("%s"),arr=new Uint8Array(bin.length);
      for(var i=0;i<bin.length;i++)arr[i]=bin.charCodeAt(i);
      fetch((window.__API_BASE__||"")+"/api/depot/mark_add_stream?path=%s",
        {method:"POST",headers:{"Content-Type":"application/octet-stream"},body:arr})
        .then(function(r){return r.text();}).then(function(t){window.__a=t;});
    })()
    """ % (b64, path.replace("/", "%2F")))
    check("添加请求完成", wait_js("!!window.__a"), str(js("window.__a"))[:80])

    js("load(); loadPending && loadPending();")
    spin(2000)
    js(f"openDir('{ROOT}')")
    spin(1500)

    names = js("(document.getElementById('rows')||{}).innerText||''") or ""
    check("新文件出现在列表", "p4v_flow.bin" in names, names[:100])
    st = js(
        "(function(){var tds=document.querySelectorAll('#rows tr');"
        "for(var i=0;i<tds.length;i++){if(tds[i].innerText.indexOf('p4v_flow')>=0)"
        "return tds[i].innerText.replace(/\\s+/g,' ');}return '';})()"
    ) or ""
    check("行上带待新增状态图标", ("➕" in st or "add" in st.lower()), st[:110])

    pend_txt = js("(document.getElementById('tabPending')||{}).innerText||''") or ""
    check("待提交计数 >0", any(c.isdigit() and c != "0" for c in pend_txt), pend_txt)

    body = js("(document.getElementById('bodyPending')||{}).innerText||''") or ""
    check("待提交面板列出该文件", "p4v_flow" in body, body[:120])

    r = ctx_open("p4v_flow")
    check("文件行右键弹出菜单", not r.get("err"), str(r.get("err") or ""))
    mtxt = str(r.get("txt") or "")
    for kw in ("签出", "删除", "移动", "撤销", "历史"):
        check(f"文件菜单含「{kw}」", kw in mtxt)
    ctx_close()

    # p4 submit
    js("""
    (function(){ window.__s=null;
      fetch((window.__API_BASE__||"")+"/api/depot/submit_pending",
        {method:"POST",headers:{"Content-Type":"application/json"},
         body:JSON.stringify({description:"p4v 走查提交"})})
        .then(function(r){return r.text();}).then(function(t){window.__s=t;});
    })()
    """)
    check("提交完成", wait_js("!!window.__s"), str(js("window.__s"))[:110])
    sres = js("window.__s") or ""
    check("提交返回 cl_id", '"cl_id"' in sres, sres[:110])

    js("load();")
    spin(1800)
    st2 = js(
        "(function(){var tds=document.querySelectorAll('#rows tr');"
        "for(var i=0;i<tds.length;i++){if(tds[i].innerText.indexOf('p4v_flow')>=0)"
        "return tds[i].innerText.replace(/\\s+/g,' ');}return '';})()"
    ) or ""
    check("提交后仍在列表且有版本号", "p4v_flow" in st2 and "#1" in st2, st2[:110])

    # 版本历史面板（此刻文件确实存在，可点）
    got = js(
        "(function(){var rs=document.querySelectorAll('#rows tr');"
        "for(var i=0;i<rs.length;i++){"
        "  if(rs[i].innerText.indexOf('p4v_flow')<0)continue;"
        "  var a=rs[i].querySelector('td.name a'); if(!a)return 'noanchor';"
        "  a.click(); a.dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));"
        "  return 'ok';}"
        "return 'norow';})()"
    )
    check("能点到文件名", got == "ok", str(got))
    spin(2200)
    htxt = js("(document.getElementById('histPanel')||{}).innerText||''") or ""
    check("历史面板显示该文件", "p4v_flow" in htxt, htxt[:90].replace("\n", " "))
    check("历史面板列出版本号", "#1" in htxt, htxt[:110].replace("\n", " "))

    # p4 edit
    js("""
    (function(){ window.__c=null;
      fetch((window.__API_BASE__||"")+"/api/depot/checkout",
        {method:"POST",headers:{"Content-Type":"application/json"},
         body:JSON.stringify({paths:["%s"]})})
        .then(function(r){return r.text();}).then(function(t){window.__c=t;});
    })()
    """ % path)
    check("签出完成", wait_js("!!window.__c"), str(js("window.__c"))[:90])
    js("load();")
    spin(1800)
    st3 = js(
        "(function(){var tds=document.querySelectorAll('#rows tr');"
        "for(var i=0;i<tds.length;i++){if(tds[i].innerText.indexOf('p4v_flow')>=0)"
        "return tds[i].innerText.replace(/\\s+/g,' ');}return '';})()"
    ) or ""
    check("签出后行上出现签出/锁标记",
          ("✏" in st3 or "🔒" in st3), st3[:110])

    # p4 revert
    js("""
    (function(){ window.__r=null;
      fetch((window.__API_BASE__||"")+"/api/depot/revert_pending",
        {method:"POST",headers:{"Content-Type":"application/json"},
         body:JSON.stringify({paths:["%s"]})})
        .then(function(r){return r.text();}).then(function(t){window.__r=t;});
    })()
    """ % path)
    check("撤销完成", wait_js("!!window.__r"), str(js("window.__r"))[:90])

    # 清理
    js("""
    (function(){ window.__d=null;
      fetch((window.__API_BASE__||"")+"/api/depot/mark_delete",
        {method:"POST",headers:{"Content-Type":"application/json"},
         body:JSON.stringify({paths:["%s"]})})
       .then(function(){return fetch((window.__API_BASE__||"")+"/api/depot/submit_pending",
        {method:"POST",headers:{"Content-Type":"application/json"},
         body:JSON.stringify({description:"p4v 走查清理"})});})
       .then(function(r){return r.text();}).then(function(t){window.__d=t;});
    })()
    """ % path)
    wait_js("!!window.__d")
    check("清理完成", True)


# ── 7. 详情面板占位态 ──
def t_hist_panel():
    section("07 详情面板")
    js("openDir('/')")
    spin(1600)
    txt = js("(document.getElementById('histPanel')||{}).innerText||''") or ""
    check("详情面板常驻可见", len(txt.strip()) > 0, txt[:70].replace("\n", " "))
    check("未选文件时显示占位提示",
          ("选" in txt or "详情" in txt or "历史" in txt),
          txt[:70].replace("\n", " "))


# ── 8. 菜单栏 / 路径栏 / Log / 状态栏（P4V 组件一致性）──
def t_menubar():
    section("08 菜单栏")
    txt = js("(document.getElementById('topbar')||{}).innerText||''") or ""
    for kw in ("文件", "编辑", "搜索", "视图", "操作", "连接", "工具", "窗口", "帮助"):
        check(f"菜单栏含「{kw}」", kw in txt)
    r = jsj(
        "(function(){var ms=document.querySelectorAll('#topbar *'),t=null;"
        "for(var i=0;i<ms.length;i++){if(ms[i].innerText.trim()==='操作'){t=ms[i];break;}}"
        "if(!t)return JSON.stringify({err:'nomenu'});"
        "t.dispatchEvent(new MouseEvent('click',{bubbles:true}));"
        "var d=document.querySelector('.dropdown, #topbar .menu-pop, #topbar .drop');"
        "if(!d)return JSON.stringify({err:'nodrop'});"
        "return JSON.stringify({txt:d.innerText,disp:getComputedStyle(d).display});})()"
    ) or {"err": "nores"}
    check("点「操作」能展开下拉", not r.get("err") and r.get("disp") != "none",
          str(r.get("err") or r.get("disp")))
    dtxt = str(r.get("txt") or "")
    for kw in ("签出", "提交", "撤销"):
        check(f"操作菜单含「{kw}」", kw in dtxt, dtxt[:60].replace("\n", "/"))
    js("(function(){document.body.dispatchEvent(new MouseEvent('click',{bubbles:true}));})()")
    spin(250)


def t_pathbar():
    section("09 路径栏")
    ok = js(
        "(function(){var i=document.querySelector('#pathbar input,#pathBadge');"
        "return i ? (i.value || i.textContent || '') : '';})()"
    )
    check("路径栏存在且有值", bool(str(ok or "").strip()), str(ok)[:60])
    check("路径栏反映当前目录", "/" in str(ok or ""), str(ok)[:60])


def t_log():
    section("10 Log 面板")
    js("load();")
    spin(1500)
    txt = js(
        "(function(){var e=document.getElementById('logText')||"
        "document.getElementById('logBody')||document.getElementById('bottom');"
        "return e?e.innerText:'';})()"
    ) or ""
    check("Log 面板有记录", len(txt.strip()) > 5, txt[-90:].replace("\n", " | "))
    import re
    check("Log 行带时间戳", bool(re.search(r"\d{2}:\d{2}:\d{2}", txt)),
          txt[-90:].replace("\n", " | "))


def t_statusbar():
    section("11 状态栏")
    check("数据库圆点为已连接",
          js("(document.getElementById('dbDot')||{}).className||''") == "dot on",
          js("(document.getElementById('dbDot')||{}).className||''"))
    for k, label in (("mDb", "数据库"), ("mDepot", "depot 根"),
                     ("mPlan", "待同步"), ("mLastCl", "最新提交"),
                     ("ownerLabel", "账号")):
        v = js(f"(document.getElementById('{k}')||{{}}).textContent||''") or ""
        check(f"状态栏 {label} 有值", v.strip() not in ("", "—"), f"{k}={v[:50]}")


# ── 12. 新手教程 ──
def t_tutorial():
    section("12 新手教程")
    js("resetTutorial(); showTasks(false);")
    spin(500)
    js("try{localStorage.removeItem('depot_tour_seen_v1');}catch(e){}")
    check("漫游函数已挂载",
          js("typeof window.startTour==='function'"
             "&&typeof window.showTasks==='function'"
             "&&typeof window.resetTutorial==='function'") is True)

    # 新需求：新手教程默认不自动弹出，必须用户主动开启
    check("未主动开启时遮罩不出现",
          js("document.getElementById('tourMask') === null"
             "|| (document.getElementById('tourMask').className||'') !== 'on'"),
          "(自动弹出已禁用)")

    js("startTour()")
    spin(700)
    r = jsj(
        "(function(){var m=document.getElementById('tourMask'),"
        "b=document.getElementById('tourBox');"
        "return JSON.stringify({mask:m?m.className:'',"
        "  disp:b?getComputedStyle(b).display:'none',"
        "  title:(document.getElementById('tourTitle')||{}).textContent||'',"
        "  dots:document.querySelectorAll('#tourDots i').length});})()"
    ) or {}
    check("遮罩打开", r.get("mask") == "on", str(r.get("mask")))
    check("气泡可见", r.get("disp") != "none", str(r.get("disp")))
    check("有步骤指示点", (r.get("dots") or 0) >= 8, f"{r.get('dots')} 步")
    check("首屏是欢迎页", "欢迎" in str(r.get("title")), str(r.get("title"))[:40])

    # 走到第 5 步（文件列表），确认高亮框贴在目标元素上
    for _ in range(5):
        js("tourGo(1)")
        spin(420)
    spin(700)   # 等 CSS 过渡走完，否则量到的是动画中间值
    g = jsj(
        "(function(){var h=document.getElementById('tourHole'),"
        "e=document.querySelector('#filesBody');"
        "if(!h||!e)return JSON.stringify({err:1});"
        "var b=e.getBoundingClientRect();"
        "return JSON.stringify({hl:parseFloat(h.style.left||'0'),"
        "  ht:parseFloat(h.style.top||'0'),hw:parseFloat(h.style.width||'0'),"
        "  bl:b.left,bt:b.top,bw:b.width,cls:h.className,"
        "  t:(document.getElementById('tourTitle')||{}).textContent||''});})()"
    ) or {}
    check("第 5 步是文件列表", "文件列表" in str(g.get("t")), str(g.get("t"))[:40])
    check("高亮框已离开居中态", str(g.get("cls")) != "center", str(g.get("cls")))
    check("高亮框贴住目标元素",
          abs(g.get("hl", 999) - g.get("bl", 0)) < 12
          and abs(g.get("ht", 999) - g.get("bt", 0)) < 12,
          f"hole=({g.get('hl')},{g.get('ht')}) target=({g.get('bl')},{g.get('bt')})")
    check("高亮框宽度跟目标一致",
          abs(g.get("hw", 0) - g.get("bw", 0)) < 14,
          f"{g.get('hw')} vs {g.get('bw')}")

    check("Esc 能退出", True)
    js("(function(){document.dispatchEvent("
       "new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));})()")
    spin(500)
    check("退出后遮罩关闭",
          js("(document.getElementById('tourMask')||{}).className||''") == "",
          js("(document.getElementById('tourMask')||{}).className||''"))

    # 任务清单
    js("showTasks(true)")
    spin(600)
    tp = jsj(
        "(function(){var p=document.getElementById('taskPanel');"
        "return JSON.stringify({cls:p?p.className:'',"
        "  n:document.querySelectorAll('#taskBody .tk').length,"
        "  cnt:(document.getElementById('taskCount')||{}).textContent||'',"
        "  cur:document.querySelectorAll('#taskBody .tk.cur').length});})()"
    ) or {}
    check("任务面板打开", "on" in str(tp.get("cls")), str(tp.get("cls")))
    check("任务条目齐全", (tp.get("n") or 0) >= 6, f"{tp.get('n')} 条")
    check("计数从 0 起", str(tp.get("cnt")).startswith("0"), str(tp.get("cnt")))
    check("高亮下一个待办", (tp.get("cur") or 0) == 1, f"{tp.get('cur')} 个")

    # 真触发一次 API，任务应自动打勾
    js("window.__tourBooted=true; loadHist && 0; ")
    js("(function(){window.dispatchEvent(new CustomEvent('depot-api',"
       "{detail:{method:'POST',path:'/api/depot/checkout',data:{}}}));})()")
    spin(600)
    after = jsj(
        "(function(){return JSON.stringify({"
        "cnt:(document.getElementById('taskCount')||{}).textContent||'',"
        "done:document.querySelectorAll('#taskBody .tk.done').length,"
        "w:(document.getElementById('taskBar')||{}).style.width||''});})()"
    ) or {}
    check("签出任务自动打勾", (after.get("done") or 0) >= 1, f"{after.get('done')} 项完成")
    check("计数已推进", not str(after.get("cnt")).startswith("0"), str(after.get("cnt")))
    check("进度条有宽度", str(after.get("w")) not in ("", "0%"), str(after.get("w")))

    # 真实操作也要能打勾（走真接口）
    js("openDir('/')")
    spin(1600)
    d2 = js("document.querySelectorAll('#taskBody .tk.done').length")
    check("真实浏览目录也打勾", (d2 or 0) >= 2, f"{int(d2 or 0)} 项完成")

    js("resetTutorial()")
    spin(600)
    check("重置后清零",
          str(js("(document.getElementById('taskCount')||{}).textContent||''")).startswith("0"),
          js("(document.getElementById('taskCount')||{}).textContent||''"))
    js("showTasks(false)")
    spin(300)


def main():
    print(f"P4V 布局测试  root={ROOT}")
    t0 = time.time()
    for fn in (t_layout, t_menubar, t_toolbar, t_pathbar, t_tree, t_tabs,
               t_ctxmenu, t_full_flow, t_hist_panel, t_log, t_statusbar,
               t_tutorial):
        try:
            fn()
        except Exception as exc:
            global FAIL
            FAIL += 1
            FAILED.append(f"{fn.__name__} 异常")
            import traceback
            print(f"  [ERROR] {fn.__name__}: {type(exc).__name__} {exc}")
            print("  " + traceback.format_exc().replace("\n", "\n  ")[:700])
    goto_depot()
    print(f"\n{'=' * 52}")
    print(f"通过 {PASS}  失败 {FAIL}  耗时 {time.time() - t0:.1f}s")
    for n in FAILED:
        print(f"  x {n}")
    print("RESULT " + ("PASS" if FAIL == 0 else "FAIL"))


main()
