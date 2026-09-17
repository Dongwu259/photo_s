"""photo_s/gui/panels/watch.py — 监视 / autopilot 起飞对话框（v2.6 智能模式）。

v2.6 结构项首批：从 app.py 平移（方法体逐字节保留，
仅函数级相对导入加深一层）。Mixin 无独立状态，全部经 ``self`` 与
PhotoSApp 共享；新面板代码继续按此模式落位，app.py 不再膨胀。
"""

import os
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from ...engine import ProcessOptions, SUPPORTED_FORMATS
from .. import workflows
from ..bus import UiBus
from ..theme import COLORS, FONT_BODY, FONT_SMALL
from ..widgets import FlatButton


class WatchPanelMixin:
    """监视 / autopilot 起飞对话框（v2.6 智能模式）。"""

    def _show_watch(self, host=None):
        """Folder watcher: auto-process new images dropped into a directory.
        Two modes: basic (straight convert with the dialog fields) and the
        v2.6 autopilot modes (suggest / auto_tone / both — suggest → process
        → audit → passed/review routing via photo_s.autopilot). Runs in a
        daemon thread (watchdog Observer); closing the dialog stops it.
        Uses the current watch fields, not the main-window options.
        v2.6 结构项（非模态化首批）：``host`` 给定时内嵌为 Tools 模块的
        常驻面板——不再弹 Toplevel，面板关闭经 ``host.close_hook`` 停表
        （与 WM_DELETE_WINDOW 同语义）。"""
        if host is not None:
            win = tk.Frame(host, bg=COLORS["bg"])
            win.pack(fill="both", expand=True)
            head = tk.Frame(win, bg=COLORS["bg"])
            head.pack(fill="x", pady=(0, 6))
            tk.Label(head, text=self._t("watch_title"), font=FONT_BODY,
                     fg=COLORS["text"], bg=COLORS["bg"]).pack(side="left")
            FlatButton(
                head, text="×", command=self._tools_close_panel,
                bg=COLORS["bg"], fg=COLORS["text_secondary"],
                hover_bg=COLORS["border"], font=FONT_SMALL, padx=6, pady=1,
                border_color=COLORS["border"]).pack(side="right")
        else:
            win = tk.Toplevel(self.root)
            win.title(self._t("watch_title"))
            win.geometry("560x520")
            win.configure(bg=COLORS["bg"])
            win.transient(self.root)

        from ...engine import ProcessOptions, SUPPORTED_FORMATS

        watch_dir = tk.StringVar()
        out_dir = tk.StringVar()
        recursive = tk.BooleanVar(value=False)
        fmt = tk.StringVar(value=self.output_format.get() or "JPEG")
        quality = tk.IntVar(value=85)
        rm_orig = tk.BooleanVar(value=False)
        # v2.6 autopilot fields
        mode_disp = tk.StringVar()          # localized combobox text
        strength = tk.StringVar(value="1.0")
        ap_write_xmp = tk.BooleanVar(value=False)
        ap_scan = tk.BooleanVar(value=False)
        modes = (("basic", "watch_mode_basic"), ("suggest", "watch_mode_suggest"),
                 ("auto_tone", "watch_mode_auto_tone"), ("both", "watch_mode_both"))
        disp_of = {m: self._t(key) for m, key in modes}
        mode_of = {v: k for k, v in disp_of.items()}
        mode_disp.set(disp_of["basic"])
        state = {"stop": threading.Event(), "running": False, "count": 0,
                 "thread": None, "ap_pass": 0, "ap_review": 0, "ap_error": 0}

        body = tk.Frame(win, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=20, pady=16)
        body.columnconfigure(1, weight=1)

        def _row(row, label_key, var, browse_dir=False):
            tk.Label(body, text=self._t(label_key), font=FONT_SMALL,
                     fg=COLORS["text_secondary"], bg=COLORS["bg"]).grid(
                row=row, column=0, sticky="w", pady=(0, 6), padx=(0, 10))
            ttk.Entry(body, textvariable=var, font=FONT_BODY).grid(
                row=row, column=1, sticky="ew", pady=(0, 6))
            if browse_dir:
                def _browse():
                    if self._dlg_cooldown_active():
                        return
                    p = filedialog.askdirectory()
                    self._after_file_dialog()
                    if p:
                        var.set(p)
                FlatButton(body, text=self._t("browse"), command=_browse,
                           bg=COLORS["card"], fg=COLORS["text"],
                           hover_bg=COLORS["bg"],
                           border_color=COLORS["border"],
                           font=FONT_SMALL).grid(
                    row=row, column=2, sticky="w", padx=(8, 0), pady=(0, 6))

        _row(0, "watch_dir", watch_dir, browse_dir=True)
        _row(2, "watch_outdir", out_dir, browse_dir=True)

        # v2.6: processing mode — basic watcher or autopilot (rows 1/3 were
        # layout gaps in the original grid, so no renumbering needed)
        tk.Label(body, text=self._t("watch_mode"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).grid(
            row=1, column=0, sticky="w", pady=(0, 6), padx=(0, 10))
        mode_box = ttk.Combobox(body, textvariable=mode_disp,
                                values=[disp_of[m] for m, _ in modes],
                                state="readonly", font=FONT_BODY)
        mode_box.grid(row=1, column=1, sticky="ew", pady=(0, 6))
        strength_lbl = tk.Label(body, text=self._t("watch_strength"),
                                font=FONT_SMALL, fg=COLORS["text_secondary"],
                                bg=COLORS["bg"])
        strength_lbl.grid(row=3, column=0, sticky="w", padx=(0, 10))
        strength_box = ttk.Combobox(body, textvariable=strength, width=5,
                                    values=("1.0", "0.8", "0.6", "0.4", "0.2"),
                                    state="readonly", font=FONT_BODY)
        strength_box.grid(row=3, column=1, sticky="w")

        def _current_mode():
            return mode_of.get(mode_disp.get(), "basic")

        def _on_mode(_evt=None):
            m = _current_mode()
            strength_box.configure(
                state="readonly" if m in ("auto_tone", "both") else "disabled")
            for cb in (ap_xmp_cb, ap_scan_cb):
                cb.configure(state="normal" if m != "basic" else "disabled")
            rm_cb.configure(state="normal" if m == "basic" else "disabled")

        mode_box.bind("<<ComboboxSelected>>", _on_mode)

        ttk.Checkbutton(body, text=self._t("watch_recursive"),
                        variable=recursive).grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(2, 6))

        tk.Label(body, text=self._t("watch_format"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).grid(
            row=5, column=0, sticky="w", pady=(0, 6), padx=(0, 10))
        ttk.Combobox(body, textvariable=fmt,
                     values=list(SUPPORTED_FORMATS), state="readonly",
                     font=FONT_BODY).grid(row=5, column=1, columnspan=2,
                                          sticky="ew", pady=(0, 6))

        qrow = tk.Frame(body, bg=COLORS["bg"])
        qrow.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(2, 2))
        qval = tk.Label(qrow, text=str(quality.get()), font=FONT_SMALL,
                        fg=COLORS["accent"], bg=COLORS["bg"], width=4)
        qval.pack(side="right")
        qlbl = tk.Label(qrow, text=self._t("watch_quality"), font=FONT_SMALL,
                        fg=COLORS["text_secondary"], bg=COLORS["bg"])
        qlbl.pack(side="left")
        ttk.Scale(qrow, from_=1, to=100, variable=quality,
                  command=lambda v: qval.configure(text=str(int(float(v)))))\
            .pack(side="left", fill="x", expand=True, padx=(8, 8))

        optrow = tk.Frame(body, bg=COLORS["bg"])
        optrow.grid(row=7, column=0, columnspan=3, sticky="w", pady=(2, 10))
        rm_cb = ttk.Checkbutton(optrow, text=self._t("watch_remove_original"),
                                variable=rm_orig)
        rm_cb.pack(side="left")
        ap_xmp_cb = ttk.Checkbutton(optrow,
                                    text=self._t("watch_ap_write_xmp"),
                                    variable=ap_write_xmp)
        ap_xmp_cb.pack(side="left", padx=(14, 0))
        ap_scan_cb = ttk.Checkbutton(optrow,
                                     text=self._t("watch_scan_existing"),
                                     variable=ap_scan)
        ap_scan_cb.pack(side="left", padx=(14, 0))
        _on_mode()  # initial enable/disable for the default mode

        btns = tk.Frame(body, bg=COLORS["bg"])
        btns.grid(row=8, column=0, columnspan=3, sticky="w")
        start_btn = FlatButton(btns, text=self._t("watch_start"),
                               command=lambda: _start(),
                               bg=COLORS["accent"],
                               hover_bg=COLORS["accent_hover"])
        start_btn.pack(side="left")
        stop_btn = FlatButton(btns, text=self._t("watch_stop"),
                              command=lambda: _stop(),
                              bg=COLORS["card"], fg=COLORS["text"],
                              hover_bg=COLORS["bg"],
                              border_color=COLORS["border"])
        stop_btn.pack(side="left", padx=(8, 0))
        stop_btn.configure(state="disabled")
        FlatButton(btns, text=self._t("watch_open_out"),
                   command=lambda: _open_out(),
                   bg=COLORS["card"], fg=COLORS["text"],
                   hover_bg=COLORS["bg"], border_color=COLORS["border"],
                   font=FONT_SMALL).pack(side="left", padx=(8, 0))

        status = tk.Label(body, text="", font=FONT_SMALL,
                          fg=COLORS["text_secondary"], bg=COLORS["bg"])
        status.grid(row=9, column=0, columnspan=3, sticky="w", pady=(10, 0))

        bus = UiBus(win)
        schedule = bus.schedule

        def _start():
            # stop-then-start race: the previous watcher thread may still be
            # draining when Start is pressed again — two watchers on the same
            # directory would double-process every new file. Wait for it.
            prev = state.get("thread")
            if prev is not None and prev.is_alive():
                status.configure(
                    text=self._t("watch_stopping_prev")
                    if self._t("watch_stopping_prev") != "watch_stopping_prev"
                    else "等待上一个 watcher 停止… stopping previous watcher…",
                    fg=COLORS["warning"])
                if win.winfo_exists():
                    win.after(200, _start)
                return
            d = watch_dir.get().strip()
            if not d or not os.path.isdir(d):
                status.configure(text=self._t("watch_no_dir"),
                                 fg=COLORS["danger"])
                return
            import importlib.util
            if importlib.util.find_spec("watchdog") is None:
                status.configure(text=self._t("watch_no_watchdog"),
                                 fg=COLORS["danger"])
                return
            state["stop"].clear()
            state["running"] = True
            state["count"] = 0
            state["ap_pass"] = state["ap_review"] = state["ap_error"] = 0
            start_btn.configure(state="disabled")
            stop_btn.configure(state="normal")
            status.configure(text=self._t("watch_running"),
                             fg=COLORS["success"])
            rec = recursive.get()  # read on the main thread only
            m = _current_mode()
            if m == "basic":
                opts = ProcessOptions(
                    quality=int(quality.get()),
                    output_format=fmt.get(),
                    output_dir=out_dir.get().strip() or None,
                    remove_original=rm_orig.get(),
                )

                def run():
                    from ...watcher import start_watching
                    start_watching(d, opts, recursive=rec,
                                   on_process=lambda r: schedule(
                                       lambda: _on_result(r)),
                                   stop_event=state["stop"])
                    state["running"] = False
            else:
                from ...autopilot import AutopilotConfig, run_autopilot
                try:
                    ap_strength = float(strength.get())
                except (ValueError, tk.TclError):
                    ap_strength = 1.0
                cfg = AutopilotConfig(
                    watch_dir=d,
                    out_dir=out_dir.get().strip() or None,
                    mode=m,
                    auto_tone_strength=ap_strength,
                    write_xmp=ap_write_xmp.get(),
                    recursive=rec,
                    scan_existing=ap_scan.get(),
                    quality=int(quality.get()),
                    output_format=fmt.get(),
                )

                def run():
                    try:
                        # validate_config fail-loud (missing plugin etc.)
                        # surfaces in the status line, buttons restored
                        run_autopilot(cfg, on_event=lambda r: schedule(
                            lambda: _on_ap_event(r)),
                            stop_event=state["stop"])
                    except RuntimeError as e:
                        schedule(lambda err=str(e): _ap_start_failed(err))
                    state["running"] = False

            state["thread"] = threading.Thread(target=run, daemon=True)
            state["thread"].start()

        def _stop():
            state["stop"].set()
            start_btn.configure(state="normal")
            stop_btn.configure(state="disabled")

        def _open_out():
            m = _current_mode()
            d = out_dir.get().strip()
            if not d:
                watch = watch_dir.get().strip()
                d = (os.path.join(watch, "photo-s-out")
                     if m != "basic" and watch else watch)
            if not d or not os.path.isdir(d):
                status.configure(text=self._t("watch_out_missing"),
                                 fg=COLORS["warning"])
                return
            workflows.reveal_in_file_manager(d)

        def _on_result(r):
            if not win.winfo_exists():
                return
            if r.success and r.output_path:
                try:
                    self._append_files([r.output_path])
                except Exception:
                    pass
                state["count"] += 1
                status.configure(
                    text=self._t("watch_processed", n=state["count"]),
                    fg=COLORS["success"])

        def _on_ap_event(rec):
            if not win.winfo_exists():
                return
            name = os.path.basename(rec.get("input") or "")
            err = rec.get("error")
            routed = rec.get("routed") or ""
            if err:
                state["ap_error"] += 1
                text, fg = self._t("ap_event_error", name=name,
                                   err=err[:80]), COLORS["danger"]
            elif "passed" in routed.replace("\\", "/"):
                state["ap_pass"] += 1
                text, fg = self._t(
                    "ap_event_pass", name=name, p=state["ap_pass"],
                    r=state["ap_review"], e=state["ap_error"],
                    dir=os.path.basename(routed)), COLORS["success"]
            else:
                state["ap_review"] += 1
                reason = ((rec.get("audit") or {}).get("reason") or "")[:60]
                text, fg = self._t(
                    "ap_event_review", name=name, p=state["ap_pass"],
                    r=state["ap_review"], e=state["ap_error"],
                    reason=reason), COLORS["warning"]
            status.configure(text=text, fg=fg)

        def _ap_start_failed(err):
            if not win.winfo_exists():
                return
            state["running"] = False
            start_btn.configure(state="normal")
            stop_btn.configure(state="disabled")
            status.configure(text=self._t("ap_start_failed", err=err[:140]),
                             fg=COLORS["danger"])

        if host is None:
            win.protocol("WM_DELETE_WINDOW",
                         lambda: (_stop(), win.destroy()))
        else:
            host.close_hook = _stop  # tools 面板关闭时停表（防泄漏）
        bus.start()
