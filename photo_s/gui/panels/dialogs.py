"""photo_s/gui/panels/dialogs.py — 工具工作流对话框：去重/挑片/重命名/校验和/画廊/联系表/对比/预设/分析。

v2.6 结构项首批：从 app.py 平移（方法体逐字节保留，
仅函数级相对导入加深一层）。Mixin 无独立状态，全部经 ``self`` 与
PhotoSApp 共享；新面板代码继续按此模式落位，app.py 不再膨胀。
"""

import os
import sys
import threading
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..bus import UiBus
from ..theme import (COLORS, PLATFORM_FONTS, FONT_BODY,
                     FONT_BUTTON, FONT_SECTION, FONT_SMALL, FONT_TINY)
from ..widgets import (FlatButton, _ZoomPanState, _open_image_safe,
                       canvas_unbind_safe)


class WorkflowDialogsMixin:
    """工具工作流对话框：去重/挑片/重命名/校验和/画廊/联系表/对比/预设/分析。"""

    def _hosted_frame(self, host, title):
        """v2.6 非模态化：Tools 内嵌面板模式的对话框窗体——标题 + × 关闭
        头行，其余内容照 Toplevel 路径构建（两种模式共用 win 变量）。"""
        win = tk.Frame(host, bg=COLORS["bg"])
        win.pack(fill="both", expand=True)
        head = tk.Frame(win, bg=COLORS["bg"])
        head.pack(fill="x", pady=(0, 6))
        tk.Label(head, text=title, font=FONT_BODY,
                 fg=COLORS["text"], bg=COLORS["bg"]).pack(side="left")
        FlatButton(
            head, text="×", command=self._tools_close_panel,
            bg=COLORS["bg"], fg=COLORS["text_secondary"],
            hover_bg=COLORS["border"], font=FONT_SMALL, padx=6, pady=1,
            border_color=COLORS["border"]).pack(side="right")
        return win

    def _show_dedup(self, host=None):
        """Duplicate viewer: scan in a background thread, render groups
        with per-image keep-checkboxes (sharpest pre-checked), move the
        unchecked ones into a ``_duplicates_trash`` subfolder."""
        if not self.files:
            messagebox.showinfo(self._t("dedup_title"),
                                self._t("gallery_need_files"))
            return
        files = self._checked_files()
        if not files:
            messagebox.showinfo(self._t("dedup_title"),
                                self._t("check_none"))
            return

        if host is not None:
            win = self._hosted_frame(host, self._t("dedup_title"))
        else:
            win = tk.Toplevel(self.root)
            win.title(self._t("dedup_title"))
            win.geometry("980x660")
            win.configure(bg=COLORS["bg"])
            win.transient(self.root)
        canvas_unbind_safe(win)

        header = tk.Frame(win, bg=COLORS["bg"])
        header.pack(fill="x", padx=20, pady=(16, 4))
        tk.Label(header, text=self._t("dedup_title"),
                 font=(PLATFORM_FONTS["title"], 14, "bold"),
                 fg=COLORS["text"], bg=COLORS["bg"]).pack(side="left")
        status_lbl = tk.Label(header, text="", font=FONT_SMALL,
                              fg=COLORS["text_secondary"], bg=COLORS["bg"])
        status_lbl.pack(side="left", padx=(16, 0))

        # Scrollable group area
        holder = tk.Frame(win, bg=COLORS["bg"])
        holder.pack(fill="both", expand=True, padx=20, pady=8)
        canvas = tk.Canvas(holder, bg=COLORS["bg"], highlightthickness=0,
                           borderwidth=0)
        sb = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=COLORS["bg"])
        canvas.create_window((0, 0), window=inner, anchor="nw")

        def _sync_scroll(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        inner.bind("<Configure>", _sync_scroll)

        def _on_mw(event):
            if inner.winfo_reqheight() > canvas.winfo_height():
                canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

        canvas.bind("<Enter>",
                    lambda e: canvas.bind_all("<MouseWheel>", _on_mw))
        canvas.bind("<Leave>",
                    lambda e: canvas.unbind_all("<MouseWheel>"))

        footer = tk.Frame(win, bg=COLORS["bg"])
        footer.pack(fill="x", padx=20, pady=(4, 16))

        state = {"groups": [], "scores": {}, "checks": [], "sharp": set()}

        # Worker→UI marshalling queue (see gallery dialog for rationale)
        bus = UiBus(win)
        schedule = bus.schedule
        bus.start()

        def render():
            for w in inner.winfo_children():
                w.destroy()
            state["checks"] = []
            state["sharp"] = set()
            groups, scores = state["groups"], state["scores"]
            if not groups:
                tk.Label(inner, text=self._t("dedup_none"), font=FONT_BODY,
                         fg=COLORS["text_secondary"],
                         bg=COLORS["bg"]).pack(pady=40)
                execute_btn.configure(state="disabled")
                return
            from PIL import Image, ImageTk
            for gi, group in enumerate(groups):
                card = tk.Frame(inner, bg=COLORS["card"], bd=0,
                                highlightthickness=0)
                card.pack(fill="x", padx=2, pady=(0, 10))
                head = tk.Frame(card, bg=COLORS["card"])
                head.pack(fill="x", padx=12, pady=(10, 4))
                tk.Label(head, text=self._t("dedup_group", i=gi + 1),
                         font=(PLATFORM_FONTS["body"], 12, "bold"),
                         fg=COLORS["text"], bg=COLORS["card"]).pack(
                    side="left")
                tk.Label(head, text="· {}".format(
                    self._t("files_count", n=len(group))), font=FONT_SMALL,
                    fg=COLORS["text_secondary"], bg=COLORS["card"]).pack(
                    side="left", padx=(8, 0))
                row = tk.Frame(card, bg=COLORS["card"])
                row.pack(fill="x", padx=12, pady=(0, 12))
                sharpest = max(group,
                               key=lambda p: scores.get(p, 0.0))
                state["sharp"].add(sharpest)
                for p in group:
                    cell = tk.Frame(row, bg=COLORS["card"])
                    cell.pack(side="left", padx=6)
                    try:
                        img = _open_image_safe(p).convert("RGB")
                        img.thumbnail((150, 150), Image.LANCZOS)
                        photo = ImageTk.PhotoImage(img, master=cell)
                        lbl = tk.Label(cell, image=photo, bg=COLORS["bg"],
                                       bd=0, highlightthickness=0)
                        lbl.image = photo  # keep the reference alive
                        lbl.pack()
                    except Exception:
                        tk.Label(cell, text="?", width=12, height=6,
                                 bg=COLORS["bg"],
                                 fg=COLORS["text_secondary"]).pack()
                    cap = os.path.basename(p)
                    if len(cap) > 16:
                        cap = cap[:15] + "…"
                    star = " " + self._t("dedup_sharpest") \
                        if p == sharpest else ""
                    tk.Label(cell, text=cap + star, font=FONT_TINY,
                             fg=COLORS["text_secondary"],
                             bg=COLORS["card"]).pack()
                    tk.Label(cell, text="{} {:.1f}".format(
                        self._t("dedup_blur"), scores.get(p, 0.0)),
                        font=FONT_TINY, fg=COLORS["text_secondary"],
                        bg=COLORS["card"]).pack()
                    var = tk.BooleanVar(value=(p == sharpest))
                    ttk.Checkbutton(cell, text=self._t("dedup_keep"),
                                    variable=var).pack(pady=(2, 0))
                    state["checks"].append((p, var))
            execute_btn.configure(state="normal")

        def scan_thread():
            try:
                def cb(cur, total):
                    schedule(lambda: status_lbl.configure(
                        text=self._t("dedup_scanning", n=cur, total=total)))

                groups, scores = self._dedup_scan(list(files),
                                                  progress_cb=cb)
            except Exception as e:
                schedule(lambda err=str(e): _scan_failed(err))
                return
            schedule(lambda: _scanned(groups, scores))

        def _scan_failed(err):
            if not win.winfo_exists():
                return
            status_lbl.configure(text=self._t("op_failed", err=err),
                                 fg=COLORS["danger"])

        def _scanned(groups, scores):
            if not win.winfo_exists():
                return
            state["groups"], state["scores"] = groups, scores
            status_lbl.configure(text="")
            render()

        def execute():
            unchecked = [p for p, var in state["checks"] if not var.get()]
            if not unchecked:
                messagebox.showinfo(self._t("dedup_title"),
                                    self._t("dedup_none_selected"))
                return
            if not messagebox.askyesno(
                    self._t("dedup_title"),
                    self._t("dedup_confirm", n=len(unchecked))):
                return
            # single trash dir next to the first file's folder
            trash_dir = os.path.join(os.path.dirname(files[0]),
                                     "_duplicates_trash")
            execute_btn.configure(state="disabled")

            def move_thread():
                try:
                    def cb(cur, total):
                        schedule(lambda: status_lbl.configure(
                            text="{} {}/{}".format(self._t("dedup_moving"),
                                                   cur, total)))

                    moved, failed, moved_map = self._dedup_move_to_trash(
                        unchecked, trash_dir, progress_cb=cb)
                except Exception as e:
                    schedule(lambda err=str(e): _scan_failed(err))
                    return
                schedule(lambda: _moved(moved, failed, moved_map, unchecked,
                                        trash_dir))

            def _moved(moved, failed, moved_map, unchecked, trash_dir):
                if not win.winfo_exists():
                    return
                # Only files that actually moved leave the UI — a failed
                # move must keep its row (set(unchecked) would hide it).
                moved_set = set(moved_map)
                self.files = [f for f in self.files if f not in moved_set]
                self._checked -= moved_set
                self._refresh_file_list()
                self._update_stats()
                state["groups"] = [
                    [p for p in g if p not in moved_set]
                    for g in state["groups"]]
                state["groups"] = [g for g in state["groups"]
                                   if len(g) >= 2]
                state["scores"] = {p: s for p, s in state["scores"].items()
                                   if p not in moved_set}
                msg = self._t("dedup_moved", n=moved, dir=trash_dir)
                if failed:
                    msg += "（{} 失败）".format(failed)
                status_lbl.configure(text=msg, fg=COLORS["accent"])
                if moved_map:
                    self._push_undo(
                        self._t("undo_dedup", n=len(moved_map)),
                        lambda: self._restore_dedup(dict(moved_map)))
                render()

            threading.Thread(target=move_thread, daemon=True).start()

        execute_btn = FlatButton(
            footer, text=self._t("dedup_execute"), command=execute,
            bg=COLORS["accent"])
        execute_btn.configure(state="disabled")
        execute_btn.pack(side="left")
        FlatButton(
            footer, text=self._t("dedup_rescan"),
            command=lambda: threading.Thread(target=scan_thread,
                                             daemon=True).start(),
            bg=COLORS["bg"], fg=COLORS["text"], hover_bg=COLORS["border"],
            border_color=COLORS["border"]).pack(side="left", padx=(8, 0))
        FlatButton(
            footer, text=self._t("close"), command=win.destroy,
            bg=COLORS["bg"], fg=COLORS["text"], hover_bg=COLORS["border"],
            border_color=COLORS["border"]).pack(side="right")

        threading.Thread(target=scan_thread, daemon=True).start()

    def _show_cull(self, host=None):
        """Cull: classify the file list by exposure/sharpness thresholds,
        then optionally keep only the matches (removing the rest, undoable)."""
        if not self.files:
            messagebox.showinfo(self._t("cull_title"),
                                self._t("cull_no_files"))
            return

        if host is not None:
            win = self._hosted_frame(host, self._t("cull_title"))
        else:
            win = tk.Toplevel(self.root)
            win.title(self._t("cull_title"))
            win.geometry("640x540")
            win.configure(bg=COLORS["bg"])
            win.transient(self.root)

        body = tk.Frame(win, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=20, pady=16)
        body.columnconfigure(1, weight=1)

        ov = tk.StringVar(); un = tk.StringVar()
        lmin = tk.StringVar(); lmax = tk.StringVar(); shp = tk.StringVar()
        state = {"results": None}

        def _row(row, label_key, var, hint=""):
            tk.Label(body, text=self._t(label_key) + (hint or ""),
                     font=FONT_SMALL, fg=COLORS["text_secondary"],
                     bg=COLORS["bg"]).grid(row=row, column=0, sticky="w",
                                           pady=(0, 6), padx=(0, 10))
            ttk.Entry(body, textvariable=var, font=FONT_BODY, width=10).grid(
                row=row, column=1, sticky="w", pady=(0, 6))

        _row(0, "cull_overexposed", ov, " %")
        _row(1, "cull_underexposed", un, " %")
        _row(2, "cull_lum_min", lmin)
        _row(3, "cull_lum_max", lmax)
        _row(4, "cull_sharp", shp)

        def _thresholds():
            def _num(v):
                v = v.get().strip()
                try:
                    return float(v) if v else None
                except ValueError:
                    return None  # non-numeric input → threshold unset
            return {"overexposed_max": _num(ov),
                    "underexposed_max": _num(un),
                    "luminance_min": _num(lmin),
                    "luminance_max": _num(lmax),
                    "sharpness_min": _num(shp)}

        btns = tk.Frame(body, bg=COLORS["bg"])
        btns.grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 8))
        scan_btn = FlatButton(btns, text=self._t("cull_scan"),
                              command=lambda: _scan(),
                              bg=COLORS["accent"],
                              hover_bg=COLORS["accent_hover"])
        scan_btn.pack(side="left")
        apply_btn = FlatButton(btns, text=self._t("cull_apply"),
                               command=lambda: _apply(),
                               bg=COLORS["card"], fg=COLORS["text"],
                               hover_bg=COLORS["bg"],
                               border_color=COLORS["border"])
        apply_btn.pack(side="left", padx=(8, 0))
        apply_btn.configure(state="disabled")

        status = tk.Label(body, text="", font=FONT_SMALL,
                          fg=COLORS["text_secondary"], bg=COLORS["bg"])
        status.grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 6))

        tree = ttk.Treeview(body, columns=("lum", "over", "under", "blur",
                                           "kept"), show="headings",
                            height=12)
        for c, w, t in (("lum", 60, self._t("cull_lum_min").replace(
                             "Luminance min", "Lum")),
                        ("over", 50, "%"), ("under", 50, "%"),
                        ("blur", 50, "blur"), ("kept", 50, "✓")):
            tree.heading(c, text=t)
            tree.column(c, width=w, anchor="center")
        tree.column("lum", width=70)
        vsb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.grid(row=7, column=0, columnspan=3, sticky="nsew")
        vsb.grid(row=7, column=3, sticky="ns")
        body.rowconfigure(7, weight=1)

        bus = UiBus(win)
        schedule = bus.schedule

        def _scan():
            scan_btn.configure(state="disabled")
            status.configure(text=self._t("preview_render"))
            th = _thresholds()

            def run():
                try:
                    results = self._cull_scan(self.files, th)
                    schedule(lambda: _scanned(results))
                except Exception as e:
                    schedule(lambda err=str(e): status.configure(
                        text=self._t("cull_failed", err=err),
                        fg=COLORS["danger"]))

            threading.Thread(target=run, daemon=True).start()

        def _scanned(results):
            if not win.winfo_exists():
                return
            scan_btn.configure(state="normal")
            state["results"] = results
            kept = sum(1 for r in results if r["kept"])
            status.configure(
                text=self._t("cull_kept", kept=kept, total=len(results)),
                fg=COLORS["accent"])
            for item in tree.get_children():
                tree.delete(item)
            for r in results:
                tree.insert("", "end", values=(
                    f"{r['luminance']:.2f}", f"{r['overexposed_pct']:.1f}",
                    f"{r['underexposed_pct']:.1f}",
                    r.get("blur_score", "-"),
                    "✓" if r["kept"] else "✗"))
            apply_btn.configure(state="normal")

        def _apply():
            if self.processing:
                status.configure(text=self._t("cull_processing"),
                                 fg=COLORS["warning"])
                return
            results = state.get("results")
            if not results:
                return
            kept = [r["path"] for r in results if r["kept"]]
            kept_set = set(kept)
            removed = [(i, f) for i, f in enumerate(self.files)
                       if f not in kept_set]
            if not removed:
                return
            was_checked = set(self._checked - kept_set)
            self.files = kept
            self._checked &= kept_set
            self._refresh_file_list()
            self._update_stats()
            self._push_undo(self._t("undo_cull", n=len(removed)),
                            lambda: self._restore_removed(list(removed),
                                                          set(was_checked)),
                            lambda: self._redo_remove(list(removed),
                                                      set(was_checked)))
            status.configure(text=self._t("cull_kept", kept=len(kept),
                                          total=len(self.files)),
                             fg=COLORS["success"])


        bus.start()

    def _show_rename(self, host=None):
        """Batch rename with live preview: template + options on top, a
        Treeview mapping old -> new names (in-batch conflicts and errors
        flagged), refreshed by a debounced background dry-run on every
        change. Execute confirms, runs the real rename in a worker, then
        refreshes the main file list. Not wired into the undo stack."""
        from ...rename import rename_files

        files = self._checked_files()
        if not files:
            messagebox.showinfo(self._t("rename_title"),
                                self._t("check_none"))
            return

        if host is not None:
            win = self._hosted_frame(host, self._t("rename_title"))
        else:
            win = tk.Toplevel(self.root)
            win.title(self._t("rename_title"))
            win.geometry("880x560")
            win.configure(bg=COLORS["bg"])
            win.transient(self.root)
        canvas_unbind_safe(win)

        body = tk.Frame(win, bg=COLORS["bg"])
        body.pack(fill="x", padx=20, pady=(16, 0))
        body.columnconfigure(2, weight=1)

        pattern_var = tk.StringVar(
            value=self.rename_pattern.get().strip() or "{date}_{seq}")
        mode_var = tk.StringVar(value="inplace")
        dir_var = tk.StringVar(value="")
        overwrite_var = tk.BooleanVar(value=False)

        tk.Label(body, text=self._t("rename_pattern_lbl"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).grid(
            row=0, column=0, sticky="w", padx=(0, 10), pady=(0, 4))
        ttk.Entry(body, textvariable=pattern_var, font=FONT_BODY).grid(
            row=0, column=1, columnspan=3, sticky="ew", pady=(0, 4))
        tk.Label(body, text=self._t("rename_vars"), font=FONT_TINY,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).grid(
            row=1, column=1, columnspan=3, sticky="w", pady=(0, 8))

        ttk.Radiobutton(body, text=self._t("rename_mode_inplace"),
                        variable=mode_var, value="inplace",
                        command=lambda: _options_changed()).grid(
            row=2, column=0, sticky="w", padx=(0, 10), pady=(0, 8))
        ttk.Radiobutton(body, text=self._t("rename_mode_copy"),
                        variable=mode_var, value="copy",
                        command=lambda: _options_changed()).grid(
            row=2, column=1, sticky="w", padx=(0, 10), pady=(0, 8))
        dir_entry = ttk.Entry(body, textvariable=dir_var, font=FONT_BODY)
        dir_entry.grid(row=2, column=2, sticky="ew", pady=(0, 8))

        def _browse_dir():
            if self._dlg_cooldown_active():
                return
            folder = filedialog.askdirectory(
                title=self._t("rename_mode_copy"))
            self._after_file_dialog()
            if folder:
                dir_var.set(folder)

        browse_btn = FlatButton(body, text=self._t("browse"),
                                command=_browse_dir,
                                bg=COLORS["card"], fg=COLORS["text"],
                                hover_bg=COLORS["bg"],
                                border_color=COLORS["border"],
                                font=FONT_SMALL)
        browse_btn.grid(row=2, column=3, sticky="w", padx=(8, 0),
                        pady=(0, 8))

        ttk.Checkbutton(body, text=self._t("rename_overwrite"),
                        variable=overwrite_var,
                        command=lambda: _queue_preview()).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(0, 4))

        holder = tk.Frame(win, bg=COLORS["bg"])
        holder.pack(fill="both", expand=True, padx=20, pady=8)
        tree = ttk.Treeview(holder, columns=("old", "new", "status"),
                            show="headings", height=14)
        tree.heading("old", text=self._t("rename_col_old"))
        tree.heading("new", text=self._t("rename_col_new"))
        tree.heading("status", text=self._t("rename_col_status"))
        tree.column("old", width=300, anchor="w")
        tree.column("new", width=300, anchor="w")
        tree.column("status", width=220, anchor="w")
        tree.tag_configure("conflict", foreground=COLORS["warning"])
        tree.tag_configure("error", foreground=COLORS["danger"])
        sb = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)

        footer = tk.Frame(win, bg=COLORS["bg"])
        footer.pack(fill="x", padx=20, pady=(4, 16))

        # Worker→UI marshalling queue (see dedup dialog for rationale)
        bus = UiBus(win)
        schedule = bus.schedule
        bus.start()

        state = {"after_id": None, "token": 0, "rows": []}

        def _status_text(row):
            if row["status"] == "conflict":
                return self._t("rename_status_conflict")
            if row["status"] == "error":
                return row["error"]
            return ""

        def _render_rows(rows):
            tree.delete(*tree.get_children())
            for row in rows:
                new = os.path.basename(row["output"]) \
                    if row["output"] else "—"
                tag = row["status"] \
                    if row["status"] in ("conflict", "error") else ""
                tree.insert("", "end", values=(
                    os.path.basename(row["input"]), new,
                    _status_text(row)), tags=(tag,) if tag else ())

        def _current_options():
            out = dir_var.get().strip() if mode_var.get() == "copy" else ""
            return pattern_var.get(), out or None, overwrite_var.get()

        def _queue_preview(*_):
            if not win.winfo_exists():
                return
            if state["after_id"] is not None:
                try:
                    win.after_cancel(state["after_id"])
                except tk.TclError:
                    pass
            state["after_id"] = win.after(300, _start_preview)

        def _start_preview():
            state["after_id"] = None
            if not win.winfo_exists():
                return
            pattern, out, ow = _current_options()
            if mode_var.get() == "copy" and not out:
                state["rows"] = []
                state["token"] += 1
                _render_rows([])
                status_lbl.configure(text=self._t("rename_need_dir"),
                                     fg=COLORS["warning"])
                execute_btn.configure(state="disabled")
                return
            execute_btn.configure(state="normal")
            state["token"] += 1
            token = state["token"]
            status_lbl.configure(text=self._t("rename_preview_updating"),
                                 fg=COLORS["text_secondary"])

            def run():
                try:
                    rows = self._rename_preview(files, pattern,
                                                output_dir=out,
                                                overwrite=ow)
                except Exception as e:
                    schedule(lambda err=str(e): _preview_failed(token, err))
                    return
                schedule(lambda: _preview_done(token, rows))

            threading.Thread(target=run, daemon=True).start()

        def _preview_failed(token, err):
            if not win.winfo_exists() or token != state["token"]:
                return
            status_lbl.configure(text=self._t("op_failed", err=err),
                                 fg=COLORS["danger"])

        def _preview_done(token, rows):
            if not win.winfo_exists() or token != state["token"]:
                return
            state["rows"] = rows
            _render_rows(rows)
            conflicts = sum(1 for r in rows if r["status"] == "conflict")
            errors = sum(1 for r in rows if r["status"] == "error")
            status_lbl.configure(
                text=self._t("rename_counts", n=len(rows), c=conflicts,
                             e=errors),
                fg=COLORS["warning"] if (conflicts or errors)
                else COLORS["text_secondary"])

        def _options_changed():
            copying = mode_var.get() == "copy"
            dir_entry.configure(state="normal" if copying else "disabled")
            browse_btn.configure(state="normal" if copying else "disabled")
            _queue_preview()

        def _execute():
            pattern, out, ow = _current_options()
            if mode_var.get() == "copy" and not out:
                messagebox.showinfo(self._t("rename_title"),
                                    self._t("rename_need_dir"))
                return
            if not messagebox.askyesno(
                    self._t("rename_title"),
                    self._t("rename_confirm", n=len(files))):
                return
            # conflict count from the last preview — the real run resolves
            # them via _N suffixes, so its own rows only know ok/error
            conflicts = sum(1 for r in state["rows"]
                            if r["status"] == "conflict")
            execute_btn.configure(state="disabled")

            def run():
                try:
                    results = rename_files(list(files), pattern,
                                           output_dir=out, overwrite=ow)
                except Exception as e:
                    schedule(lambda err=str(e): _execute_failed(err))
                    return
                schedule(lambda: _executed(results, conflicts))

            threading.Thread(target=run, daemon=True).start()

        def _execute_failed(err):
            if not win.winfo_exists():
                return
            execute_btn.configure(state="normal")
            status_lbl.configure(text=self._t("op_failed", err=err),
                                 fg=COLORS["danger"])

        def _executed(results, conflicts):
            if not win.winfo_exists():
                return
            execute_btn.configure(state="normal")
            ok = sum(1 for r in results if r["status"] == "ok")
            errors = sum(1 for r in results if r["status"] == "error")
            if mode_var.get() == "inplace":
                # keep the main list pointing at the renamed paths
                renamed = {r["input"]: r["output"] for r in results
                           if r["status"] == "ok" and r["output"]}
                if renamed:
                    self.files = [renamed.get(f, f) for f in self.files]
                    self._checked = {renamed.get(f, f)
                                     for f in self._checked}
                    files[:] = [renamed.get(f, f) for f in files]
            self._refresh_file_list()
            state["rows"] = results
            _render_rows(results)
            msg = self._t("rename_done", ok=ok, c=conflicts, e=errors)
            status_lbl.configure(text=msg, fg=COLORS["accent"])
            messagebox.showinfo(self._t("rename_title"), msg)

        def _on_close():
            if state["after_id"] is not None:
                try:
                    win.after_cancel(state["after_id"])
                except tk.TclError:
                    pass
                state["after_id"] = None
            win.destroy()

        if host is None:
            win.protocol("WM_DELETE_WINDOW", _on_close)
        else:
            host.close_hook = _on_close

        execute_btn = FlatButton(
            footer, text=self._t("rename_execute"), command=_execute,
            bg=COLORS["accent"], hover_bg=COLORS["accent_hover"])
        execute_btn.pack(side="left")
        status_lbl = tk.Label(footer, text="", font=FONT_SMALL,
                              fg=COLORS["text_secondary"], bg=COLORS["bg"])
        status_lbl.pack(side="left", padx=(12, 0))
        FlatButton(
            footer, text=self._t("close"), command=_on_close,
            bg=COLORS["bg"], fg=COLORS["text"], hover_bg=COLORS["border"],
            border_color=COLORS["border"]).pack(side="right")

        pattern_var.trace_add("write", lambda *_: _queue_preview())
        dir_var.trace_add("write", lambda *_: _queue_preview())
        _options_changed()          # syncs dir-entry state + first preview

    def _show_hash(self, host=None):
        """Checksums: generate a manifest of the checked files, or verify an
        existing one."""
        if host is not None:
            win = self._hosted_frame(host, self._t("hash_title"))
        else:
            win = tk.Toplevel(self.root)
            win.title(self._t("hash_title"))
            win.geometry("600x500")
            win.configure(bg=COLORS["bg"])
            win.transient(self.root)

        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=12, pady=12)

        # ── Generate tab ──
        gen = tk.Frame(nb, bg=COLORS["bg"])
        nb.add(gen, text=self._t("hash_tab_gen"))
        gen.columnconfigure(1, weight=1)
        out_var = tk.StringVar(value=os.path.join(os.getcwd(),
                                                  "manifest.csv"))
        status_g = tk.Label(gen, text="", font=FONT_SMALL,
                            fg=COLORS["text_secondary"], bg=COLORS["bg"])
        status_g.grid(row=0, column=0, columnspan=3, sticky="w", pady=(4, 8))
        tk.Label(gen, text=self._t("hash_output"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).grid(
            row=1, column=0, sticky="w", padx=(0, 10), pady=(0, 6))
        ttk.Entry(gen, textvariable=out_var, font=FONT_BODY).grid(
            row=1, column=1, sticky="ew", pady=(0, 6))

        def _browse_out():
            if self._dlg_cooldown_active():
                return
            p = filedialog.asksaveasfilename(
                defaultextension=".csv", initialfile="manifest.csv",
                filetypes=[("CSV", "*.csv")])
            self._after_file_dialog()
            if p:
                out_var.set(p)

        FlatButton(gen, text=self._t("browse"), command=_browse_out,
                   bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
                   border_color=COLORS["border"],
                   font=FONT_SMALL).grid(row=1, column=2, sticky="w",
                                         padx=(8, 0), pady=(0, 6))
        open_g = FlatButton(gen, text=self._t("hash_open"),
                            command=lambda: _open_path(out_var.get()),
                            bg=COLORS["card"], fg=COLORS["text"],
                            hover_bg=COLORS["bg"],
                            border_color=COLORS["border"], font=FONT_SMALL)
        open_g.grid(row=2, column=1, sticky="w", pady=(4, 0))
        open_g.grid_remove()
        FlatButton(gen, text=self._t("hash_generate"), command=lambda: _gen(),
                   bg=COLORS["accent"],
                   hover_bg=COLORS["accent_hover"]).grid(
            row=2, column=0, sticky="w", pady=(4, 0))

        # ── Verify tab ──
        ver = tk.Frame(nb, bg=COLORS["bg"])
        nb.add(ver, text=self._t("hash_tab_verify"))
        ver.columnconfigure(1, weight=1)
        manifest_var = tk.StringVar()
        status_v = tk.Label(ver, text="", font=FONT_SMALL,
                            fg=COLORS["text_secondary"], bg=COLORS["bg"])
        status_v.grid(row=0, column=0, columnspan=3, sticky="w", pady=(4, 8))

        def _browse_manifest():
            if self._dlg_cooldown_active():
                return
            p = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
            self._after_file_dialog()
            if p:
                manifest_var.set(p)

        tk.Label(ver, text=self._t("hash_choose"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).grid(
            row=1, column=0, sticky="w", padx=(0, 10), pady=(0, 6))
        ttk.Entry(ver, textvariable=manifest_var, font=FONT_BODY).grid(
            row=1, column=1, sticky="ew", pady=(0, 6))
        FlatButton(ver, text=self._t("browse"), command=_browse_manifest,
                   bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
                   border_color=COLORS["border"],
                   font=FONT_SMALL).grid(row=1, column=2, sticky="w",
                                         padx=(8, 0), pady=(0, 6))
        FlatButton(ver, text=self._t("hash_verify"), command=lambda: _ver(),
                   bg=COLORS["accent"], hover_bg=COLORS["accent_hover"]).grid(
            row=2, column=0, sticky="w", pady=(4, 0))
        tree = ttk.Treeview(ver, columns=("kind", "detail"), show="headings",
                            height=10)
        tree.heading("kind", text="")
        tree.heading("detail", text="")
        tree.column("kind", width=90, anchor="w")
        tree.column("detail", width=420, anchor="w")
        tree.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        ver.rowconfigure(3, weight=1)

        bus = UiBus(win)
        schedule = bus.schedule

        def _gen():
            files = self._checked_files()
            if not files:
                status_g.configure(text=self._t("hash_no_files"),
                                   fg=COLORS["warning"])
                return
            status_g.configure(text=self._t("preview_render"))
            output = out_var.get().strip()

            def run():
                try:
                    self._hash_generate(files, output)
                    schedule(lambda: _gen_done())
                except Exception as e:
                    schedule(lambda err=str(e): status_g.configure(
                        text=self._t("hash_failed", err=err),
                        fg=COLORS["danger"]))

            threading.Thread(target=run, daemon=True).start()

        def _gen_done():
            if not win.winfo_exists():
                return
            status_g.configure(
                text=self._t("hash_done", path=out_var.get(),
                             n=len(self._checked_files())),
                fg=COLORS["success"])
            open_g.grid()

        def _ver():
            m = manifest_var.get().strip()
            if not m:
                return
            status_v.configure(text=self._t("preview_render"))

            def run():
                try:
                    report = self._hash_verify(m)
                    schedule(lambda: _ver_done(report))
                except Exception as e:
                    schedule(lambda err=str(e): status_v.configure(
                        text=self._t("hash_failed", err=err),
                        fg=COLORS["danger"]))

            threading.Thread(target=run, daemon=True).start()

        def _ver_done(report):
            if not win.winfo_exists():
                return
            ok_all = (report["missing"] == [] and report["mismatched"] == [])
            status_v.configure(
                text=" · ".join(filter(None, [
                    self._t("hash_total", n=report["total"]),
                    self._t("hash_ok", n=report["ok"]),
                    (self._t("hash_missing", n=len(report["missing"]))
                     if report["missing"] else ""),
                    (self._t("hash_mismatched", n=len(report["mismatched"]))
                     if report["mismatched"] else ""),
                ])) or self._t("hash_all_ok"),
                fg=COLORS["success"] if ok_all else COLORS["danger"])
            for item in tree.get_children():
                tree.delete(item)
            for p in report["missing"]:
                tree.insert("", "end", values=(self._t("hash_missing", n=1),
                                               p))
            for mm in report["mismatched"]:
                tree.insert("", "end", values=(
                    self._t("hash_mismatched", n=1),
                    f"{mm['path']}  (expected {mm['expected'][:12]}… "
                    f"got {mm['actual'][:12]}…)"))

        def _open_path(p):
            if p and os.path.isfile(p):
                webbrowser.open(Path(os.path.abspath(p)).as_uri())


        bus.start()

    def _show_gallery_export(self, host=None):
        """Gallery export dialog: title + thumb size + output dir, then
        build the HTML gallery in a background thread (thumbnail
        rendering can take a while)."""
        if not self.files:
            messagebox.showinfo(self._t("gallery_title"),
                                self._t("gallery_need_files"))
            return
        files = self._checked_files()
        if not files:
            messagebox.showinfo(self._t("gallery_title"),
                                self._t("check_none"))
            return

        if host is not None:
            win = self._hosted_frame(host, self._t("gallery_title"))
        else:
            win = tk.Toplevel(self.root)
            win.title(self._t("gallery_title"))
            win.geometry("480x360")
            win.configure(bg=COLORS["bg"])
            win.transient(self.root)

        body = tk.Frame(win, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=20, pady=16)
        body.columnconfigure(0, weight=1)

        tk.Label(body, text=self._t("gallery_name"), font=FONT_BODY,
                 fg=COLORS["text"], bg=COLORS["bg"]).grid(
            row=0, column=0, sticky="w", pady=(0, 2))
        title_var = tk.StringVar(value="PhotoS Gallery")
        ttk.Entry(body, textvariable=title_var, font=FONT_BODY).grid(
            row=1, column=0, sticky="ew", pady=(0, 10))

        tk.Label(body, text=self._t("gallery_thumb"), font=FONT_BODY,
                 fg=COLORS["text"], bg=COLORS["bg"]).grid(
            row=2, column=0, sticky="w", pady=(0, 2))
        thumb_combo = ttk.Combobox(
            body, values=("240", "360", "480", "600"),
            state="readonly", font=FONT_BODY, width=8)
        thumb_combo.set("360")
        thumb_combo.grid(row=3, column=0, sticky="w", pady=(0, 10))

        tk.Label(body, text=self._t("gallery_out"), font=FONT_BODY,
                 fg=COLORS["text"], bg=COLORS["bg"]).grid(
            row=4, column=0, sticky="w", pady=(0, 2))
        out_row = tk.Frame(body, bg=COLORS["bg"])
        out_row.grid(row=5, column=0, sticky="ew", pady=(0, 10))
        out_var = tk.StringVar(value=self.output_dir.get())
        ttk.Entry(out_row, textvariable=out_var, font=FONT_BODY).pack(
            side="left", fill="x", expand=True)

        def _browse_out():
            if self._dlg_cooldown_active():
                return
            picked = filedialog.askdirectory(title=self._t("gallery_out"))
            self._after_file_dialog()
            if picked:
                out_var.set(picked)

        FlatButton(
            out_row, text=self._t("browse"), command=_browse_out,
            bg=COLORS["bg"], fg=COLORS["text"], hover_bg=COLORS["border"],
            font=FONT_SMALL, padx=10, pady=3,
            border_color=COLORS["border"]).pack(side="left", padx=(8, 0))

        status_lbl = tk.Label(body, text="", font=FONT_SMALL,
                              fg=COLORS["text_secondary"], bg=COLORS["bg"])
        status_lbl.grid(row=6, column=0, sticky="w", pady=(0, 8))

        btns = tk.Frame(body, bg=COLORS["bg"])
        btns.grid(row=7, column=0, sticky="w")
        state = {"output": None}

        # Worker threads must never touch Tk directly: they put UI
        # callbacks on a queue and a main-thread after-loop drains it
        # (win.after from a worker raises "main thread is not in main
        # loop" whenever the mainloop is not running).
        bus = UiBus(win)
        schedule = bus.schedule
        bus.start()

        def set_status(text, color=None):
            if win.winfo_exists():
                status_lbl.configure(
                    text=text, fg=color or COLORS["text_secondary"])

        def run(out_dir, title, thumb):
            # Tk variables are read in the button command (main thread) and
            # handed in as plain values — touching out_var/title_combo from
            # this worker thread is unsafe under non-threaded Tcl.
            if not out_dir:
                schedule(lambda: set_status(
                    self._t("gallery_need_dir"), COLORS["danger"]))
                return
            schedule(lambda: (
                generate_btn.configure(state="disabled"),
                set_status(self._t("gallery_generating"))))
            try:
                res = self._gallery_build(
                    list(files), out_dir,
                    title=title,
                    thumb_size=int(thumb))
            except Exception as e:
                schedule(lambda err=str(e): _failed(err))
            else:
                schedule(lambda: _done(res))

        def _failed(err):
            if not win.winfo_exists():
                return
            generate_btn.configure(state="normal")
            set_status(self._t("gallery_error", err=err), COLORS["danger"])

        def _done(res):
            if not win.winfo_exists():
                return
            state["output"] = res["output"]
            generate_btn.configure(state="normal")
            set_status(self._t("gallery_done", count=res["count"],
                               path=res["output"]), COLORS["accent"])
            open_btn.pack(side="left", padx=(8, 0))

        generate_btn = FlatButton(
            btns, text=self._t("gallery_generate"),
            command=lambda: threading.Thread(
                target=run,
                args=(out_var.get().strip(),
                      title_var.get().strip() or "PhotoS Gallery",
                      thumb_combo.get()),
                daemon=True).start(),
            bg=COLORS["accent"])
        generate_btn.pack(side="left")
        open_btn = FlatButton(
            btns, text=self._t("gallery_open"),
            command=lambda: state["output"]
            and webbrowser.open(Path(state["output"]).as_uri()),
            bg=COLORS["bg"], fg=COLORS["text"], hover_bg=COLORS["border"],
            border_color=COLORS["border"])

    def _show_contact_sheet(self, host=None):
        """Contact sheet: grid of thumbnails from the checked files."""
        files = self._checked_files()
        if not files:
            if not self.files:
                messagebox.showinfo(self._t("contact_title"),
                                    self._t("contact_need_files"))
            else:
                messagebox.showinfo(self._t("contact_title"),
                                    self._t("check_none"))
            return

        if host is not None:
            win = self._hosted_frame(host, self._t("contact_title"))
        else:
            win = tk.Toplevel(self.root)
            win.title(self._t("contact_title"))
            win.geometry("480x400")
            win.configure(bg=COLORS["bg"])
            win.transient(self.root)

        body = tk.Frame(win, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=20, pady=16)
        body.columnconfigure(1, weight=1)

        out_var = tk.StringVar(value=os.path.join(
            os.getcwd(), "contact_sheet.png"))
        cols_var = tk.StringVar(value="4")
        thumb_var = tk.StringVar(value="240x240")
        cap_var = tk.BooleanVar(value=True)
        bg_var = tk.StringVar(value="#000000")

        def _row(row, label_key, var, browse=False):
            tk.Label(body, text=self._t(label_key), font=FONT_SMALL,
                     fg=COLORS["text_secondary"], bg=COLORS["bg"]).grid(
                row=row, column=0, sticky="w", pady=(0, 6), padx=(0, 10))
            ttk.Entry(body, textvariable=var, font=FONT_BODY).grid(
                row=row, column=1, sticky="ew", pady=(0, 6))
            if browse:
                def _browse():
                    if self._dlg_cooldown_active():
                        return
                    p = filedialog.asksaveasfilename(
                        defaultextension=".png",
                        initialfile=os.path.basename(var.get()),
                        filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg"),
                                   ("WebP", "*.webp")])
                    self._after_file_dialog()
                    if p:
                        var.set(p)
                FlatButton(body, text=self._t("browse"), command=_browse,
                           bg=COLORS["card"], fg=COLORS["text"],
                           hover_bg=COLORS["bg"],
                           border_color=COLORS["border"],
                           font=FONT_SMALL).grid(
                    row=row, column=2, sticky="w", padx=(8, 0), pady=(0, 6))

        _row(0, "contact_output", out_var, browse=True)
        _row(2, "contact_cols", cols_var)
        _row(3, "contact_thumb", thumb_var)
        ttk.Checkbutton(body, text=self._t("contact_caption"),
                        variable=cap_var).grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(2, 2))
        _row(5, "contact_bg", bg_var)

        status = tk.Label(body, text="", font=FONT_SMALL,
                          fg=COLORS["text_secondary"], bg=COLORS["bg"])
        status.grid(row=6, column=0, columnspan=3, sticky="w", pady=(8, 0))

        open_btn = FlatButton(body, text=self._t("contact_open"),
                              command=lambda: _open(),
                              bg=COLORS["card"], fg=COLORS["text"],
                              hover_bg=COLORS["bg"],
                              border_color=COLORS["border"],
                              font=FONT_SMALL)
        open_btn.grid(row=7, column=1, sticky="w", pady=(8, 0))
        open_btn.grid_remove()

        gen_btn = FlatButton(body, text=self._t("contact_generate"),
                             command=lambda: _generate(),
                             bg=COLORS["accent"],
                             hover_bg=COLORS["accent_hover"])
        gen_btn.grid(row=7, column=0, sticky="w", pady=(8, 0))

        bus = UiBus(win)
        schedule = bus.schedule

        def _parse_thumb():
            from ...cli import _parse_dimensions
            try:
                tw, th = _parse_dimensions(thumb_var.get().strip())
                return (tw or 240, th or 240)
            except Exception:
                return (240, 240)

        def _parse_cols():
            try:
                return max(1, int(cols_var.get()))
            except (ValueError, TypeError):
                return 4

        def _parse_bg():
            from ...adjust import hex_to_rgb
            try:
                return hex_to_rgb(bg_var.get().strip())
            except (ValueError, AttributeError):
                status.configure(text=self._t("contact_bad_bg"),
                                 fg=COLORS["warning"])
                return (0, 0, 0)

        def _generate():
            gen_btn.configure(state="disabled")
            status.configure(text=self._t("preview_render"))
            output = out_var.get().strip()
            captions = cap_var.get()
            bg = _parse_bg()
            cols = _parse_cols()      # parsed on the MAIN thread — the old
            thumb = _parse_thumb()    # worker read cols_var/thumb_var itself

            def run():
                try:
                    result = self._contact_sheet_build(
                        files, output, cols=cols,
                        thumb_size=thumb, captions=captions, bg=bg)
                    schedule(lambda: _done(result))
                except Exception as e:
                    schedule(lambda err=str(e): _done(None, err))

            threading.Thread(target=run, daemon=True).start()

        def _done(result, err=None):
            if not win.winfo_exists():
                return
            gen_btn.configure(state="normal")
            if err or not result:
                status.configure(text=self._t("contact_failed",
                                              err=err or "?"),
                                 fg=COLORS["danger"])
                return
            status.configure(text=self._t("contact_done", path=result),
                             fg=COLORS["success"])
            open_btn.grid()

        def _open():
            p = out_var.get().strip()
            if p and os.path.isfile(p):
                webbrowser.open(Path(os.path.abspath(p)).as_uri())


        bus.start()

    def _show_compare(self, host=None):
        """Multi-image compare viewer: 2-4 checked images side by side on
        canvases. Wheel-zoom and drag-pan apply only to the panel under
        the cursor; the "sync zoom" checkbox makes the wheel zoom every
        panel together. Double-click resets all panels. Each redraw
        renders only the visible region (PIL resize with a source box),
        debounced to ~60ms; originals are decoded once in a worker
        thread."""
        from PIL import Image, ImageTk

        files = self._checked_files()
        if len(files) < 2:
            messagebox.showinfo(self._t("compare_view_title"),
                                self._t("compare_need_two"))
            return
        files = files[:4]

        if host is not None:
            win = self._hosted_frame(host, self._t("compare_view_title"))
        else:
            win = tk.Toplevel(self.root)
            win.title(self._t("compare_view_title"))
            win.geometry("1100x640")
            win.configure(bg=COLORS["bg"])
            win.transient(self.root)
        canvas_unbind_safe(win)

        panels = []
        pending = [None]  # after() id of the debounced redraw

        tk.Label(win, text=self._t("compare_hint"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).pack(
            pady=(12, 0))

        row = tk.Frame(win, bg=COLORS["bg"])
        row.pack(fill="both", expand=True, padx=16, pady=12)

        for i, path in enumerate(files):
            col = tk.Frame(row, bg=COLORS["card"], bd=0, highlightthickness=0)
            col.pack(side="left", fill="both", expand=True,
                     padx=(0 if i == 0 else 4, 0))
            tk.Label(col, text=os.path.basename(path), font=FONT_TINY,
                     fg=COLORS["text_secondary"], bg=COLORS["card"]).pack(
                fill="x", padx=6, pady=(4, 0))
            canvas = tk.Canvas(col, bg=COLORS["card"], highlightthickness=0,
                               bd=0)
            canvas.pack(fill="both", expand=True, padx=4, pady=4)
            panels.append({"path": path, "canvas": canvas, "img": None,
                           "iw": 0, "ih": 0, "scale": None, "photo": None,
                           "error": False, "state": _ZoomPanState()})

        def _schedule_redraw():
            # Debounce: wheel/drag/Configure storms merge into one redraw.
            if pending[0] is None:
                pending[0] = win.after(60, _redraw)

        def _redraw():
            pending[0] = None
            if not win.winfo_exists():
                return
            for p in panels:
                canvas = p["canvas"]
                cw, ch = canvas.winfo_width(), canvas.winfo_height()
                if cw < 2 or ch < 2:
                    continue  # not mapped yet; <Configure> will retrigger
                img = p["img"]
                if img is None:
                    canvas.delete("all")
                    canvas.create_text(
                        cw / 2, ch / 2, font=FONT_SMALL,
                        text=self._t("cannot_load") if p["error"]
                        else self._t("compare_loading"),
                        fill=COLORS["danger"] if p["error"]
                        else COLORS["text_secondary"])
                    continue
                iw, ih = p["iw"], p["ih"]
                # Visible source window: the 1/zoom fraction centered on
                # (fx, fy) — always on-image thanks to the state clamp.
                st = p["state"]
                vw, vh = iw / st.zoom, ih / st.zoom
                left = min(max(st.fx * iw - vw / 2, 0.0), iw - vw)
                top = min(max(st.fy * ih - vh / 2, 0.0), ih - vh)
                # Fit the window into the canvas preserving aspect (the
                # canvas background letterboxes the difference).
                scale = min(cw / vw, ch / vh)
                tw = max(1, int(vw * scale))
                th = max(1, int(vh * scale))
                p["scale"] = scale
                view = img.resize((tw, th), Image.LANCZOS,
                                  box=(left, top, left + vw, top + vh))
                photo = ImageTk.PhotoImage(view, master=canvas)
                p["photo"] = photo  # keep a reference or it is GC'd
                canvas.delete("all")
                canvas.create_image(cw / 2, ch / 2, image=photo)

        sync_zoom = tk.BooleanVar(value=False)

        def _zoom_step(factor, p=None):
            # Default: zoom only the panel under the cursor. With the
            # "sync zoom" checkbox on, every panel zooms together.
            if sync_zoom.get() or p is None:
                for q_ in panels:
                    q_["state"].zoom_at(factor)
            else:
                p["state"].zoom_at(factor)
            _schedule_redraw()

        def _make_wheel(p):
            def _on_wheel(event):
                # macOS trackpads/wheels give ±1-ish deltas, Windows ±120;
                # only the direction matters here.
                _zoom_step(1.1 if event.delta > 0 else 1 / 1.1, p)
            return _on_wheel

        drag = {"x": 0, "y": 0, "panel": None}

        def _make_press(p):
            def _on_press(event):
                drag["x"], drag["y"], drag["panel"] = event.x, event.y, p
            return _on_press

        def _on_drag(event):
            p = drag["panel"]
            if p is None or p["img"] is None or not p["scale"]:
                return
            dx, dy = event.x - drag["x"], event.y - drag["y"]
            drag["x"], drag["y"] = event.x, event.y
            # The image follows the cursor, so the view center moves the
            # other way. Pan only the panel under the cursor.
            p["state"].pan(-dx / (p["scale"] * p["iw"]),
                           -dy / (p["scale"] * p["ih"]))
            _schedule_redraw()

        def _on_double(_event):
            # Global reset: re-fit every panel (zoom + center).
            for p in panels:
                p["state"].fit()
            _schedule_redraw()

        for p in panels:
            c = p["canvas"]
            c.bind("<Configure>", lambda _e: _schedule_redraw())
            c.bind("<MouseWheel>", _make_wheel(p))
            if sys.platform.startswith("linux"):
                # X11 reports wheel scrolling as buttons 4/5, not
                # <MouseWheel>.
                c.bind("<Button-4>", lambda _e, p=p: _zoom_step(1.1, p))
                c.bind("<Button-5>", lambda _e, p=p: _zoom_step(1 / 1.1, p))
            c.bind("<ButtonPress-1>", _make_press(p))
            c.bind("<B1-Motion>", _on_drag)
            c.bind("<Double-Button-1>", _on_double)

        bottom = tk.Frame(win, bg=COLORS["bg"])
        bottom.pack(fill="x", padx=16, pady=(0, 12))
        ttk.Checkbutton(bottom, text=self._t("compare_sync_zoom"),
                        variable=sync_zoom).pack(side="left")
        FlatButton(bottom, text=self._t("close"), command=win.destroy,
                   bg=COLORS["accent"], hover_bg=COLORS["accent_hover"],
                   font=FONT_BUTTON, padx=24, pady=6).pack(side="right")

        bus = UiBus(win)
        schedule = bus.schedule

        def _load_done(p, img):
            p["img"] = img
            p["iw"], p["ih"] = img.size
            _schedule_redraw()

        def _load_failed(p):
            p["error"] = True
            _schedule_redraw()

        def _load_all():
            for p in panels:
                try:
                    # convert() forces the decode here in the worker —
                    # Image.open alone is lazy and would decode on the UI
                    # thread at first paint.
                    img = _open_image_safe(p["path"]).convert("RGB")
                except Exception:
                    schedule(lambda p=p: _load_failed(p))
                else:
                    schedule(lambda p=p, img=img: _load_done(p, img))


        threading.Thread(target=_load_all, daemon=True).start()
        bus.start()
        _schedule_redraw()  # paint the loading placeholders right away

    def _show_presets(self, host=None):
        """Presets: save / load / delete named option sets (stored as JSON in
        ~/.photos/presets). Load applies the preset back onto the settings."""
        if host is not None:
            win = self._hosted_frame(host, self._t("presets_title"))
        else:
            win = tk.Toplevel(self.root)
            win.title(self._t("presets_title"))
            win.geometry("520x440")
            win.configure(bg=COLORS["bg"])
            win.transient(self.root)

        from ... import presets

        body = tk.Frame(win, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=20, pady=16)
        body.columnconfigure(1, weight=1)

        tk.Label(body, text=self._t("presets_list"), font=FONT_BODY,
                 fg=COLORS["text"], bg=COLORS["bg"]).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        listbox = tk.Listbox(body, height=8, font=FONT_BODY,
                             selectmode=tk.SINGLE,
                             bg=COLORS["card"], fg=COLORS["text"],
                             highlightthickness=0,
                             relief=tk.FLAT)
        listbox.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        body.rowconfigure(1, weight=1)

        tk.Label(body, text=self._t("presets_name"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).grid(
            row=2, column=0, sticky="w", padx=(0, 10), pady=(0, 6))
        name_var = tk.StringVar()
        ttk.Entry(body, textvariable=name_var, font=FONT_BODY).grid(
            row=2, column=1, columnspan=2, sticky="ew", pady=(0, 6))
        tk.Label(body, text=self._t("presets_desc"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).grid(
            row=3, column=0, sticky="w", padx=(0, 10), pady=(0, 6))
        desc_var = tk.StringVar()
        ttk.Entry(body, textvariable=desc_var, font=FONT_BODY).grid(
            row=3, column=1, columnspan=2, sticky="ew", pady=(0, 6))

        status = tk.Label(body, text="", font=FONT_SMALL,
                          fg=COLORS["text_secondary"], bg=COLORS["bg"])
        status.grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))

        btns = tk.Frame(body, bg=COLORS["bg"])
        btns.grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))
        FlatButton(btns, text=self._t("presets_save"), command=lambda: _save(),
                   bg=COLORS["accent"], hover_bg=COLORS["accent_hover"]
                   ).pack(side="left")
        FlatButton(btns, text=self._t("presets_load"), command=lambda: _load(),
                   bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
                   border_color=COLORS["border"]).pack(side="left", padx=(8, 0))
        FlatButton(btns, text=self._t("presets_delete"),
                   command=lambda: _delete(),
                   bg=COLORS["card"], fg=COLORS["danger"],
                   hover_bg=COLORS["danger_hover"],
                   border_color=COLORS["border"]).pack(side="left", padx=(8, 0))

        def _refresh():
            listbox.delete(0, tk.END)
            try:
                items = presets.list_presets()
            except Exception:
                items = []
            if not items:
                listbox.insert(tk.END, self._t("presets_empty"))
                listbox.itemconfig(0, fg=COLORS["text_secondary"])
            for it in items:
                listbox.insert(tk.END, it)

        def _selected_name():
            sel = listbox.curselection()
            if not sel:
                return None
            item = listbox.get(sel[0])
            if item == self._t("presets_empty"):
                return None
            return item.split(" — ", 1)[0]

        def _save():
            name = name_var.get().strip()
            if not name:
                status.configure(text=self._t("presets_name_required"),
                                 fg=COLORS["warning"])
                return
            try:
                presets.save_preset(name, self._build_options(),
                                    desc_var.get().strip())
            except Exception as e:
                status.configure(text=self._t("presets_load_failed",
                                              name=str(e)),
                                 fg=COLORS["danger"])
                return
            status.configure(text=self._t("presets_saved"),
                             fg=COLORS["success"])
            _refresh()

        def _load():
            name = _selected_name()
            if not name:
                return
            try:
                opts = presets.load_preset(name)
            except Exception:
                opts = None
            if opts is None:
                status.configure(text=self._t("presets_load_failed",
                                              name=name),
                                 fg=COLORS["danger"])
                return
            self._apply_options_to_ui(opts)
            status.configure(text=self._t("presets_loaded", name=name),
                             fg=COLORS["success"])

        def _delete():
            name = _selected_name()
            if not name:
                return
            if not messagebox.askyesno(
                    self._t("presets_title"),
                    self._t("presets_confirm_delete", name=name)):
                return
            try:
                presets.delete_preset(name)
            except Exception as e:
                status.configure(text=self._t("presets_load_failed",
                                              name=str(e)),
                                 fg=COLORS["danger"])
                return
            status.configure(text=self._t("presets_deleted", name=name),
                             fg=COLORS["success"])
            _refresh()

        _refresh()

    def _show_analysis(self, host=None):
        """Dialog showing exposure / sharpness stats + luminance histogram
        for the currently selected file (via photo_s.metrics)."""
        from ...metrics import compute_exposure_stats, compute_blur_score

        selected = list(self._selected_rows)
        if not selected:
            messagebox.showwarning(self._t("analyze_title"),
                                   self._t("analyze_none"))
            return
        path = selected[0]

        stats = compute_exposure_stats(path)
        if not stats.get("ok"):
            messagebox.showerror(self._t("analyze_title"),
                                 self._t("analyze_err"))
            return

        if host is not None:
            win = self._hosted_frame(
                host, "{} — {}".format(self._t("analyze_title"),
                                      os.path.basename(path)))
        else:
            win = tk.Toplevel(self.root)
            win.title("{} — {}".format(self._t("analyze_title"),
                                   os.path.basename(path)))
            win.configure(bg=COLORS["bg"])
            win.transient(self.root)
            win.resizable(False, False)

        inner = tk.Frame(win, bg=COLORS["bg"])
        inner.pack(padx=24, pady=20)

        def stat_row(label, value, color=None):
            row = tk.Frame(inner, bg=COLORS["bg"])
            row.pack(anchor="w", fill="x", pady=1)
            tk.Label(row, text=label, font=FONT_SMALL,
                     fg=COLORS["text_secondary"], bg=COLORS["bg"],
                     width=22, anchor="w").pack(side="left")
            tk.Label(row, text=value, font=FONT_SMALL,
                     fg=color or COLORS["text"], bg=COLORS["bg"]).pack(side="left")

        stat_row(self._t("analyze_luminance"),
                 "{:.3f}".format(stats["luminance"]))
        stat_row(self._t("analyze_over"),
                 "{:.2f}%".format(stats["overexposed_pct"]),
                 COLORS["danger"] if stats["overexposed_pct"] > 0
                 else COLORS["text"])
        stat_row(self._t("analyze_under"),
                 "{:.2f}%".format(stats["underexposed_pct"]),
                 COLORS["warning"] if stats["underexposed_pct"] > 0
                 else COLORS["text"])
        try:
            blur = compute_blur_score(path)
            stat_row(self._t("analyze_blur"), "{:.1f}".format(blur))
        except Exception:
            pass

        # Luminance histogram (from the same grayscale sample)
        tk.Label(inner, text=self._t("analyze_histogram"),
                 font=FONT_SECTION, fg=COLORS["text"],
                 bg=COLORS["bg"]).pack(anchor="w", pady=(14, 6))
        canvas = tk.Canvas(inner, width=360, height=120, bg=COLORS["card"],
                           highlightthickness=0, bd=0)
        canvas.pack()

        from PIL import Image
        img = _open_image_safe(path)
        sample = img.convert("L").copy()
        sample.thumbnail((256, 256))
        hist = sample.histogram()  # 256 bins

        max_bin = max(hist) or 1
        bins = 64  # aggregate into 64 bars
        bar_w = 360 / bins
        for i in range(bins):
            lo = i * 4
            hi = lo + 4
            h = sum(hist[lo:hi]) / max_bin
            h = max(h * 100, 1.0)  # min visible bar
            color = COLORS["accent"] if 30 <= lo <= 225 else COLORS["border"]
            canvas.create_rectangle(i * bar_w, 120 - h,
                                    (i + 1) * bar_w, 120,
                                    fill=color, outline="")

        FlatButton(inner, text=self._t("close"), command=win.destroy,
                   bg=COLORS["accent"], hover_bg=COLORS["accent_hover"],
                   font=FONT_BUTTON, padx=24, pady=6).pack(pady=(16, 0))
