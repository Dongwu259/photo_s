"""photo_s/gui/panels/review.py — 审查灯箱（v2.5 内嵌 Library）+ EXIF 评级/标签/关键词编辑。

v2.6 结构项首批：从 app.py 平移（方法体逐字节保留，
仅函数级相对导入加深一层）。Mixin 无独立状态，全部经 ``self`` 与
PhotoSApp 共享；新面板代码继续按此模式落位，app.py 不再膨胀。
"""

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..bus import UiBus
from ..theme import COLORS, PLATFORM_FONTS, FONT_BODY, FONT_SMALL
from ..widgets import FlatButton, _exif_datetime_str, _open_image_safe


class ReviewPanelMixin:
    """审查灯箱（v2.5 内嵌 Library）+ EXIF 评级/标签/关键词编辑。"""

    def _review_save(self, path, rating=None, label=None, keywords=None,
                     title=None, make=None, model=None, lens=None, iso=None,
                     shutter=None, aperture=None, date=None):
        """Sync: write rating/label/keywords/title + camera/lens/shooting-
        field diffs into ``path``'s EXIF (PhotoS: UserComment segment for
        the first four; standard EXIF tags for the rest — ``aperture`` maps
        to the engine's ``fnumber`` key, ``date`` to ``datetime``).
        Only changed fields are touched: None leaves a field alone, a
        string ("" included) writes/clears it. Returns (ok, message,
        revert, entry): revert undoes this exact write (None when
        nothing changed); entry is the global undo entry pushed (None
        likewise). Tk-free so tests can call it directly."""
        from ...engine import apply_exif_tags, read_exif_metadata

        m = read_exif_metadata(path)
        tags = {}
        if rating is not None and rating != m.get("rating"):
            tags["rating"] = rating
        lb = (label or "").strip() if label is not None else None
        if lb is not None and lb != (m.get("label") or ""):
            tags["label"] = lb
        kw = (keywords or "").strip()
        if kw != ",".join(m.get("keywords") or []):
            tags["keywords"] = kw
        tl = (title or "").strip()
        if tl != (m.get("title") or ""):
            tags["title"] = tl
        # (argument, meta key holding the current value, engine tag);
        # meta key None → the current value is the normalized
        # date+time pair (EXIF DateTimeOriginal form).
        prev_extra = {}
        for value, meta_key, tag in (
                (make, "make", "make"),
                (model, "camera", "model"),
                (lens, "lens", "lens"),
                (iso, "iso", "iso"),
                (shutter, "shutter", "shutter"),
                (aperture, "fnumber", "fnumber"),
                (date, None, "datetime")):
            if value is None:
                continue
            cur = (_exif_datetime_str(m) if meta_key is None
                   else str(m.get(meta_key) or "").strip())
            prev_extra[tag] = cur
            v = str(value).strip()
            if v != cur:
                tags[tag] = v
        if not tags:
            return True, "", None, None
        prev = {"rating": m.get("rating"),
                "label": m.get("label") or "",
                "keywords": ",".join(m.get("keywords") or []),
                "title": m.get("title") or ""}
        prev.update(prev_extra)
        try:
            msg = apply_exif_tags(path, tags)
        except Exception as e:
            return False, self._t("review_save_failed", err=str(e)), None, None
        if msg.startswith("⚠️"):
            return False, msg, None, None

        def revert():
            # full restore — None / "" explicitly clear the fields
            # (engine clear semantics, added for undo)
            t = {"rating": prev["rating"],
                 "label": prev["label"],
                 "keywords": prev["keywords"],
                 "title": prev["title"]}
            for tag in prev_extra:
                t[tag] = prev[tag]
            apply_exif_tags(path, t)

        entry = self._push_undo(
            self._t("undo_tag", name=os.path.basename(path)), revert)
        return True, msg, revert, entry

    def _show_review(self):
        """v2.5: 审查灯箱并入 Library（原独立 Toplevel 弹窗）。

        切到 Library 并把文件列表区换成内嵌灯箱：导航 / 0-5 星 / 关键词
        标题 / 拍摄信息编辑 / 精选淘汰双阈值分拣。EXIF 写走 _review_save
        （UserComment 分段，部分更新保留其他标签）；作用域 = 勾选照片；
        Esc / 关闭退出回网格。⌘E 入口不变。
        """
        if not self.files:
            messagebox.showinfo(self._t("review_title"),
                                self._t("review_none"))
            return
        all_paths = self._checked_files()
        if not all_paths:
            messagebox.showinfo(self._t("review_title"),
                                self._t("check_none"))
            return
        if self._active_module != "library":
            self._show_module("library")
        if getattr(self, "_lib_lightbox_active", False):
            self._exit_library_lightbox()  # 保存挂起编辑后重建
        self._lib_lightbox_active = True
        self._lib_lightbox_frame = tk.Frame(self._lib_lightbox_host,
                                            bg=COLORS["bg"])
        start = next(iter(self._selected_rows or ()), None)
        self._lib_lightbox_ctl = self._build_review_ui(
            self._lib_lightbox_frame, all_paths, hosted=True,
            start_path=start if start in all_paths else None)
        self._lib_lightbox_frame.pack(fill="both", expand=True)
        self._lib_lightbox_apply_layout()

    def _exit_library_lightbox(self):
        """退出灯箱回网格：冲掉输入框里未提交的关键词/标题（即改即写
        语义与弹窗 OK 一致），刷新网格行内星标。"""
        ctl = self._lib_lightbox_ctl
        self._lib_lightbox_ctl = None
        self._lib_lightbox_active = False
        if ctl is not None:
            ctl["close"]()
        if self._lib_lightbox_frame is not None:
            self._lib_lightbox_frame.destroy()
            self._lib_lightbox_frame = None
        self._lib_lightbox_apply_layout()
        cache = getattr(self, "_lib_rating_cache", None)
        if cache is not None:
            cache.clear()
        lcache = getattr(self, "_lib_label_cache", None)
        if lcache is not None:
            lcache.clear()
        self._lib_draw()

    def _lib_lightbox_apply_layout(self):
        """Library 卡片内 pack 切换：文件网格 ↔ 内嵌灯箱（工具栏不动）。"""
        if getattr(self, "_lib_lightbox_active", False):
            self._lib_list_frame.pack_forget()
            self._lib_lightbox_host.pack(fill="both", expand=True,
                                         padx=14, pady=12)
        else:
            self._lib_lightbox_host.pack_forget()
            self._lib_list_frame.pack(fill="both", expand=True,
                                      padx=14, pady=12)

    def _build_review_ui(self, host, all_paths, *, hosted=False,
                         start_path=None):
        """Lightbox review UI — 弹窗/内嵌共用构建器。

        导航 / 0-5 星评级 / 关键词标题 / 拍摄信息 / 评分关键词筛选 /
        精选淘汰分拣。``hosted=True`` 由 Library 内嵌（退出走
        ``self._exit_library_lightbox``），否则 host 为 Toplevel（诊断
        路径）。返回 ``{close, set_rating, go, undo}`` 控制器。
        """
        import importlib.util

        from ...engine import read_exif_metadata
        has_piexif = importlib.util.find_spec("piexif") is not None

        initial_idx = (all_paths.index(start_path)
                       if start_path and start_path in all_paths else 0)
        state = {"seq": [], "meta": {}, "idx": 0, "rating": None,
                 "label": "", "photo": None, "reverts": {}}

        header = tk.Frame(host, bg=COLORS["bg"])
        header.pack(fill="x", padx=20, pady=(14, 4))
        tk.Label(header, text=self._t("review_title"),
                 font=(PLATFORM_FONTS["title"], 14, "bold"),
                 fg=COLORS["text"], bg=COLORS["bg"]).pack(side="left")
        pos_lbl = tk.Label(header, text="", font=FONT_BODY,
                           fg=COLORS["text_secondary"], bg=COLORS["bg"])
        pos_lbl.pack(side="left", padx=(16, 0))
        status_lbl = tk.Label(header, text="", font=FONT_SMALL,
                              fg=COLORS["text_secondary"], bg=COLORS["bg"])
        status_lbl.pack(side="right")

        if not has_piexif:
            tk.Label(host, text=self._t("review_no_piexif"), font=FONT_SMALL,
                     fg=COLORS["danger"], bg=COLORS["bg"]).pack(
                anchor="w", padx=20)

        # Image area + shooting-info line
        img_lbl = tk.Label(host, bg=COLORS["bg"])
        img_lbl.pack(fill="both", expand=True, padx=20, pady=8)
        info_lbl = tk.Label(host, text="", font=FONT_SMALL,
                            fg=COLORS["text_secondary"], bg=COLORS["bg"])
        info_lbl.pack(fill="x", padx=20, pady=(0, 2))

        # Nav + rating row
        ctrl = tk.Frame(host, bg=COLORS["bg"])
        ctrl.pack(fill="x", padx=20, pady=(0, 6))
        nav = tk.Frame(ctrl, bg=COLORS["bg"])
        nav.pack(side="left")
        prev_btn = FlatButton(
            nav, text=self._t("review_prev"), command=lambda: go(-1),
            bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"], font=FONT_SMALL)
        prev_btn.pack(side="left")
        next_btn = FlatButton(
            nav, text=self._t("review_next"), command=lambda: go(1),
            bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"], font=FONT_SMALL)
        next_btn.pack(side="left", padx=(8, 0))

        rating_box = tk.Frame(ctrl, bg=COLORS["bg"])
        rating_box.pack(side="left", padx=(20, 0))
        tk.Label(rating_box, text=self._t("review_rating"), font=FONT_BODY,
                 fg=COLORS["text"], bg=COLORS["bg"]).pack(
            side="left", padx=(0, 6))
        rating_btns = {}
        for n in range(6):
            btn = FlatButton(
                rating_box, text="{}★".format(n),
                command=lambda n=n: set_rating(n),
                bg=COLORS["card"], fg=COLORS["text"],
                hover_bg=COLORS["bg"], border_color=COLORS["border"],
                font=FONT_SMALL, padx=10, pady=3)
            btn.pack(side="left", padx=(4, 0))
            rating_btns[n] = btn

        # v2.6 P2: LR color labels next to the stars — same write path
        # (EXIF UserComment → XMP xmp:Label on write-back), keyboard 6-9
        # in the grid, buttons here cover all five colors + clear
        label_box = tk.Frame(ctrl, bg=COLORS["bg"])
        label_box.pack(side="left", padx=(16, 0))
        tk.Label(label_box, text=self._t("review_label"), font=FONT_BODY,
                 fg=COLORS["text"], bg=COLORS["bg"]).pack(
            side="left", padx=(0, 6))
        label_btns = {}
        for name in self._LABELS:
            btn = FlatButton(
                label_box, text=self._t("label_" + name.lower()),
                command=lambda n=name: set_label(n),
                bg=COLORS["card"], fg=COLORS["text"],
                hover_bg=COLORS["bg"], border_color=COLORS["border"],
                font=FONT_SMALL, padx=8, pady=3)
            btn.pack(side="left", padx=(3, 0))
            label_btns[name] = btn
        label_clear_btn = FlatButton(
            label_box, text="×",
            command=lambda: set_label(""),
            bg=COLORS["card"], fg=COLORS["text"],
            hover_bg=COLORS["bg"], border_color=COLORS["border"],
            font=FONT_SMALL, padx=6, pady=3)
        label_clear_btn.pack(side="left", padx=(3, 0))

        # Keywords + title row
        fields = tk.Frame(host, bg=COLORS["bg"])
        fields.pack(fill="x", padx=20, pady=(0, 4))
        tk.Label(fields, text=self._t("review_keywords"), font=FONT_BODY,
                 fg=COLORS["text"], bg=COLORS["bg"]).pack(side="left")
        keywords_var = tk.StringVar()
        ttk.Entry(fields, textvariable=keywords_var, font=FONT_BODY).pack(
            side="left", fill="x", expand=True, padx=(8, 16))
        tk.Label(fields, text=self._t("review_title_lbl"), font=FONT_BODY,
                 fg=COLORS["text"], bg=COLORS["bg"]).pack(side="left")
        title_var = tk.StringVar()
        ttk.Entry(fields, textvariable=title_var, font=FONT_BODY).pack(
            side="left", fill="x", expand=True, padx=(8, 0))
        save_btn = FlatButton(
            fields, text=self._t("review_save"),
            command=lambda: save_current(),
            bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"], font=FONT_SMALL, padx=10, pady=3)
        save_btn.pack(side="left", padx=(8, 0))
        FlatButton(
            fields, text=self._t("undo"),
            command=lambda: undo_current(),
            bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"], font=FONT_SMALL, padx=10, pady=3
        ).pack(side="left", padx=(8, 0))

        # Shooting-info editor: make / model / lens / ISO / shutter /
        # aperture / date. Filled from the current image's metadata on
        # every navigation; on save, unchanged fields go out as None so
        # only real edits hit the file (_review_save diffs again anyway).
        exif = tk.Frame(host, bg=COLORS["bg"])
        exif.pack(fill="x", padx=20, pady=(0, 4))
        tk.Label(exif, text=self._t("review_shooting"), font=FONT_BODY,
                 fg=COLORS["text"], bg=COLORS["bg"]).grid(
            row=0, column=0, rowspan=2, sticky="nw", pady=2)
        exif_rows = (
            (("make", "review_make", 12), ("model", "review_model", 14),
             ("lens", "review_lens", 18), ("iso", "review_iso", 6)),
            (("shutter", "review_shutter", 9),
             ("aperture", "review_aperture", 7),
             ("date", "review_date", 20)),
        )
        exif_vars = {}
        for r, row_fields in enumerate(exif_rows):
            col = 1
            for name, lbl_key, width in row_fields:
                tk.Label(exif, text=self._t(lbl_key), font=FONT_SMALL,
                         fg=COLORS["text_secondary"], bg=COLORS["bg"]).grid(
                    row=r, column=col, sticky="w", padx=(12, 4), pady=1)
                var = tk.StringVar()
                exif_vars[name] = var
                ttk.Entry(exif, textvariable=var, font=FONT_SMALL,
                          width=width).grid(
                    row=r, column=col + 1, sticky="w", pady=1)
                col += 2

        # Filter row
        filt = tk.Frame(host, bg=COLORS["bg"])
        filt.pack(fill="x", padx=20, pady=(0, 14))
        tk.Label(filt, text=self._t("review_filter"), font=FONT_BODY,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).pack(
            side="left")
        tk.Label(filt, text=self._t("review_min_rating"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).pack(
            side="left", padx=(10, 4))
        min_rating_var = tk.StringVar(value="0")
        ttk.Combobox(filt, values=("0", "1", "2", "3", "4", "5"),
                     textvariable=min_rating_var, state="readonly",
                     width=3, font=FONT_SMALL).pack(side="left")
        tk.Label(filt, text=self._t("review_filter_kw"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).pack(
            side="left", padx=(10, 4))
        filter_var = tk.StringVar()
        ttk.Entry(filt, textvariable=filter_var, font=FONT_SMALL,
                  width=16).pack(side="left")
        FlatButton(
            filt, text=self._t("review_apply_filter"),
            command=lambda: apply_filter(),
            bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"], font=FONT_SMALL,
            padx=10, pady=3).pack(side="left", padx=(8, 0))
        FlatButton(
            filt, text=self._t("review_clear_filter"),
            command=lambda: clear_filter(),
            bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"], font=FONT_SMALL,
            padx=10, pady=3).pack(side="left", padx=(8, 0))
        FlatButton(
            filt, text=self._t("close"), command=lambda: on_close(),
            bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"], font=FONT_SMALL,
            padx=10, pady=3).pack(side="right")

        # Select (keeper workflow) row: after rating, move keepers/rejects to
        # the chosen folders. Acts on the currently filtered set.
        sel = tk.Frame(host, bg=COLORS["bg"])
        sel.pack(fill="x", padx=20, pady=(0, 14))
        tk.Label(sel, text=self._t("review_select_lbl"), font=FONT_BODY,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).pack(
            side="left")
        selects_var = tk.StringVar()
        ttk.Entry(sel, textvariable=selects_var, font=FONT_SMALL,
                  width=16).pack(side="left", padx=(8, 0))
        FlatButton(
            sel, text="📁",
            command=lambda: browse_dir(selects_var),
            bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"], font=FONT_SMALL,
            padx=6, pady=3).pack(side="left", padx=(2, 10))
        tk.Label(sel, text=self._t("review_rejects_lbl"), font=FONT_BODY,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).pack(
            side="left")
        rejects_var = tk.StringVar()
        ttk.Entry(sel, textvariable=rejects_var, font=FONT_SMALL,
                  width=16).pack(side="left", padx=(8, 0))
        FlatButton(
            sel, text="📁",
            command=lambda: browse_dir(rejects_var),
            bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"], font=FONT_SMALL,
            padx=6, pady=3).pack(side="left", padx=(2, 10))
        FlatButton(
            sel, text=self._t("review_select_go"),
            command=lambda: do_select(),
            bg=COLORS["accent"], fg="white", hover_bg=COLORS["accent_hover"],
            border_color=COLORS["accent"], font=FONT_SMALL,
            padx=12, pady=3).pack(side="left")

        def browse_dir(var):
            from tkinter import filedialog
            d = filedialog.askdirectory(
                title=self._t("review_select_browse"))
            self._after_file_dialog()
            if d:
                var.set(d)

        def do_select():
            save_current()  # persist the pending rating before sorting
            sd = selects_var.get().strip()
            rd = rejects_var.get().strip()
            if not sd and not rd:
                messagebox.showwarning(
                    self._t("app_title"),
                    self._t("review_select_need_dir"))
                return
            seq = list(state["seq"])
            if not seq:
                return
            results, okc, errc, err = self._select_move(
                seq, sd or None, rd or None, keep_min=4, reject_max=2)
            if err:
                messagebox.showerror(self._t("app_title"), err)
                return
            moved = {r["path"] for r in results
                     if r["ok"] and r["action"] in ("move", "copy")}
            # drop moved files from the queue so the lightbox advances
            state["seq"] = [p for p in state["seq"] if p not in moved]
            if not state["seq"]:
                state["seq"] = list(all_paths)
            state["idx"] = 0
            show()
            if errc:
                messagebox.showwarning(
                    self._t("app_title"),
                    self._t("review_select_done_warn",
                            ok=okc, err=errc))
            else:
                set_status(self._t("review_select_done", n=okc),
                           COLORS["accent"])

        # Worker→UI marshalling queue (see gallery dialog for rationale)
        bus = UiBus(host)
        schedule = bus.schedule
        bus.start()

        def set_status(text, color=None):
            status_lbl.configure(text=text,
                                 fg=color or COLORS["text_secondary"])

        def _fill_exif(m):
            """Push a metadata dict into the shooting-info entries."""
            exif_vars["make"].set(m.get("make") or "")
            exif_vars["model"].set(m.get("camera") or "")
            exif_vars["lens"].set(m.get("lens") or "")
            exif_vars["iso"].set(str(m.get("iso") or ""))
            exif_vars["shutter"].set(m.get("shutter") or "")
            exif_vars["aperture"].set(m.get("fnumber") or "")
            exif_vars["date"].set(_exif_datetime_str(m))

        def save_current():
            """Write rating/keywords/title + shooting-info diffs for the
            current image (unchanged shooting fields go out as None)."""
            if not state["seq"]:
                return True
            p = state["seq"][state["idx"]]
            m0 = state["meta"].get(p, {})

            def _arg(name, cur):
                v = exif_vars[name].get().strip()
                return v if v != cur else None

            ok, msg, revert, entry = self._review_save(
                p, rating=state["rating"], label=state["label"],
                keywords=keywords_var.get(),
                title=title_var.get(),
                make=_arg("make", (m0.get("make") or "").strip()),
                model=_arg("model", (m0.get("camera") or "").strip()),
                lens=_arg("lens", (m0.get("lens") or "").strip()),
                iso=_arg("iso", str(m0.get("iso") or "").strip()),
                shutter=_arg("shutter", (m0.get("shutter") or "").strip()),
                aperture=_arg("aperture",
                              (m0.get("fnumber") or "").strip()),
                date=_arg("date", _exif_datetime_str(m0)))
            if not ok:
                set_status(msg, COLORS["danger"])
                return False
            m = state["meta"].get(p, {})
            m["rating"] = state["rating"]
            m["label"] = state["label"]
            m["keywords"] = [k for k
                             in keywords_var.get().strip().split(",")
                             if k.strip()]
            m["title"] = title_var.get().strip()
            m["make"] = exif_vars["make"].get().strip()
            m["camera"] = exif_vars["model"].get().strip()
            m["lens"] = exif_vars["lens"].get().strip()
            m["iso"] = exif_vars["iso"].get().strip()
            m["shutter"] = exif_vars["shutter"].get().strip()
            m["fnumber"] = exif_vars["aperture"].get().strip()
            dt = exif_vars["date"].get().strip().replace(" ", ":").split(":")
            m["date"] = "-".join(dt[:3]) if len(dt) >= 3 else ""
            m["time"] = "-".join(dt[3:6]) if len(dt) >= 6 else ""
            if revert is not None:
                # dialog-scoped undo for THIS image (⌘Z in the lightbox)
                state["reverts"].setdefault(p, []).append((entry, revert))
            if msg:
                set_status(self._t("review_saved") + " · " + msg,
                           COLORS["accent"])
            return True

        def undo_current():
            """⌘Z / Undo button in the lightbox: revert the latest save
            on the current image and refresh the display from disk."""
            if not state["seq"]:
                return
            p = state["seq"][state["idx"]]
            stack = state["reverts"].get(p, [])
            if not stack:
                set_status(self._t("undo_none"),
                           COLORS["text_secondary"])
                return
            entry, revert = stack.pop()
            try:
                if entry in self._undo_stack:
                    self._undo_stack.remove(entry)  # keep LIFO coherent
                self._sync_undo_btn()
                revert()
            except Exception as e:
                set_status(self._t("undo_failed", err=str(e)),
                           COLORS["danger"])
                return
            try:
                m = read_exif_metadata(p)
                state["meta"][p] = m
            except Exception:
                m = state["meta"].get(p, {})
            state["rating"] = m.get("rating")
            state["label"] = m.get("label") or ""
            keywords_var.set(",".join(m.get("keywords") or []))
            title_var.set(m.get("title") or "")
            _fill_exif(m)
            _restyle_rating()
            set_status(self._t("undo_done"), COLORS["accent"])

        def _restyle_rating():
            for n, btn in rating_btns.items():
                active = (state["rating"] is not None
                          and n == state["rating"])
                btn.configure(
                    bg=COLORS["accent"] if active else COLORS["card"],
                    fg="white" if active else COLORS["text"],
                    border_color=COLORS["accent"] if active
                    else COLORS["border"])
            for name, btn in label_btns.items():
                active = name == state.get("label")
                color = self._LABEL_COLORS[name]
                btn.configure(
                    bg=color if active else COLORS["card"],
                    fg="white" if active else color,
                    border_color=color if active else COLORS["border"])
            label_clear_btn.configure(
                bg=COLORS["accent"] if not state.get("label")
                else COLORS["card"],
                fg="white" if not state.get("label") else COLORS["text"],
                border_color=COLORS["accent"] if not state.get("label")
                else COLORS["border"])

        def show():
            if not state["seq"]:
                img_lbl.configure(image="", text=self._t("review_empty"))
                info_lbl.configure(text="")
                pos_lbl.configure(text="0 / 0")
                prev_btn.configure(state="disabled")
                next_btn.configure(state="disabled")
                return
            idx = state["idx"]
            p = state["seq"][idx]
            try:
                # keep the dialog honest: re-read from disk so undo /
                # external CLI writes show up on the next navigation
                m = read_exif_metadata(p)
                state["meta"][p] = m
            except Exception:
                m = state["meta"].get(p, {})
            state["rating"] = m.get("rating")
            state["label"] = m.get("label") or ""
            keywords_var.set(",".join(m.get("keywords") or []))
            title_var.set(m.get("title") or "")
            _fill_exif(m)
            pos_lbl.configure(text=self._t("review_pos", i=idx + 1,
                                           n=len(state["seq"])))
            parts = []
            if m.get("date"):
                parts.append(m["date"])
            if m.get("camera"):
                parts.append(m["camera"])
            if m.get("iso"):
                parts.append("ISO " + str(m["iso"]))
            if m.get("focal"):
                parts.append(str(m["focal"]))
            # v2.4 WYSIWYG: photos with a develop overlay / masks render
            # through the same pipeline export uses — the lightbox shows
            # what will actually come out, never a bare original
            has_adj = (p in self._photo_adjust
                       or p in (self._photo_masks or {}))
            if has_adj:
                parts.append(self._t("export_adjusted_badge"))
            info_lbl.configure(text="  |  ".join(parts))
            prev_btn.configure(
                state="normal" if idx > 0 else "disabled")
            next_btn.configure(
                state="normal" if idx < len(state["seq"]) - 1
                else "disabled")
            _restyle_rating()
            state["photo"] = None
            try:
                from PIL import Image, ImageTk
                img = _open_image_safe(p).convert("RGB")
                img.thumbnail((900, 540), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img, master=img_lbl)
                img_lbl.configure(image=photo, text="")
                state["photo"] = photo  # keep the reference alive
            except Exception as e:
                img_lbl.configure(image="",
                                  text=os.path.basename(p) + "\n" + str(e))
            if has_adj:
                state["adj"] = (state.get("adj", 0) + 1)

                def _deliver(result, err, _tok=state["adj"]):
                    if not host.winfo_exists() or _tok != state.get("adj"):
                        return  # dialog closed / navigated away
                    if not result:
                        return  # keep the original on render failure
                    try:
                        from PIL import Image, ImageTk
                        img = _open_image_safe(result.output_path)
                        img = img.convert("RGB")
                        img.thumbnail((900, 540), Image.LANCZOS)
                        photo = ImageTk.PhotoImage(img, master=img_lbl)
                        img_lbl.configure(image=photo, text="")
                        state["photo"] = photo
                    except Exception:
                        pass  # rendered file unreadable — original stays

                self._render_adjusted_async(p, _deliver)

        def set_rating(n):
            if not state["seq"]:
                return
            state["rating"] = n
            _restyle_rating()
            save_current()

        def set_label(name):
            """Set/clear the LR color label on the current photo (persisted
            through save_current like a rating change)."""
            if not state["seq"]:
                return
            state["label"] = name or ""
            _restyle_rating()
            save_current()

        def go(delta):
            if not state["seq"]:
                return
            save_current()
            new_idx = state["idx"] + delta
            if 0 <= new_idx < len(state["seq"]):
                state["idx"] = new_idx
                show()

        def apply_filter():
            save_current()
            min_r = int(min_rating_var.get() or 0)
            kw = filter_var.get().strip().lower()
            seq = []
            for p in all_paths:
                m = state["meta"].get(p, {})
                if (m.get("rating") or 0) < min_r:
                    continue
                if kw:
                    kws = [k.lower() for k in (m.get("keywords") or [])]
                    if not any(kw in k for k in kws):
                        continue
                seq.append(p)
            state["seq"] = seq
            state["idx"] = 0
            show()

        def clear_filter():
            filter_var.set("")
            min_rating_var.set("0")
            state["seq"] = list(all_paths)
            state["idx"] = 0
            show()

        def on_close():
            save_current()
            if hosted:
                self._exit_library_lightbox()
            else:
                host.destroy()

        if not hosted:
            # 弹窗键绑定；内嵌模式的 ←/→/0-5/Esc/⌘Z 走 root 路由 +
            # _lib_lightbox_active 守卫（_lib_lightbox_key / _lib_key_rate /
            # _on_global_escape / _undo）
            def _focus_in_input():
                w = host.focus_get()
                return isinstance(w, (ttk.Entry, ttk.Combobox, tk.Entry))

            host.bind("<Left>",
                      lambda e: go(-1) if not _focus_in_input() else None)
            host.bind("<Right>",
                      lambda e: go(1) if not _focus_in_input() else None)
            for n in range(6):
                host.bind(str(n), lambda e, n=n: (
                    set_rating(n) if not _focus_in_input() else None))
            host.bind("<Escape>", lambda e: on_close())
            host.bind("<Command-z>", lambda e: undo_current())
            host.bind("<Control-z>", lambda e: undo_current())

        def scan_thread():
            try:
                def cb(cur, total):
                    schedule(lambda: set_status(
                        self._t("review_loading", n=cur, total=total)))

                meta = self._review_scan(all_paths, progress_cb=cb)
            except Exception as e:
                schedule(lambda err=str(e): set_status(
                    self._t("op_failed", err=err), COLORS["danger"]))
                return
            schedule(lambda: _scanned(meta))

        def _scanned(meta):
            if not host.winfo_exists():
                return
            state["meta"] = meta
            state["seq"] = list(all_paths)
            state["idx"] = initial_idx
            set_status("")
            show()

        if not hosted:
            host.protocol("WM_DELETE_WINDOW", on_close)
        threading.Thread(target=scan_thread, daemon=True).start()

        return {"close": save_current, "set_rating": set_rating,
                "set_label": set_label, "go": go, "undo": undo_current}
