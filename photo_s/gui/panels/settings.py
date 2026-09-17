"""photo_s/gui/panels/settings.py — 调整设置 Notebook（输出/水印/元数据/选项 Tab；Develop 侧栏复用同组变量）。

v2.6 结构项第二批：从 app.py 平移（方法体逐字节保留，
仅函数级相对导入加深一层）。Mixin 无独立状态，全部经 ``self`` 与
PhotoSApp 共享。
"""

import time
import tkinter as tk
from tkinter import ttk

from ...engine import SUPPORTED_FORMATS
from ... import watermark
from ..theme import (COLORS, PLATFORM_FONTS, FONT_BODY, FONT_SECTION,
                     FONT_SMALL, FONT_TINY)
from ..widgets import FlatButton, canvas_unbind_safe


class SettingsPanelMixin:
    """调整设置 Notebook（输出/水印/元数据/选项 Tab；Develop 侧栏复用同组变量）。"""

    def _build_settings_panel(self, parent, develop_parent):
        """Build the settings panels (v2.0 workspace split).

        ``parent`` hosts the export notebook (output / fx / metadata /
        options). ``develop_parent`` — the Develop module's right column —
        hosts the ADJUST tab contents as a standalone scroll area (it is
        the only develop tab, so no notebook). The same tk.Variables back
        both: a slider moved in Develop drives the preview there and the
        export pipeline here."""
        # Defensive: a rebuild (theme/language) destroys the old card while
        # its Enter/Leave handlers are gone, but any bind_all left behind by
        # the old panel would target a destroyed canvas. Clear it first.
        canvas_unbind_safe(parent)

        # Card container
        card = tk.Frame(parent, bg=COLORS["card"], bd=0, highlightthickness=0)
        card.pack(fill="both", expand=True)

        # v2.4: settings search — find a control by its label across tabs,
        # switch to the owning tab and highlight every hit
        search_row = tk.Frame(card, bg=COLORS["card"])
        search_row.pack(fill="x", padx=14, pady=(12, 0))
        tk.Label(search_row, text=self._t("settings_search_lbl"),
                 font=FONT_SMALL, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).pack(side="left")
        self._settings_search_var = tk.StringVar()
        search_entry = ttk.Entry(search_row,
                                textvariable=self._settings_search_var,
                                font=FONT_SMALL)
        search_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))
        search_entry.bind("<KeyRelease>",
                          lambda e: self._settings_search())

        # Category tabs (Lightroom-style): each tab is its own scroll area.
        nb = ttk.Notebook(card)
        nb.pack(fill="both", expand=True)
        self._settings_nb = nb
        self._settings_tabs = []   # (tab_widget_or_None, inner, module)

        def _make_tab_scroll(tab):
            """Scrollable canvas+inner-frame for one category tab."""
            canvas = tk.Canvas(tab, bg=COLORS["card"], highlightthickness=0, bd=0)
            scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
            inner = tk.Frame(canvas, bg=COLORS["card"])
            inner.columnconfigure(0, weight=1)
            canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")

            def _on_frame_configure(_event):
                canvas.configure(scrollregion=canvas.bbox("all"))

            def _on_canvas_configure(event):
                # Keep the inner frame as wide as the visible canvas so
                # settings are never clipped on the right edge
                canvas.itemconfigure(canvas_window, width=event.width)

            inner.bind("<Configure>", _on_frame_configure)
            canvas.bind("<Configure>", _on_canvas_configure)
            canvas.configure(yscrollcommand=scrollbar.set)
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

            # Mousewheel scrolling (bind on the tab so the handler stays alive
            # over child widgets; clamp + re-snap so trackpad momentum can't
            # wobble the view off the edge).
            _last_boundary = [0.0]

            def _on_mousewheel(event):
                delta = event.delta
                amount = -delta if abs(delta) < 10 else -delta / 120
                if time.monotonic() - _last_boundary[0] < 0.15:
                    return
                top, bottom = canvas.yview()
                if amount > 0:
                    if bottom >= 1.0 - 1e-9:
                        _last_boundary[0] = time.monotonic()
                        canvas.yview_moveto(1.0)
                        return
                elif amount < 0:
                    if top <= 1e-9:
                        _last_boundary[0] = time.monotonic()
                        canvas.yview_moveto(0.0)
                        return
                canvas.yview_scroll(amount, "units")

            def _bind_scroll(event):
                canvas.bind_all("<MouseWheel>", _on_mousewheel)

            def _unbind_scroll(event):
                canvas.unbind_all("<MouseWheel>")

            tab.bind("<Enter>", _bind_scroll)
            tab.bind("<Leave>", _unbind_scroll)
            return inner

        def _add_tab(key):
            tab = ttk.Frame(nb)
            nb.add(tab, text=self._t(key))
            self._settings_tabs.append((tab, _make_tab_scroll(tab),
                                        "export"))
            return self._settings_tabs[-1][1]

        OUT = _add_tab("tab_output")      # format/mode/resize/output/sizes/naming/subfolder
        FX = _add_tab("tab_fx")           # watermark
        META = _add_tab("tab_metadata")   # EXIF date / GPX / privacy / face blur
        OPT = _add_tab("tab_options")     # preserve/overwrite/jobs/…
        # The adjust tab lives in the Develop module (edit tools beside
        # the preview); same scroll mechanics, no notebook needed.
        adj_host = tk.Frame(develop_parent, bg=COLORS["card"], bd=0,
                            highlightthickness=0)
        adj_host.pack(fill="both", expand=True)
        ADJ = _make_tab_scroll(adj_host)
        self._settings_tabs.append((None, ADJ, "develop"))

        pad = {"padx": 18, "pady": 4}

        # ── Output Format ────────────────────────────────────────────────────
        fmt_frame = self._add_collapsible_section(OUT, "sec_format")

        self.format_combo = ttk.Combobox(
            fmt_frame, textvariable=self.output_format,
            values=list(SUPPORTED_FORMATS.keys()), state="readonly",
            font=FONT_BODY,
        )
        self.format_combo.pack(fill="x")
        ttk.Checkbutton(
            fmt_frame, text=self._t("write_xmp_label"),
            variable=self.write_xmp).pack(anchor="w", pady=(6, 0))
        # v2.6 P2: quality-gate the finished outputs (pass rate + failure
        # reasons land in the summary dialog — the audit loop agents use,
        # surfaced for humans)
        ttk.Checkbutton(
            fmt_frame, text=self._t("audit_after_export_label"),
            variable=self.audit_after_export).pack(anchor="w", pady=(4, 0))

        # ── Quality / Target Size ────────────────────────────────────────────
        # Mode toggle: radio buttons
        mode_frame = self._add_collapsible_section(OUT, "sec_mode")

        self.manual_radio = ttk.Radiobutton(
            mode_frame, text=self._t("manual_quality"), variable=self.target_size_mode,
            value=False, command=self._on_mode_change,
        )
        self.manual_radio.pack(anchor="w")

        self.target_radio = ttk.Radiobutton(
            mode_frame, text=self._t("target_size_mode"), variable=self.target_size_mode,
            value=True, command=self._on_mode_change,
        )
        self.target_radio.pack(anchor="w", pady=(4, 0))

        # ── Quality slider (shown in manual mode; ceiling in target mode) ────
        self.quality_section_frame = tk.Frame(mode_frame, bg=COLORS["card"])
        self.quality_section_frame.pack(fill="x", pady=(6, 0))

        self.quality_section_label = tk.Label(
            self.quality_section_frame, text=self._t("quality"),
            font=FONT_SMALL, fg=COLORS["text_secondary"], bg=COLORS["card"],
        )
        self.quality_section_label.pack(anchor="w")

        quality_row = tk.Frame(self.quality_section_frame, bg=COLORS["card"])
        quality_row.pack(fill="x", pady=(4, 0))

        self.quality_label = tk.Label(
            quality_row, text=str(self.quality.get()),
            font=(PLATFORM_FONTS["body"], 14, "bold"),
            fg=COLORS["accent"], bg=COLORS["card"], width=4,
        )
        self.quality_label.pack(side="right")

        self.quality_slider = ttk.Scale(
            quality_row, from_=1, to=100, variable=self.quality,
            orient="horizontal", command=self._on_quality_change,
        )
        self.quality_slider.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # ── Target size input (shown in target mode) ─────────────────────────
        self.target_section_frame = tk.Frame(mode_frame, bg=COLORS["card"])
        self.target_section_frame.pack(fill="x", pady=(6, 0))

        tk.Label(self.target_section_frame, text=self._t("target_size"),
                 font=FONT_SMALL, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).pack(anchor="w")

        target_row = tk.Frame(self.target_section_frame, bg=COLORS["card"])
        target_row.pack(fill="x", pady=(4, 0))

        self.target_entry = ttk.Entry(
            target_row, textvariable=self.target_size_value,
            font=FONT_BODY, width=8,
        )
        self.target_entry.pack(side="left")

        self.target_unit_combo = ttk.Combobox(
            target_row, textvariable=self.target_size_unit,
            values=["KB", "MB"], state="readonly",
            font=FONT_BODY, width=5,
        )
        self.target_unit_combo.pack(side="left", padx=(8, 0))

        tk.Label(target_row, text=self._t("autotune_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"], justify="left",
                 bg=COLORS["card"]).pack(side="left", padx=(8, 0))

        # Hide target section initially (manual mode default)
        self.target_section_frame.pack_forget()

        # ── Resize ──────────────────────────────────────────────────────────
        resize_frame = self._add_collapsible_section(OUT, "sec_resize")
        resize_frame.columnconfigure(1, weight=1)
        resize_frame.columnconfigure(3, weight=1)

        tk.Label(resize_frame, text=self._t("width"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=0, column=0, sticky="e", padx=(0, 4))
        w_entry = ttk.Entry(resize_frame, textvariable=self.max_width,
                            font=FONT_BODY, width=7)
        w_entry.grid(row=0, column=1, sticky="w")

        tk.Label(resize_frame, text=self._t("height"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=0, column=2, sticky="e", padx=(12, 4))
        h_entry = ttk.Entry(resize_frame, textvariable=self.max_height,
                            font=FONT_BODY, width=7)
        h_entry.grid(row=0, column=3, sticky="w")

        tk.Label(resize_frame, text=self._t("pixels_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))

        # Max pixels on the longest side (downscale only)
        tk.Label(resize_frame, text=self._t("max_pixels"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        px_entry = ttk.Entry(resize_frame, textvariable=self.max_pixels,
                             font=FONT_BODY, width=7)
        px_entry.grid(row=2, column=2, columnspan=2, sticky="w",
                      padx=(8, 0), pady=(8, 0))
        tk.Label(resize_frame, text=self._t("max_pixels_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(2, 0))

        # Scale percentage
        scale_frame = tk.Frame(resize_frame, bg=COLORS["card"])
        scale_frame.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(8, 0))

        tk.Label(scale_frame, text=self._t("scale"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).pack(side="left")

        scale_entry = ttk.Entry(scale_frame, textvariable=self.scale_percent,
                                font=FONT_BODY, width=7)
        scale_entry.pack(side="left", padx=(8, 0))

        # ── Output Location ─────────────────────────────────────────────────
        out_frame = self._add_collapsible_section(OUT, "sec_output")
        out_frame.columnconfigure(0, weight=1)

        out_entry = ttk.Entry(out_frame, textvariable=self.output_dir,
                              font=FONT_SMALL)
        out_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        browse_btn = FlatButton(
            out_frame, text=self._t("browse"), command=self._browse_output_dir,
            bg=COLORS["bg"], fg=COLORS["text"], hover_bg=COLORS["border"],
            font=FONT_SMALL, padx=10, pady=4, border_color=COLORS["border"],
        )
        browse_btn.grid(row=0, column=1)

        # Print size (blank = off)
        tk.Label(out_frame, text=self._t("print_size"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(out_frame, textvariable=self.print_size,
                  font=FONT_BODY, width=10).grid(
            row=1, column=1, sticky="w", padx=(8, 0), pady=(10, 0))
        tk.Label(out_frame, text=self._t("print_size_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))

        # ── Naming ──────────────────────────────────────────────────────────
        naming_frame = self._add_collapsible_section(OUT, "sec_naming")

        tk.Label(naming_frame, text=self._t("prefix"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=0, column=0, sticky="w")
        ttk.Entry(naming_frame, textvariable=self.prefix,
                  font=FONT_BODY, width=10).grid(
            row=0, column=1, sticky="ew", padx=(8, 0))

        tk.Label(naming_frame, text=self._t("suffix"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(naming_frame, textvariable=self.suffix,
                  font=FONT_BODY, width=10).grid(
            row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

        tk.Label(naming_frame, text=self._t("smart_rename"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"], justify="left").grid(
            row=2, column=0, sticky="w", pady=(12, 0))
        self.rename_entry = ttk.Entry(
            naming_frame, textvariable=self.rename_pattern,
            font=FONT_SMALL, width=20,
        )
        self.rename_entry.grid(
            row=2, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))
        tk.Label(naming_frame, text=self._t("rename_vars"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(2, 0), padx=(0, 8))

        naming_frame.columnconfigure(1, weight=1)

        # ── Folder Organization ─────────────────────────────────────────────
        folder_frame = self._add_collapsible_section(OUT, "sec_subfolder")
        folder_frame.columnconfigure(1, weight=1)

        tk.Label(folder_frame, text=self._t("template"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=0, column=0, sticky="w")

        # Preset list is localized; index maps to an internal value
        self._folder_preset_keys = [
            "preset_flat", "preset_date", "preset_camera",
            "preset_date_camera", "preset_custom",
        ]
        # Internal value per preset index; None = custom template
        self._folder_preset_values = ["", "date", "camera", "date-camera", None]

        self.folder_combo = ttk.Combobox(
            folder_frame, font=FONT_BODY, state="readonly",
            values=[self._t(k) for k in self._folder_preset_keys],
        )
        self.folder_combo.current(0)
        self.folder_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.folder_combo.bind("<<ComboboxSelected>>", self._on_folder_preset_change)

        tk.Label(folder_frame, text=self._t("custom"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=1, column=0, sticky="w", pady=(8, 0))

        self.folder_custom_entry = ttk.Entry(
            folder_frame, textvariable=self.folder_pattern,
            font=FONT_SMALL,
        )
        self.folder_custom_entry.grid(
            row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

        tk.Label(folder_frame, text=self._t("folder_vars"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(2, 0), padx=(0, 8))

        # ── Options ─────────────────────────────────────────────────────────
        opts_frame = self._add_collapsible_section(OPT, "sec_options")

        self._add_checkbox(opts_frame, self._t("preserve_exif"),
                           self.preserve_exif, row=0)
        self._add_checkbox(opts_frame, self._t("optimize"),
                           self.optimize, row=1)
        self._add_checkbox(opts_frame, self._t("progressive"),
                           self.progressive, row=2)
        self._add_checkbox(opts_frame, self._t("overwrite"),
                           self.overwrite, row=3)
        self._add_checkbox(opts_frame, self._t("auto_rotate"),
                           self.auto_rotate, row=4)
        self._add_checkbox(opts_frame, self._t("raw_half_size"),
                           self.raw_half_size, row=5)
        self._add_checkbox(opts_frame, self._t("raw_auto_bright"),
                           self.raw_auto_bright, row=6)
        self._add_checkbox(opts_frame, self._t("delete_original"),
                           self.remove_original, row=7)
        self._add_checkbox(opts_frame, self._t("strip_gps"),
                           self.strip_gps, row=8)
        self._add_checkbox(opts_frame, self._t("keep_mtime"),
                           self.keep_mtime, row=9)

        # Parallel workers
        tk.Label(opts_frame, text=self._t("jobs"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=10, column=0, sticky="w", pady=(10, 0))
        jobs_entry = ttk.Entry(opts_frame, textvariable=self.jobs,
                               font=FONT_BODY, width=5)
        jobs_entry.grid(row=10, column=1, sticky="w", padx=(8, 0), pady=(10, 0))

        # JPEG chroma subsampling (444 = full color, larger files)
        tk.Label(opts_frame, text=self._t("jpeg_subsampling"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=11, column=0, sticky="w", pady=(10, 0))
        sub_combo = ttk.Combobox(
            opts_frame, textvariable=self.jpeg_subsampling,
            values=["444", "422", "420"], state="readonly",
            font=FONT_BODY, width=5)
        sub_combo.grid(row=11, column=1, sticky="w", padx=(8, 0), pady=(10, 0))

        # RAW demosaic algorithm (amaze = highest quality, slowest)
        tk.Label(opts_frame, text=self._t("raw_demosaic"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=12, column=0, sticky="w", pady=(10, 0))
        dem_combo = ttk.Combobox(
            opts_frame, textvariable=self.raw_demosaic,
            values=["auto", "ahd", "vng", "ppg", "dcb", "dht", "amaze"],
            state="readonly", font=FONT_BODY, width=7)
        dem_combo.grid(row=12, column=1, sticky="w", padx=(8, 0), pady=(10, 0))

        # RAW output color space (wider gamuts untagged)
        tk.Label(opts_frame, text=self._t("raw_color_space"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=13, column=0, sticky="w", pady=(10, 0))
        cs_combo = ttk.Combobox(
            opts_frame, textvariable=self.raw_color_space,
            values=["sRGB", "AdobeRGB", "ProPhotoRGB"], state="readonly",
            font=FONT_BODY, width=10)
        cs_combo.grid(row=13, column=1, sticky="w", padx=(8, 0), pady=(10, 0))

        self._add_checkbox(opts_frame, self._t("raw_16bit"),
                           self.raw_16bit, row=14)

        # ── Cutout / background removal (v2.1.0) ─────────────────────────────
        cut_frame = self._add_collapsible_section(OPT, "sec_cutout")
        cut_frame.columnconfigure(1, weight=1)
        tk.Label(cut_frame, text=self._t("cutout_mode"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=0, column=0, sticky="w", pady=(4, 0))
        ttk.Combobox(cut_frame,
                     values=(self._t("cutout_off"), self._t("cutout_subject"),
                             self._t("cutout_person"), self._t("cutout_object"),
                             self._t("cutout_color")),
                     textvariable=self.cutout_mode, state="readonly",
                     width=12, font=FONT_SMALL).grid(
            row=0, column=1, sticky="w", padx=(8, 0), pady=(4, 0))
        # object mode: COCO class entry
        cut_label_frame = tk.Frame(cut_frame, bg=COLORS["card"])
        tk.Label(cut_label_frame, text=self._t("cutout_label"),
                 font=FONT_SMALL, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).pack(side="left", padx=(0, 6))
        ttk.Entry(cut_label_frame, textvariable=self.cutout_label,
                  font=FONT_BODY, width=14).pack(side="left")
        # color mode: R/G/B + tol + feather entries
        cut_color_frame = tk.Frame(cut_frame, bg=COLORS["card"])
        for i, (key, var) in enumerate((
                ("cutout_r", self.cutout_r), ("cutout_g", self.cutout_g),
                ("cutout_b", self.cutout_b))):
            tk.Label(cut_color_frame, text=self._t(key), font=FONT_SMALL,
                     fg=COLORS["text_secondary"], bg=COLORS["card"]).pack(
                side="left", padx=(0 if i == 0 else 8, 2))
            ttk.Entry(cut_color_frame, textvariable=var, width=3,
                      font=FONT_BODY).pack(side="left")
        for key, var in (("cutout_tol", self.cutout_tol),
                         ("cutout_feather", self.cutout_feather)):
            tk.Label(cut_color_frame, text=self._t(key), font=FONT_SMALL,
                     fg=COLORS["text_secondary"], bg=COLORS["card"]).pack(
                side="left", padx=(12, 2))
            ttk.Entry(cut_color_frame, textvariable=var, width=4,
                      font=FONT_BODY).pack(side="left")
        cut_label_frame.grid(row=1, column=0, columnspan=2, sticky="w",
                             pady=(4, 0))
        cut_color_frame.grid(row=1, column=0, columnspan=2, sticky="w",
                             pady=(4, 0))
        tk.Label(cut_frame, text=self._t("cutout_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        tk.Label(cut_frame, text=self._t("cutout_ai_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(2, 0))
        # dynamic visibility: object shows the label frame, color the rgb frame
        self._cutout_frames = {"object": cut_label_frame,
                               "color": cut_color_frame}
        self.cutout_mode.trace_add("write", self._on_cutout_mode_changed)
        self._on_cutout_mode_changed()

        # ── Watermark ────────────────────────────────────────────────────────
        wm_frame = self._add_collapsible_section(FX, "sec_watermark")
        wm_frame.columnconfigure(1, weight=1)

        tk.Label(wm_frame, text=self._t("wm_text"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=0, column=0, sticky="w")
        wm_text_entry = ttk.Entry(wm_frame, textvariable=self.watermark_text,
                                  font=FONT_BODY)
        wm_text_entry.grid(row=0, column=1, columnspan=2, sticky="ew",
                           padx=(8, 0))

        tk.Label(wm_frame, text=self._t("wm_image"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=1, column=0, sticky="w", pady=(8, 0))
        wm_image_entry = ttk.Entry(wm_frame, textvariable=self.watermark_image,
                                   font=FONT_SMALL)
        wm_image_entry.grid(row=1, column=1, sticky="ew", padx=(8, 0),
                            pady=(8, 0))
        wm_browse = FlatButton(
            wm_frame, self._t("browse"),
            lambda: self._browse_watermark_image(),
            COLORS["accent"], fg="white")
        wm_browse.grid(row=1, column=2, sticky="e", padx=(6, 0), pady=(8, 0))

        tk.Label(wm_frame, text=self._t("wm_position"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=2, column=0, sticky="w", pady=(8, 0))
        wm_pos_combo = ttk.Combobox(
            wm_frame, textvariable=self.watermark_position, state="readonly",
            font=FONT_SMALL, width=14,
            values=list(watermark.POSITIONS.keys()))
        wm_pos_combo.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        tk.Label(wm_frame, text=self._t("wm_opacity"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=3, column=0, sticky="w", pady=(8, 0))
        wm_opacity_scale = ttk.Scale(
            wm_frame, from_=0, to=100, variable=self.watermark_opacity,
            command=lambda v: wm_opacity_lbl.config(
                text=f"{int(float(v))}%"))
        wm_opacity_scale.grid(row=3, column=1, sticky="ew", padx=(8, 0),
                              pady=(8, 0))
        wm_opacity_lbl = tk.Label(wm_frame, text="50%", font=FONT_SMALL,
                                  fg=COLORS["text_secondary"],
                                  bg=COLORS["card"], width=4)
        wm_opacity_lbl.grid(row=3, column=2, sticky="e", pady=(8, 0))

        # ── Multi-size output ─────────────────────────────────────────────────
        sizes_frame = self._add_collapsible_section(OUT, "sec_sizes")
        sizes_frame.columnconfigure(0, weight=1)

        sizes_entry = ttk.Entry(sizes_frame, textvariable=self.output_sizes,
                                font=FONT_BODY)
        sizes_entry.grid(row=0, column=0, sticky="ew")
        tk.Label(sizes_frame, text=self._t("sizes_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=1, column=0, sticky="w", pady=(4, 0))

        # ── Adjust (tone & color) ────────────────────────────────────────────
        adj_frame = self._add_collapsible_section(ADJ, "sec_adjust")
        adj_frame.columnconfigure(1, weight=1)

        adj_specs = [
            ("brightness", self.brightness, 0.0, 2.0, 0.05, "{:.2f}"),
            ("contrast", self.contrast, 0.0, 2.0, 0.05, "{:.2f}"),
            ("saturation", self.saturation, 0.0, 2.0, 0.05, "{:.2f}"),
            ("gamma", self.gamma, 0.1, 3.0, 0.05, "{:.2f}"),
            ("sharpen", self.sharpen, 0.0, 3.0, 0.05, "{:.2f}"),
        ]
        for i, (key, var, lo, hi, step, fmt) in enumerate(adj_specs):
            tk.Label(adj_frame, text=self._t(key), font=FONT_SMALL,
                     fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
                row=i, column=0, sticky="w")
            val_lbl = tk.Label(adj_frame, text=fmt.format(var.get()),
                               font=FONT_SMALL, fg=COLORS["text_secondary"],
                               bg=COLORS["card"], width=5)
            val_lbl.grid(row=i, column=2, sticky="e")
            ttk.Scale(adj_frame, from_=lo, to=hi, variable=var,
                      command=lambda v, lbl=val_lbl, f=fmt: lbl.config(
                          text=f.format(float(v)))).grid(
                row=i, column=1, sticky="ew", padx=(8, 0))

        self._add_checkbox(adj_frame, self._t("grayscale"),
                           self.grayscale, row=5)
        self._add_checkbox(adj_frame, self._t("sepia"),
                           self.sepia, row=6)

        # Export sharpening (LR-style output-stage USM; 0 = off)
        tk.Label(adj_frame, text=self._t("export_sharpen"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=7, column=0, sticky="w", pady=(8, 0))
        es_val = tk.Label(adj_frame, text="0.00", font=FONT_SMALL,
                          fg=COLORS["text_secondary"], bg=COLORS["card"],
                          width=5)
        es_val.grid(row=7, column=2, sticky="e", pady=(8, 0))
        ttk.Scale(adj_frame, from_=0.0, to=2.0, variable=self.export_sharpen,
                  command=lambda v, lbl=es_val: lbl.config(
                      text=f"{float(v):.2f}")).grid(
            row=7, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

        # Highlight recovery (LR-style; 0 = off)
        tk.Label(adj_frame, text=self._t("highlight_recovery"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=8, column=0, sticky="w", pady=(8, 0))
        hr_val = tk.Label(adj_frame, text="0.00", font=FONT_SMALL,
                          fg=COLORS["text_secondary"], bg=COLORS["card"],
                          width=5)
        hr_val.grid(row=8, column=2, sticky="e", pady=(8, 0))
        ttk.Scale(adj_frame, from_=0.0, to=1.0, variable=self.highlight_recovery,
                  command=lambda v, lbl=hr_val: lbl.config(
                      text=f"{float(v):.2f}")).grid(
            row=8, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

        # ── Composition (crop / rotate / flip / pad) ─────────────────────────
        comp_frame = self._add_collapsible_section(ADJ, "sec_composition")
        comp_frame.columnconfigure(1, weight=1)

        comp_specs = [
            ("crop", self.crop, None),
            ("crop_ratio", self.crop_ratio, None),
            ("rotate", self.rotate, None),
            ("rotate_bg", self.rotate_bg, None),
            ("pad", self.pad_ratio, None),
            ("pad_bg", self.pad_bg, None),
        ]
        for i, (key, var, _) in enumerate(comp_specs):
            tk.Label(comp_frame, text=self._t(key), font=FONT_SMALL,
                     fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
                row=i, column=0, sticky="w")
            ttk.Entry(comp_frame, textvariable=var, font=FONT_BODY).grid(
                row=i, column=1, sticky="ew", padx=(8, 0))

        tk.Label(comp_frame, text=self._t("flip"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=6, column=0, sticky="w", pady=(8, 0))
        flip_combo = ttk.Combobox(
            comp_frame, textvariable=self.flip, state="readonly",
            font=FONT_SMALL, width=6, values=["", "h", "v"])
        flip_combo.grid(row=6, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        tk.Label(comp_frame, text=self._t("crop_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(4, 0))
        tk.Label(comp_frame, text=self._t("pad_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(2, 0))

        # ── Correction (exposure / LOG / denoise / straighten) ───────────────
        corr_frame = self._add_collapsible_section(ADJ, "sec_correction")
        corr_frame.columnconfigure(1, weight=1)

        # EV exposure slider (-2..+2 stops)
        tk.Label(corr_frame, text=self._t("ev"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=0, column=0, sticky="w")
        ev_lbl = tk.Label(corr_frame, text="{:+.2f}".format(self.ev.get()),
                          font=FONT_SMALL, fg=COLORS["text_secondary"],
                          bg=COLORS["card"], width=5)
        ev_lbl.grid(row=0, column=2, sticky="e")
        ttk.Scale(corr_frame, from_=-2.0, to=2.0, variable=self.ev,
                  command=lambda v, lbl=ev_lbl: lbl.config(
                      text="{:+.2f}".format(float(v)))).grid(
            row=0, column=1, sticky="ew", padx=(8, 0))
        tk.Label(corr_frame, text=self._t("ev_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))

        # Auto-exposure target (blank = off)
        tk.Label(corr_frame, text=self._t("auto_exposure"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=2, column=0, sticky="w")
        ttk.Entry(corr_frame, textvariable=self.auto_exposure,
                  font=FONT_BODY, width=8).grid(
            row=2, column=1, sticky="w", padx=(8, 0))
        tk.Label(corr_frame, text=self._t("auto_exposure_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(2, 0))

        # LOG recovery curve (blank = off)
        tk.Label(corr_frame, text=self._t("log_curve"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=4, column=0, sticky="w")
        log_combo = ttk.Combobox(
            corr_frame, textvariable=self.log_curve, state="readonly",
            font=FONT_SMALL, width=8,
            values=["", "SLOG3", "CLOG3", "LOGC3", "DLOG", "VLOG", "HLG"])
        log_combo.grid(row=4, column=1, sticky="w", padx=(8, 0))
        tk.Label(corr_frame, text=self._t("log_curve_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(2, 0))

        # Denoise strength (blank = off)
        tk.Label(corr_frame, text=self._t("denoise"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=6, column=0, sticky="w")
        ttk.Entry(corr_frame, textvariable=self.denoise,
                  font=FONT_BODY, width=8).grid(
            row=6, column=1, sticky="w", padx=(8, 0))
        tk.Label(corr_frame, text=self._t("denoise_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(2, 0))

        # LUT color grade (.cube file or preset name)
        tk.Label(corr_frame, text=self._t("lut"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=8, column=0, sticky="w")
        lut_entry = ttk.Entry(corr_frame, textvariable=self.lut_file,
                              font=FONT_SMALL)
        lut_entry.grid(row=8, column=1, sticky="ew", padx=(8, 0))
        FlatButton(corr_frame, text=self._t("browse"),
                   command=self._browse_lut,
                   bg=COLORS["bg"], fg=COLORS["text"],
                   hover_bg=COLORS["border"], font=FONT_SMALL,
                   padx=8, pady=2, border_color=COLORS["border"]).grid(
            row=8, column=2, sticky="e", padx=(4, 0))
        tk.Label(corr_frame, text=self._t("lut_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=9, column=0, columnspan=3, sticky="w", pady=(2, 0))

        # Auto-straighten + max angle
        self._add_checkbox(corr_frame, self._t("auto_straighten"),
                           self.auto_straighten, row=8)
        tk.Label(corr_frame, text=self._t("max_straighten_angle"),
                 font=FONT_SMALL, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=9, column=0, sticky="w")
        ttk.Entry(corr_frame, textvariable=self.max_straighten_angle,
                  font=FONT_BODY, width=8).grid(
            row=9, column=1, sticky="w", padx=(8, 0))

        # ── White balance / color / evaluation (row 10+) ─────────────────────
        # WB temperature (blank = off)
        tk.Label(corr_frame, text=self._t("wb_temp"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=10, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(corr_frame, textvariable=self.wb_temp,
                  font=FONT_BODY, width=8).grid(
            row=10, column=1, sticky="w", padx=(8, 0), pady=(10, 0))
        tk.Label(corr_frame, text=self._t("wb_temp_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=11, column=0, columnspan=3, sticky="w", pady=(2, 0))

        # WB reference image (blank = off)
        tk.Label(corr_frame, text=self._t("wb_reference"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=12, column=0, sticky="w")
        ref_entry = ttk.Entry(corr_frame, textvariable=self.wb_reference,
                              font=FONT_SMALL)
        ref_entry.grid(row=12, column=1, sticky="ew", padx=(8, 0))
        FlatButton(corr_frame, text=self._t("browse_ref"),
                   command=self._browse_wb_reference,
                   bg=COLORS["bg"], fg=COLORS["text"],
                   hover_bg=COLORS["border"], font=FONT_SMALL,
                   padx=8, pady=2, border_color=COLORS["border"]).grid(
            row=12, column=2, sticky="e", padx=(4, 0))
        tk.Label(corr_frame, text=self._t("wb_reference_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=13, column=0, columnspan=3, sticky="w", pady=(2, 0))

        # Checkboxes: auto levels / color / evaluation
        self._add_checkbox(corr_frame, self._t("auto_levels"),
                           self.auto_levels, row=14)
        self._add_checkbox(corr_frame, self._t("srgb"),
                           self.srgb, row=15)
        self._add_checkbox(corr_frame, self._t("flatten_cmyk"),
                           self.flatten_cmyk, row=16)
        self._add_checkbox(corr_frame, self._t("evaluate"),
                           self.evaluate, row=17)
        self._add_checkbox(corr_frame, self._t("blur_score"),
                           self.blur_score, row=18)
        self._add_checkbox(corr_frame, self._t("resume"),
                           self.resume, row=19)

        # ── LR-direction grading (v1.6.0) — blank = off ──────────────────────
        tk.Label(corr_frame, text=self._t("sec_grading"),
                 font=FONT_SECTION, fg=COLORS["text"],
                 bg=COLORS["card"]).grid(
            row=20, column=0, columnspan=3, sticky="w", pady=(14, 2))

        # entries for the scalar/compact specs; the three interactive
        # editors (curves / color-grading / hsl) get an "edit…" button
        _grade_widgets = [
            ("wb_tint", "wb_tint_hint"),
            ("levels", "levels_hint"),
            ("vibrance", "vibrance_hint"),
            ("clarity", "clarity_hint"),
            ("texture", "texture_hint"),
            ("dehaze", "dehaze_hint"),
            ("vignette", "vignette_hint"),
            ("grain", "grain_hint"),
        ]
        _grade_editors = [
            ("curves", "curves_hint", "edit_curves", "_open_curve_editor",
             "grade_curves_val"),
            ("color_grading", "color_grading_hint", "edit_wheels",
             "_open_color_wheel_dialog", "grade_wheels_val"),
            ("hsl", "hsl_hint", "edit_hsl", "_open_hsl_dialog",
             "grade_hsl_val"),
            ("point_color", "point_color_hint", "edit_point_color",
             "_open_point_color_dialog", "grade_point_color_val"),
            ("masks", "masks_hint", "edit_masks", "_dev_enter_mask_mode",
             "grade_masks_val"),
        ]
        for off, (var_key, hint_key) in enumerate(_grade_widgets):
            r = 21 + off * 2
            tk.Label(corr_frame, text=self._t(var_key), font=FONT_SMALL,
                     fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
                row=r, column=0, sticky="w")
            ttk.Entry(corr_frame, textvariable=getattr(self, var_key),
                      font=FONT_BODY, width=8).grid(
                row=r, column=1, sticky="w", padx=(8, 0))
            tk.Label(corr_frame, text=self._t(hint_key),
                     font=FONT_TINY, fg=COLORS["text_secondary"],
                     bg=COLORS["card"]).grid(
                row=r + 1, column=0, columnspan=3, sticky="w", pady=(0, 4))
        for off, (var_key, hint_key, btn_key, method, val_attr) in \
                enumerate(_grade_editors):
            r = 21 + (len(_grade_widgets) + off) * 2
            tk.Label(corr_frame, text=self._t(var_key), font=FONT_SMALL,
                     fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
                row=r, column=0, sticky="w")
            FlatButton(corr_frame, text=self._t(btn_key),
                       command=getattr(self, method),
                       bg=COLORS["bg"], fg=COLORS["text"],
                       hover_bg=COLORS["border"], font=FONT_SMALL,
                       padx=8, pady=2, border_color=COLORS["border"]).grid(
                row=r, column=1, sticky="w", padx=(8, 0))
            val_lbl = tk.Label(corr_frame, text="", font=FONT_TINY,
                               fg=COLORS["text_secondary"],
                               bg=COLORS["card"], anchor="w")
            val_lbl.grid(row=r, column=2, sticky="ew", padx=(4, 0))
            corr_frame.columnconfigure(2, weight=1)
            setattr(self, val_attr, val_lbl)
            tk.Label(corr_frame, text=self._t(hint_key),
                     font=FONT_TINY, fg=COLORS["text_secondary"],
                     bg=COLORS["card"]).grid(
                row=r + 1, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self._refresh_grade_value_labels()

        # ── Lens correction (v1.7.0) - manual params, blank = off ───────────
        lens_frame = self._add_collapsible_section(ADJ, "sec_lens",
                                                   default_open=False)
        lens_frame.columnconfigure(1, weight=1)
        _lens_fields = [
            ("lens_distort", "lens_distort_hint"),
            ("lens_vignette", "lens_vignette_hint"),
            ("lens_ca", "lens_ca_hint"),
        ]
        for off, (var_key, hint_key) in enumerate(_lens_fields):
            r = off * 2
            tk.Label(lens_frame, text=self._t(var_key), font=FONT_SMALL,
                     fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
                row=r, column=0, sticky="w")
            ttk.Entry(lens_frame, textvariable=getattr(self, var_key),
                      font=FONT_BODY, width=10).grid(
                row=r, column=1, sticky="w", padx=(8, 0))
            tk.Label(lens_frame, text=self._t(hint_key),
                     font=FONT_TINY, fg=COLORS["text_secondary"],
                     bg=COLORS["card"]).grid(
                row=r + 1, column=0, columnspan=3, sticky="w", pady=(0, 4))

        # Lens profile (user-maintained; see photo-s lens-profile)
        tk.Label(lens_frame, text=self._t("lens_profile"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=6, column=0, sticky="w", pady=(8, 0))
        try:
            from ...lensprofile import lens_profile_names
            _lens_profiles = [""] + lens_profile_names()
        except Exception:
            _lens_profiles = [""]
        lp_combo = ttk.Combobox(
            lens_frame, textvariable=self.lens_profile,
            values=_lens_profiles, state="readonly", font=FONT_BODY, width=18)
        lp_combo.grid(row=6, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        # ── Metadata section ──────────────────────────────────────────────────
        meta_frame = self._add_collapsible_section(META, "sec_metadata")
        meta_frame.columnconfigure(1, weight=1)

        # EXIF date shift (blank = off)
        tk.Label(meta_frame, text=self._t("date_shift"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=0, column=0, sticky="w")
        ttk.Entry(meta_frame, textvariable=self.date_shift,
                  font=FONT_BODY, width=8).grid(
            row=0, column=1, sticky="w", padx=(8, 0))
        tk.Label(meta_frame, text=self._t("date_shift_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))

        # GPX track (blank = off)
        tk.Label(meta_frame, text=self._t("gpx_trace"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(meta_frame, textvariable=self.gpx_trace,
                  font=FONT_SMALL).grid(
            row=2, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        FlatButton(meta_frame, text=self._t("browse_gpx"),
                   command=self._browse_gpx,
                   bg=COLORS["bg"], fg=COLORS["text"],
                   hover_bg=COLORS["border"], font=FONT_SMALL,
                   padx=8, pady=2, border_color=COLORS["border"]).grid(
            row=2, column=2, sticky="e", padx=(4, 0), pady=(8, 0))
        tk.Label(meta_frame, text=self._t("gpx_trace_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(2, 0))

        self._add_checkbox(meta_frame, self._t("sync_date"),
                           self.sync_date, row=4)
        self._add_checkbox(meta_frame, self._t("scrub"),
                           self.scrub, row=5)

        # Face blur (privacy mask; needs opencv via [enhance] extra)
        tk.Label(meta_frame, text=self._t("blur_faces"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=6, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(meta_frame,
                     values=(self._t("blur_faces_off"), self._t("blur_faces_blur"),
                             self._t("blur_faces_pixelate")),
                     textvariable=self.blur_faces, state="readonly",
                     width=12, font=FONT_SMALL).grid(
            row=6, column=1, sticky="w", padx=(8, 0), pady=(8, 0))
        tk.Label(meta_frame, text=self._t("blur_faces_margin_lbl"),
                 font=FONT_SMALL, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=6, column=2, sticky="w", padx=(12, 0), pady=(8, 0))
        ttk.Entry(meta_frame, textvariable=self.blur_faces_margin,
                  font=FONT_BODY, width=4).grid(
            row=6, column=3, sticky="w", padx=(4, 0), pady=(8, 0))
        tk.Label(meta_frame, text=self._t("blur_faces_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=7, column=0, columnspan=4, sticky="w", pady=(2, 0))
