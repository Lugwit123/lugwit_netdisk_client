# -*- coding: utf-8 -*-
"""前端性能体检（在客户端进程内执行，由 run_gui_tests.py --suite perf 注入）。

量四件事：
  1. load() 端到端（含 status / pending / sync_plan 的连带请求）
  2. 纯渲染耗时（render 一屏行）
  3. 大目录渲染（造 N 行假数据，不走网络）
  4. 滚动时的掉帧情况
"""
import json
import time

from PySide6.QtCore import QEventLoop, QTimer

w = main_window  # noqa: F821
view = w.view
page = view.page()


def spin(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def js(code, timeout_ms=30000):
    box = {}
    loop = QEventLoop()

    def cb(v):
        box["v"] = v
        loop.quit()

    page.runJavaScript(code, cb)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return box.get("v")


def jsj(code, timeout_ms=30000):
    try:
        return json.loads(js(code, timeout_ms) or "null")
    except (TypeError, ValueError):
        return None


def wait(expr, tries=120, gap=150):
    for _ in range(tries):
        if js(expr) is True:
            return True
        spin(gap)
    return False


def bar(ms, scale=8.0):
    n = int(min(46, ms / scale))
    return "█" * n


print("前端性能体检\n")

# 确保在版本库页且窗口可见；强制重载，避免量到进程里缓存的旧 JS
w.show()
w.raise_()
spin(300)
_box = {}
_loop = QEventLoop()


def _on(ok):
    _box["ok"] = ok
    _loop.quit()


view.loadFinished.connect(_on)
w.goto("/baidu/depot")
QTimer.singleShot(20000, _loop.quit)
_loop.exec()
try:
    view.loadFinished.disconnect(_on)
except (TypeError, RuntimeError):
    pass
spin(2200)
js("openDir('/')")
spin(1800)

# ── 1. load() 端到端 ──
print("=== 1. load() 端到端（连带 status / pending / sync_plan）===")
js("""
(function(){
  window.__p = null;
  var t0 = performance.now(), n0 = performance.getEntriesByType('resource').length;
  var settled = 0;
  load().then(function(){
    settled = performance.now() - t0;      // load() 自己认为完成的时刻
    setTimeout(function(){                 // 再等一会，把连带请求也收进来统计
      var rs = performance.getEntriesByType('resource').slice(n0);
      var api = rs.filter(function(r){return r.name.indexOf('/api/depot/')>=0;});
      var last = 0;
      api.forEach(function(r){ last = Math.max(last, r.responseEnd - t0); });
      window.__p = JSON.stringify({
        settled: settled, last: last, reqs: api.length,
        names: api.map(function(r){
          return r.name.replace(/^.*\\/api\\/depot\\//,'').split('?')[0]
                 + ' 起' + Math.round(r.startTime-t0) + ' 耗' + Math.round(r.duration);
        })
      });
    }, 700);
  });
})()
""")
wait("!!window.__p")
d = jsj("window.__p") or {}
print(f"  列表可用    {d.get('settled', 0):.0f} ms  {bar(d.get('settled', 0))}")
print(f"  全部就绪    {d.get('last', 0):.0f} ms  {bar(d.get('last', 0))}")
print(f"  发出请求    {d.get('reqs', 0)} 个（起=相对开始的毫秒，耗=自身耗时）")
for n in (d.get("names") or []):
    print(f"      {n}")

# ── 1b. 节流：紧接着再 load()，status/sync_plan 不该再发 ──
print("  接着再 load() 一次：")
js("""
(function(){
  window.__p2 = null;
  var t0 = performance.now(), n0 = performance.getEntriesByType('resource').length;
  load().then(function(){
    setTimeout(function(){
      var rs = performance.getEntriesByType('resource').slice(n0);
      var api = rs.filter(function(r){return r.name.indexOf('/api/depot/')>=0;});
      window.__p2 = JSON.stringify({
        reqs: api.length,
        names: api.map(function(r){
          return r.name.replace(/^.*\\/api\\/depot\\//,'').split('?')[0];
        })
      });
    }, 600);
  });
})()
""")
wait("!!window.__p2")
d2 = jsj("window.__p2") or {}
extra = [n for n in (d2.get("names") or []) if n in ("status", "sync_plan")]
print(f"  再发请求    {d2.get('reqs', 0)} 个{'' if not extra else '（含被节流的 ' + '/'.join(extra) + '）'} -> "
      + ("节流生效" if not extra else "节流未生效"))

# ── 2. 纯渲染 ──
print("\n=== 2. 纯渲染（当前目录，不走网络）===")
r = jsj("""
(function(){
  var ts = [];
  for (var i = 0; i < 12; i++) {
    var t = performance.now();
    render();
    ts.push(performance.now() - t);
  }
  ts.sort(function(a,b){return a-b;});
  return JSON.stringify({
    rows: document.querySelectorAll('#rows tr').length,
    med: ts[6], min: ts[0], max: ts[11],
    nodes: document.getElementsByTagName('*').length
  });
})()
""") or {}
print(f"  行数        {r.get('rows', 0)}")
print(f"  render()    中位 {r.get('med', 0):.1f} ms   最慢 {r.get('max', 0):.1f} ms")
print(f"  DOM 节点    {r.get('nodes', 0)}")

# ── 3. 大目录 ──
print("\n=== 3. 大目录渲染（造假数据，不走网络）===")
for n in (200, 1000, 3000):
    got = jsj("""
    (function(){
      var bak = items;
      var fake = [];
      for (var i = 0; i < %d; i++) {
        fake.push({name:'file_'+i+'.png', path:'/perf/file_'+i+'.png',
                   isdir:false, rev:(i%%9)+1, size:i*1024,
                   action:'edit', owner:'tester', created_at:'2026-08-25T01:00:00Z',
                   locked_by: i%%17===0 ? 'someone' : '',
                   pending: i%%11===0 ? 'edit' : '',
                   pending_cl:0, pending_src:'', out_of_date: i%%7===0});
      }
      items = fake;
      var t = performance.now();
      render();
      var ms = performance.now() - t;
      var nodes = document.getElementsByTagName('*').length;
      items = bak; render();
      return JSON.stringify({ms: ms, nodes: nodes});
    })()
    """ % n) or {}
    ms = got.get("ms", 0)
    print(f"  {n:>5} 行    {ms:>7.0f} ms  {bar(ms, 20)}"
          + ("   << 卡" if ms > 400 else ""))

# ── 4. 滚动重排成本 ──
print("\n=== 4. 滚动重排成本（1000 行，同步测，不受后台节流影响）===")
f = jsj("""
(function(){
  var bak = items, fake = [];
  for (var i = 0; i < 1000; i++)
    fake.push({name:'f'+i+'.png', path:'/perf/f'+i+'.png', isdir:false,
               rev:1, size:1024, action:'edit', owner:'t', created_at:null,
               locked_by:'', pending:'', pending_cl:0, pending_src:'', out_of_date:false});
  items = fake; render();
  var box = document.getElementById('filesBody');
  var span = Math.max(1, box.scrollHeight - box.clientHeight);
  var N = 120, t = performance.now();
  for (var k = 0; k < N; k++) {
    box.scrollTop = (k * 37) % span;
    void box.offsetHeight;            // 强制同步重排，避免浏览器合批
  }
  var ms = (performance.now() - t) / N;
  box.scrollTop = 0; items = bak; render();
  return JSON.stringify({per: ms, span: span});
})()
""") or {}
per = f.get("per", 0)
verdict = ("很轻" if per < 1 else "还行" if per < 4 else
           "偏重，滚动会掉帧")
print(f"  每次滚动重排 {per:.2f} ms   （{verdict}）")
print(f"  可滚动高度   {f.get('span', 0):.0f} px")

# ── 5. 环境 ──
print("\n=== 5. 渲染环境 ===")
import os
flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "(未设置)")
print(f"  Chromium flags   {flags}")
print(f"  {'注意：--disable-gpu 会走纯软件渲染，动画和滚动天然吃亏' if 'disable-gpu' in flags else ''}")
sz = jsj("JSON.stringify({w:innerWidth,h:innerHeight,dpr:devicePixelRatio})") or {}
print(f"  视口             {sz.get('w')}x{sz.get('h')}  dpr={sz.get('dpr')}")

print("\nRESULT PASS")
