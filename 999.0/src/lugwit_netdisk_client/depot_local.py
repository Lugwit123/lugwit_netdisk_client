# -*- coding: utf-8 -*-
"""版本库（百度云 depot）本地访问：客户端进程内直连 depot 服务。

网页在**客户端里**运行时（`window.lugwitBridge` 存在），拿到的是本地能力——
所以版本库内容不必再绕「托盘中转」或 nginx `/baidu` 网关，直接问本机 depot 服务
（`lugwit_baidu_netdisk`，默认 127.0.0.1:1028）。

基址优先级：`L_CLIENT_DEPOT_URL` > `L_DEPOT_SERVICE_URL` > `http://127.0.0.1:1028`
（远端部署时可指向服务器网关，如 `https://121.196.144.88/baidu`）。

与 `l_tray/src/l_tray/depot_bridge.py` 是同一套语义（托盘与客户端二选一，谁在
谁服务）；两边都保持同样的路径校验与大小上限，避免行为不一致。

安全边界：`path` 必须绝对逻辑路径（以 `/` 开头）且不含 `..`；单文件上限 8MB。
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_DEPOT_URL = "http://127.0.0.1:1028"
MAX_BYTES = 8 * 1024 * 1024

# 直接按文本回传的扩展名（网页端做 Markdown 预览用）
TEXT_EXTS = {
    ".md", ".markdown", ".txt", ".rst", ".log", ".json", ".yaml", ".yml",
    ".csv", ".ini", ".cfg", ".toml", ".py", ".js", ".ts", ".css", ".html",
    ".xml", ".sh", ".bat", ".cmd", ".ps1", ".sql",
}


def base_url() -> str:
    url = (
        os.environ.get("L_CLIENT_DEPOT_URL")
        or os.environ.get("L_DEPOT_SERVICE_URL")
        or DEFAULT_DEPOT_URL
    )
    return str(url).strip().rstrip("/")


def _http(method: str, path: str, *, params: dict[str, Any] | None = None,
          body: bytes | None = None, timeout: float = 60.0,
          token: str = "") -> tuple[int, bytes]:
    url = base_url() + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/octet-stream")
    tok = (token or os.environ.get("LUGWIT_ACCESS_TOKEN", "")).strip()
    if tok:
        # depot 服务（gate.require_lugwit_token）认 cookie `lugwit_token`；
        # 同时带 Bearer 以便将来直连认证服务时也能用。
        req.add_header("Cookie", "lugwit_token=" + tok)
        req.add_header("Authorization", "Bearer " + tok)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"版本库服务不可用（{base_url()}）：{exc}") from exc


def _json(raw: bytes) -> dict[str, Any]:
    try:
        return json.loads(raw.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError:
        return {}


def _check_path(path: str) -> str:
    p = str(path or "").strip()
    if not p.startswith("/"):
        raise ValueError("路径必须是绝对逻辑路径（以 / 开头）")
    if ".." in p.split("/"):
        raise ValueError("路径不允许包含 ..")
    return p


def base_info() -> dict[str, Any]:
    """当前解析到的 depot 基址（供页面显示 / 排查）。"""
    return {"ok": True, "base_url": base_url(), "max_bytes": MAX_BYTES,
            "source": "client-bridge"}


def list_dir(dir: str = "", ws: str = "", token: str = "") -> dict[str, Any]:
    params: dict[str, Any] = {"dir": _check_path(dir)}
    if str(ws).strip():
        params["ws"] = str(ws).strip()
    status, raw = _http("GET", "/api/depot/list", params=params, token=token)
    if status >= 400:
        raise RuntimeError(f"列目录失败：HTTP {status} {raw[:200]!r}")
    return {"ok": True, "base_url": base_url(), "dir": params["dir"], **_json(raw)}


def download(path: str, rev: int = 0, ws: str = "", token: str = "") -> dict[str, Any]:
    """取版本库文件内容；文本类扩展名回 `text`，其余回 `base64`。"""
    p = _check_path(path)
    params: dict[str, Any] = {"path": p, "rev": int(rev or 0), "inline": 1}
    if str(ws).strip():
        params["ws"] = str(ws).strip()
    status, raw = _http("GET", "/api/depot/download", params=params, token=token)
    if status >= 400:
        raise RuntimeError(f"读取失败：HTTP {status} {raw[:200]!r}")
    if len(raw) > MAX_BYTES:
        raise ValueError(f"文件超过上限（{len(raw)} > {MAX_BYTES} 字节）")
    out: dict[str, Any] = {"ok": True, "path": p, "rev": int(rev or 0), "size": len(raw)}
    if os.path.splitext(p)[1].lower() in TEXT_EXTS:
        try:
            out["text"] = raw.decode("utf-8")
        except UnicodeDecodeError:
            out["text"] = raw.decode("gbk", "replace")
    else:
        out["base64"] = base64.b64encode(raw).decode("ascii")
    return out


def versions(path: str, ws: str = "", token: str = "") -> dict[str, Any]:
    p = _check_path(path)
    params: dict[str, Any] = {"path": p}
    if str(ws).strip():
        params["ws"] = str(ws).strip()
    status, raw = _http("GET", "/api/depot/versions", params=params, token=token)
    if status >= 400:
        raise RuntimeError(f"取版本历史失败：HTTP {status} {raw[:200]!r}")
    return {"ok": True, **_json(raw)}


__all__ = ["base_url", "base_info", "list_dir", "download", "versions",
           "MAX_BYTES", "TEXT_EXTS"]
