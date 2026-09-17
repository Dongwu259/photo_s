"""v2.6 结构项 tests: panels/ 拆分 · PanedWindow 分栏持久化 · watch 面板化。

Same conventions as test_gui_v26.py (hermetic HOME, zh pinned, real
display or skip).
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("PHOTO_S_LANG", "zh")


def _make_app():
    import tkinter as tk
    from photo_s.gui import PhotoSApp
    try:
        root = tk.Tk()
    except Exception as e:
        pytest.skip("no display: {}".format(e))
    app = PhotoSApp(root)
    root.update_idletasks()
    return root, app


def _poll(root, pred, seconds=10.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        root.update()
        if pred():
            return True
        time.sleep(0.05)
    return False


# ── panels/ 拆分：组合 + 方法归位 ─────────────────────────────────────────────

class TestPanelsSplit:
    def test_mixins_compose_into_app(self):
        from photo_s.gui import PhotoSApp
        from photo_s.gui.panels import (ReviewPanelMixin,
                                        WatchPanelMixin,
                                        WorkflowDialogsMixin)
        for base in (ReviewPanelMixin, WorkflowDialogsMixin,
                     WatchPanelMixin):
            assert issubclass(PhotoSApp, base)
        # 方法经 mixin 可达（TOOLS_CARDS 的 opener 全部存在）
        for _, _, opener in PhotoSApp.TOOLS_CARDS:
            assert callable(getattr(PhotoSApp, opener)), opener
        for name in ("_build_review_ui", "_review_save", "_show_dedup",
                     "_show_watch", "_show_presets", "_show_compare"):
            owner = getattr(PhotoSApp, name).__qualname__
            assert "Mixin" in owner, (name, owner)

    def test_panels_have_no_own_state(self):
        """Mixin 不定义 __init__、不声明类属性——状态全部经宿主 self。"""
        from photo_s.gui.panels import (ReviewPanelMixin, WatchPanelMixin,
                                        WorkflowDialogsMixin)
        for cls in (ReviewPanelMixin, WorkflowDialogsMixin, WatchPanelMixin):
            assert "__init__" not in cls.__dict__
            assert not any(not k.startswith("__") for k in cls.__dict__
                           if not callable(cls.__dict__[k])), \
                f"{cls.__name__} 声明了非方法类属性"


# ── PanedWindow 分栏：可拖 + 持久化 ──────────────────────────────────────────

class TestPaneSashes:
    def test_develop_main_is_panedwindow(self):
        import tkinter.ttk as ttk
        root, app = _make_app()
        assert isinstance(app._dev_main, ttk.PanedWindow)
        assert isinstance(app._export_main, ttk.PanedWindow)
        # sash 只有在窗格真实映射后才有位置——先切到对应模块
        app._show_module("develop")
        root.update()
        cur = app._dev_main.sashpos(0)
        assert cur > 0
        app._dev_main.sashpos(0, cur + 40)
        assert app._dev_main.sashpos(0) == cur + 40
        app._show_module("export")
        root.update()
        assert app._export_main.sashpos(0) > 0
        root.destroy()

    def test_sash_persists_across_restart(self, tmp_path):
        root, app = _make_app()
        app._show_module("develop")
        assert _poll(root, lambda: app._dev_main.sashpos(0) > 0)
        target = app._dev_main.sashpos(0) + 60
        app._dev_main.sashpos(0, target)
        app._save_gui_state()
        root.destroy()

        root2, app2 = _make_app()  # 同一隔离 HOME → 读回 gui_state
        app2._show_module("develop")
        assert _poll(root2,
                     lambda: app2._dev_main.sashpos(0) == target), \
            "sash 位置经 gui_state 恢复"
        root2.destroy()

    def test_mask_mode_hides_side_pane(self):
        root, app = _make_app()
        app._show_module("develop")
        root.update()
        # 直接驱动布局切换（不构建整个蒙版编辑器——enter 需要 Photos 和用户交互）
        sash = app._dev_main.sashpos(0)
        app._dev_mask_mode = True
        app._dev_mask_apply_layout()
        root.update()
        assert str(app._dev_side) not in [str(x) for x in app._dev_main.panes()], "侧栏 pane 摘除"
        assert app._dev_mask_host.winfo_manager() == "pack"
        assert app._dev_viewer_card.winfo_manager() == ""
        app._dev_mask_mode = False
        app._dev_mask_apply_layout()
        root.update()
        assert str(app._dev_side) in [str(x) for x in app._dev_main.panes()], "侧栏 pane 归位"
        assert app._dev_viewer_card.winfo_manager() == "pack"
        assert _poll(root, lambda: app._dev_main.sashpos(0) == sash), \
            "sash 位置还原（after_idle 后生效）"
        root.destroy()


# ── Tools 面板化首批：watch 内嵌 ────────────────────────────────────────────

class TestWatchPanel:
    def test_card_toggles_inline_panel(self):
        root, app = _make_app()
        app._show_module("tools")
        assert app._tools_panel_open is None
        app._tools_open_watch()
        root.update()
        assert app._tools_panel_open == "_show_watch"
        assert app._tools_panel_host.winfo_children(), "面板已内嵌构建"
        assert not [w for w in root.winfo_children()
                    if w.winfo_class() == "Toplevel"], "不弹窗"
        # 再点一次卡片 → 关闭
        app._tools_open_watch()
        root.update()
        assert app._tools_panel_open is None
        assert not app._tools_panel_host.winfo_children()
        root.destroy()

    def test_close_panel_runs_cleanup_hook(self):
        calls = []
        root, app = _make_app()
        app._tools_panel_host.close_hook = lambda: calls.append(1)
        app._tools_close_panel()
        assert calls == [1], "关闭面板必须执行 close_hook（如停表）"
        assert getattr(app._tools_panel_host, "close_hook", None) is None
        root.destroy()

    def test_dialog_mode_unchanged(self):
        """无 host 调用仍是 Toplevel 对话框（既有 watch 测试的路径）。"""
        import tkinter as tk
        root, app = _make_app()
        app._show_watch()
        tops = [w for w in root.winfo_children()
                if isinstance(w, tk.Toplevel)]
        assert tops
        tops[0].destroy()
        root.destroy()
