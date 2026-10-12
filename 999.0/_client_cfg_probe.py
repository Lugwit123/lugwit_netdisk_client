"""在客户端进程内跑：验证「服务器设置」注入 + 本机/远程切换（登录 + 页面一起切）。"""
import json
import urllib.request

from PySide6.QtWidgets import QApplication

wins = [w for w in QApplication.instance().topLevelWidgets() if hasattr(w, "bridge")]
if not wins:
    print("MARK 没有带 bridge 的窗口")
    raise SystemExit(1)
w = wins[0]

print("MARK 初始 base_url:", w.base_url)
ss = w._server_store
print("MARK server store 文件:", ss.config_file(), "| 存在:", ss.config_file().exists())
print("MARK auth_url:", ss.auth_url(), "| local_mode:", ss.local_mode())
print("MARK 🌐 设置按钮:", type(w._serverSettingsBtn).__name__)
print("MARK 登录按钮:", type(w._loginBtn).__name__)

before = w.base_url
ss.save(local_mode=True)                       # 等价于设置对话框勾「本机模式」并保存
w._on_server_config_changed(ss.all())          # 库保存后会发这个信号
print("MARK 切本机后 base_url:", before, "->", w.base_url)
print("MARK 切本机后 auth_url:", ss.auth_url())

try:
    req = urllib.request.Request(ss.auth_url() + ss.auth_route() + "/login", method="POST",
                                 data=json.dumps({"username": "admin01", "password": "666"}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read().decode())
        print("MARK 本机登录:", r.status,
              "token:", bool(d.get("access_token") or d.get("token")))
except Exception as exc:  # noqa: BLE001
    print("MARK 本机登录失败:", type(exc).__name__, str(exc)[:120])

ss.clear()                                     # 复原：清掉临时覆盖（回默认）
w._on_server_config_changed(ss.all())
print("MARK 复原后 base_url:", w.base_url, "| local_mode:", ss.local_mode())
