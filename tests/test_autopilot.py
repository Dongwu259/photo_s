"""v2.5 autopilot — 无人值守闭环（watch → suggest/auto-tone → audit → 分流）。

process_one 直接单测（不依赖 watchdog 的时序）；watcher 的 on_file/on_modified
钩子单独验证；MCP 三工具走注册表语义。暗图经 suggest 修复后应过闸门进
passed/，无法修复的进 review/——路由即验收。
"""

import json
import os
import time

import pytest

from photo_s.autopilot import (AutopilotConfig, MODES, _iter_images,
                               process_one, validate_config)


def _img(path, fill, size=(160, 160), noise=20):
    """与 test_v23_loop 同款合成图：噪声过 blur 检测，色块过技术闸门。"""
    import numpy as np
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    arr = np.full((*size, 3), fill, dtype=np.int16)
    arr += rng.integers(-noise, noise + 1, arr.shape)
    Image.fromarray(arr.clip(0, 255).astype("uint8")).save(str(path),
                                                           quality=95)
    return str(path)


def _cfg(tmp_path, **kw):
    d = tmp_path / "watch"
    d.mkdir(exist_ok=True)
    return AutopilotConfig(watch_dir=str(d), **kw)


class TestValidate:
    def test_missing_dir(self, tmp_path):
        with pytest.raises(RuntimeError, match="not found"):
            validate_config(AutopilotConfig(watch_dir=str(tmp_path / "nope")))

    def test_bad_mode(self, tmp_path):
        (tmp_path / "d").mkdir()
        with pytest.raises(RuntimeError, match="mode"):
            validate_config(AutopilotConfig(watch_dir=str(tmp_path / "d"),
                                            mode="magic"))

    def test_auto_tone_needs_plugin(self, tmp_path, monkeypatch):
        import photo_s.plugin as plugin_mod
        monkeypatch.setattr(plugin_mod, "find_provider", lambda op: None)
        (tmp_path / "d").mkdir()
        with pytest.raises(RuntimeError, match="auto-tone plugin"):
            validate_config(AutopilotConfig(watch_dir=str(tmp_path / "d"),
                                            mode="auto_tone"))

    def test_aesthetic_needs_verifier(self, tmp_path, monkeypatch):
        import photo_s.plugin as plugin_mod
        monkeypatch.setattr(plugin_mod, "find_provider", lambda op: None)
        (tmp_path / "d").mkdir()
        with pytest.raises(RuntimeError, match="verifier"):
            validate_config(AutopilotConfig(watch_dir=str(tmp_path / "d"),
                                            aesthetic=6.0))

    def test_creates_out_dirs(self, tmp_path):
        (tmp_path / "d").mkdir()
        cfg = AutopilotConfig(watch_dir=str(tmp_path / "d"))
        validate_config(cfg)
        assert os.path.isdir(os.path.join(str(tmp_path / "d"),
                                          "photo-s-out", ".staging"))


class TestProcessOne:
    def test_dark_image_fixed_and_passed(self, tmp_path):
        # 暗图：suggest 应给 ev 补偿 → 处理后亮度过闸门 → passed/
        p = _img(tmp_path / "watch" / "dark.jpg", 70)
        cfg = _cfg(tmp_path)
        validate_config(cfg)
        rec = process_one(p, cfg)
        assert rec["error"] is None, rec
        assert rec["audit"]["passed"] is True
        assert os.sep + "passed" + os.sep in rec["routed"]
        assert os.path.exists(rec["routed"])
        assert not os.path.exists(rec["output"])  # 已路由走，staging 清空

    def test_broken_image_routed_review(self, tmp_path):
        # 全白过曝图：suggest 拉不回 → 闸门拒 → review/（不丢弃，供人审）
        p = _img(tmp_path / "watch" / "blown.jpg", 252, noise=2)
        cfg = _cfg(tmp_path)
        validate_config(cfg)
        rec = process_one(p, cfg)
        assert rec["error"] is None
        assert rec["audit"]["passed"] is False
        assert os.sep + "review" + os.sep in rec["routed"]

    def test_jsonl_log_written(self, tmp_path):
        p = _img(tmp_path / "watch" / "a.jpg", 110)
        cfg = _cfg(tmp_path)
        process_one(p, cfg)
        log = tmp_path / "watch" / "photo-s-out" / "autopilot.jsonl"
        assert log.exists()
        rows = [json.loads(line) for line in
                log.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(rows) == 1
        assert rows[0]["input"].endswith("a.jpg")
        assert rows[0]["audit"]["passed"] in (True, False)

    def test_write_xmp_sidecar(self, tmp_path):
        from photo_s.lrxmp import parse_xmp_sidecar
        p = _img(tmp_path / "watch" / "x.jpg", 100)
        cfg = _cfg(tmp_path, write_xmp=True)
        rec = process_one(p, cfg)
        sidecar = tmp_path / "watch" / "x.xmp"
        assert rec["xmp"] == str(sidecar)
        settings = parse_xmp_sidecar(str(sidecar))
        # suggest 的修复参数应落在 XMP（ev/wb 任一出现即证明真实参数导出）
        assert "Exposure2012" in settings or "Temperature" in settings

    def test_unreadable_records_error(self, tmp_path):
        cfg = _cfg(tmp_path)
        bad = tmp_path / "watch" / "bad.jpg"
        bad.write_bytes(b"not an image")
        rec = process_one(str(bad), cfg)
        assert rec["error"] is not None
        assert rec["routed"] is None

    def test_collision_routing(self, tmp_path):
        p = _img(tmp_path / "watch" / "same.jpg", 110)
        cfg = _cfg(tmp_path)
        r1 = process_one(p, cfg)
        r2 = process_one(p, cfg)
        assert r1["routed"] != r2["routed"]  # 重名不覆盖


class TestIterImages:
    def test_skips_out_root(self, tmp_path):
        d = tmp_path / "watch"
        (d / "sub").mkdir(parents=True)
        _img(d / "a.jpg", 100)
        _img(d / "photo-s-out" / "passed" / "a.jpg", 100)
        _img(d / "sub" / "b.jpg", 100)
        out = _iter_images(str(d), recursive=True,
                           skip_under=str(d / "photo-s-out"))
        names = [os.path.basename(p) for p in out]
        assert names == ["a.jpg", "b.jpg"]

    def test_non_recursive_top_only(self, tmp_path):
        d = tmp_path / "watch"
        (d / "sub").mkdir(parents=True)
        _img(d / "a.jpg", 100)
        _img(d / "sub" / "b.jpg", 100)
        out = _iter_images(str(d), False, skip_under=str(d / "photo-s-out"))
        assert [os.path.basename(p) for p in out] == ["a.jpg"]


class TestWatcherHook:
    def test_on_file_receives_stable_path(self, tmp_path):
        from photo_s.watcher import _DebouncedHandler
        from photo_s.engine import ProcessOptions
        seen = []
        h = _DebouncedHandler(ProcessOptions(), on_file=seen.append)
        p = tmp_path / "a.jpg"
        _img(p, 100)
        h._pending[str(p)] = time.time() - 5  # 跳过 2s 防抖等待
        results = h.tick()
        assert results == []           # on_file 模式不产内置结果
        assert seen == [str(p)]

    def test_on_modified_enters_debounce(self, tmp_path):
        from photo_s.watcher import _DebouncedHandler
        from photo_s.engine import ProcessOptions

        class Evt:
            is_directory = False
            src_path = str(tmp_path / "m.jpg")

        h = _DebouncedHandler(ProcessOptions())
        h.on_modified(Evt())
        assert str(tmp_path / "m.jpg") in h._pending


class TestMcpTools:
    def _wait_thread_dead(self, aid, timeout=10.0):
        # 不向后续测试泄漏 watchdog 观察者/工作线程（Tk GUI 测试对时序敏感）
        from photo_s import mcp_server
        deadline = time.time() + timeout
        while time.time() < deadline:
            with mcp_server._AUTOPILOT_LOCK:
                rec = mcp_server._AUTOPILOTS.get(aid)
            if rec is None or not rec["thread"].is_alive():
                return
            time.sleep(0.1)

    def test_autopilot_start_status_stop(self, tmp_path):
        pytest.importorskip("watchdog")
        from photo_s.mcp_server import (autopilot_start_tool,
                                        autopilot_status_tool,
                                        autopilot_stop_tool)
        d = tmp_path / "w"
        d.mkdir()
        # 文件先在 + scan_existing：队列启动时预灌，不依赖文件系统事件
        # 的到达时机（watchdog 在 CI/macOS 上的投递延迟不可控）
        _img(d / "new.jpg", 90)
        res = autopilot_start_tool(dir=str(d), scan_existing=True)
        if not res.get("started"):
            pytest.skip("watchdog unavailable")
        aid = res["id"]
        deadline = time.time() + 25
        st = None
        while time.time() < deadline:
            st = autopilot_status_tool(aid)
            if st["processed_count"] >= 1:
                break
            time.sleep(0.3)
        assert st["processed_count"] >= 1
        assert st["passed"] + st["review"] + st["errors"] == \
            st["processed_count"]
        assert st["results"][0]["audit"]["passed"] is True
        stop = autopilot_stop_tool(aid)
        assert stop["ok"] is True
        self._wait_thread_dead(aid)

    def test_autopilot_start_missing_dir(self):
        from photo_s.mcp_server import autopilot_start_tool
        res = autopilot_start_tool(dir="/nonexistent-definitely")
        assert res["started"] is False
        assert "not a directory" in res["error"]

    def test_autopilot_status_unknown_id(self):
        from photo_s.mcp_server import autopilot_status_tool
        assert autopilot_status_tool("nope")["ok"] is False

    def test_autopilot_mode_needs_plugin(self, tmp_path, monkeypatch):
        import photo_s.plugin as plugin_mod
        monkeypatch.setattr(plugin_mod, "find_provider", lambda op: None)
        from photo_s.mcp_server import autopilot_start_tool
        d = tmp_path / "w2"
        d.mkdir()
        res = autopilot_start_tool(dir=str(d), mode="auto_tone")
        assert res["started"] is False
        assert "auto-tone plugin" in res["error"]


class TestRestRoutes:
    def _server(self, tmp_path):
        import threading
        from photo_s.server import create_server
        from photo_s.engine import ProcessOptions
        httpd = create_server("127.0.0.1", 0, ProcessOptions())
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        yield httpd, port
        httpd.shutdown()

    def test_autopilot_rest_flow(self, tmp_path):
        import urllib.request
        pytest.importorskip("watchdog")
        gen = self._server(tmp_path)
        httpd, port = next(gen)
        try:
            d = tmp_path / "rw"
            d.mkdir()
            body = json.dumps({"dir": str(d), "mode": "suggest",
                               "scan_existing": True}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/autopilot", data=body,
                headers={"Content-Type": "application/json",
                         "Host": "127.0.0.1"})
            with urllib.request.urlopen(req, timeout=10) as r:
                assert r.status == 202
                payload = json.loads(r.read())
            if not payload.get("started"):
                pytest.skip("watchdog unavailable")
            aid = payload["id"]
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/v1/autopilot/{aid}",
                    timeout=10) as r:
                st = json.loads(r.read())
            assert st["ok"] is True
            req2 = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/autopilot/{aid}/cancel",
                data=b"{}", method="POST",
                headers={"Content-Type": "application/json",
                         "Host": "127.0.0.1"})
            with urllib.request.urlopen(req2, timeout=10) as r:
                assert json.loads(r.read())["ok"] is True
            TestMcpTools()._wait_thread_dead(aid)
        finally:
            next(gen, None)

    def test_rest_missing_dir_400(self, tmp_path):
        import urllib.request
        import urllib.error
        gen = self._server(tmp_path)
        httpd, port = next(gen)
        try:
            body = json.dumps({"dir": "/nonexistent"}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/autopilot", data=body,
                headers={"Content-Type": "application/json",
                         "Host": "127.0.0.1"})
            with pytest.raises(urllib.error.HTTPError) as ei:
                urllib.request.urlopen(req, timeout=10)
            assert ei.value.code == 400
        finally:
            next(gen, None)
