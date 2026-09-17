#!/usr/bin/env python3
"""极简 MCP streamable-HTTP 客户端（零依赖，用于调用本机 TTS 服务）。

PhotoS 自己就是 MCP server，这里再用 MCP 去驱动另一个本机 server
（Kokoro 中文 TTS，http://127.0.0.1:8740/mcp）给演示视频生成旁白。

用法：
    python3 tools/tts_mcp_client.py list
    python3 tools/tts_mcp_client.py call tts_generate '{"text": "...", "voice": "zm_058"}'

环境变量 PHOTOS_TTS_URL 可覆盖服务地址；服务不可用时调用方应回退为无旁白。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

URL = os.environ.get("PHOTOS_TTS_URL", "http://127.0.0.1:8740/mcp")
HDRS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _post(body: dict, session: str | None = None):
    h = dict(HDRS)
    if session:
        h["mcp-session-id"] = session
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=h,
                                 method="POST")
    resp = urllib.request.urlopen(req, timeout=600)
    sid = resp.headers.get("mcp-session-id", session)
    raw = resp.read().decode("utf-8", "replace")
    # SSE 或纯 JSON 两种返回
    if raw.lstrip().startswith("event:") or "\ndata: " in raw:
        for line in raw.splitlines():
            if line.startswith("data: "):
                return json.loads(line[6:]), sid
        raise RuntimeError(f"无法解析 SSE: {raw[:200]}")
    return (json.loads(raw) if raw.strip() else None), sid


def connect() -> str:
    res, sid = _post({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "photos-demo", "version": "1.0"}},
    })
    assert sid, "服务未返回 mcp-session-id"
    # 必须补 initialized 通知，否则后续请求可能被拒
    try:
        _post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    except Exception:
        pass
    print(f"[mcp] connected: {res['result']['serverInfo']}", file=sys.stderr)
    return sid


def list_tools(sid: str):
    res, _ = _post({"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                    "params": {}}, sid)
    return res["result"]["tools"]


def call(sid: str, name: str, args: dict):
    res, _ = _post({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": name, "arguments": args}}, sid)
    return res["result"]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    sid = connect()
    if cmd == "list":
        for t in list_tools(sid):
            print(f"\n■ {t['name']}")
            print(f"  {t.get('description', '')[:160]}")
            props = (t.get("inputSchema") or {}).get("properties") or {}
            req = (t.get("inputSchema") or {}).get("required") or []
            for k, v in props.items():
                mark = "*" if k in req else " "
                desc = (v.get("description") or "")[:80]
                print(f"   {mark} {k}: {v.get('type')} {desc}")
    elif cmd == "call":
        print(json.dumps(call(sid, sys.argv[2], json.loads(sys.argv[3])),
                         ensure_ascii=False, indent=2))
