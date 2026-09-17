"""photo_s/gui/panels/mask.py — 蒙版编辑器（v2.5 内嵌 Develop）+ 点颜色对话框 + per-photo 蒙版通道。

v2.6 结构项第二批：从 app.py 平移（方法体逐字节保留，
仅函数级相对导入加深一层）。Mixin 无独立状态，全部经 ``self`` 与
PhotoSApp 共享。
"""

import tkinter as tk
from tkinter import messagebox, ttk

from ..theme import (COLORS, FONT_BODY, FONT_SECTION, FONT_SMALL,
                     FONT_TINY)
from ..widgets import FlatButton, _mask_spec_string, _open_image_safe


class MaskPanelMixin:
    """蒙版编辑器（v2.5 内嵌 Develop）+ 点颜色对话框 + per-photo 蒙版通道。"""

    def _open_point_color_dialog(self):
        """Form editor for the point_color compact spec (list + sliders)."""
        from ...grade import _parse_point_color
        if self._dlg_cooldown_active():
            return
        win = tk.Toplevel(self.root)
        win.title(self._t("dlt_point_color"))
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)
        win.geometry("820x560")

        try:
            targets = list(_parse_point_color(self.point_color.get()))
        except ValueError:
            targets = []

        body = tk.Frame(win, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=12, pady=12)

        lst = tk.Listbox(body, width=24, height=8, font=FONT_SMALL,
                         exportselection=False, bg=COLORS["card"],
                         fg=COLORS["text"], relief="flat",
                         highlightthickness=1,
                         highlightbackground=COLORS["border"])
        lst.grid(row=0, column=0, rowspan=9, sticky="ns", padx=(0, 12))

        editor = tk.Frame(body, bg=COLORS["bg"])
        editor.grid(row=0, column=1, sticky="n")

        pc_r = tk.StringVar(value="200")
        pc_g = tk.StringVar(value="120")
        pc_b = tk.StringVar(value="80")
        pc_hue = tk.DoubleVar(value=0.0)
        pc_sat = tk.DoubleVar(value=0.0)
        pc_lum = tk.DoubleVar(value=0.0)
        pc_range = tk.DoubleVar(value=0.15)
        swatch = tk.Canvas(editor, width=44, height=20,
                           bg=COLORS["card"], highlightthickness=0)

        def _sync_swatch(*_):
            try:
                rgb = (max(0, min(255, int(pc_r.get()))),
                       max(0, min(255, int(pc_g.get()))),
                       max(0, min(255, int(pc_b.get()))))
            except ValueError:
                return
            swatch.config(bg="#%02x%02x%02x" % rgb)

        tk.Label(editor, text=self._t("pc_sample"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).grid(
            row=0, column=0, columnspan=2, sticky="w")
        rgb_row = tk.Frame(editor, bg=COLORS["bg"])
        rgb_row.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 4))
        for i, var in enumerate((pc_r, pc_g, pc_b)):
            ttk.Entry(rgb_row, textvariable=var, font=FONT_BODY,
                      width=5).grid(row=0, column=i, padx=(0, 4))
            var.trace_add("write", _sync_swatch)
        swatch.grid(row=0, column=3, padx=(8, 0), rowspan=2)

        _sliders = [
            ("pc_hue", pc_hue, -180, 180, 1),
            ("pc_sat", pc_sat, -100, 100, 1),
            ("pc_lum", pc_lum, -100, 100, 1),
            ("pc_range", pc_range, 2, 100, 1),
        ]
        for off, (key, var, lo, hi, res) in enumerate(_sliders):
            tk.Label(editor, text=self._t(key), font=FONT_SMALL,
                     fg=COLORS["text_secondary"], bg=COLORS["bg"]).grid(
                row=2 + off * 2, column=0, sticky="w")
            ttk.Scale(editor, from_=lo, to=hi, variable=var).grid(
                row=2 + off * 2, column=1, sticky="ew", padx=(8, 0))
        editor.columnconfigure(1, weight=1)

        def _refresh_list():
            lst.delete(0, tk.END)
            for r, g, b, h, s, l, rng in targets:
                lst.insert(tk.END, f"{r},{g},{b}  h{h:+.0f} s{s:+.2f} "
                                   f"l{l:+.2f} r{rng:.2f}")

        def _load_selected(_evt=None):
            sel = lst.curselection()
            if not sel:
                return
            r, g, b, h, s, l, rng = targets[sel[0]]
            pc_r.set(str(r)); pc_g.set(str(g)); pc_b.set(str(b))
            pc_hue.set(float(h)); pc_sat.set(float(s)); pc_lum.set(float(l))
            pc_range.set(float(rng * 100))

        def _read_fields():
            def _ch(v):
                try:
                    return max(0, min(255, int(float(v))))
                except (TypeError, ValueError):
                    return 0  # 非数字输入不崩 Tk 回调（_sync_swatch 同款防御）
            return (_ch(pc_r.get()), _ch(pc_g.get()), _ch(pc_b.get()),
                    pc_hue.get(), pc_sat.get() / 100.0,
                    pc_lum.get() / 100.0, pc_range.get() / 100.0)

        def _add():
            targets.append(_read_fields())
            _refresh_list()
            lst.selection_clear(0, tk.END)
            lst.selection_set(tk.END)

        def _update():
            sel = lst.curselection()
            if sel:
                targets[sel[0]] = _read_fields()
                _refresh_list()
                lst.selection_set(sel[0])

        def _delete():
            sel = lst.curselection()
            if sel:
                del targets[sel[0]]
                _refresh_list()

        lst.bind("<<ListboxSelect>>", _load_selected)
        _refresh_list()

        btns = tk.Frame(editor, bg=COLORS["bg"])
        btns.grid(row=10, column=0, columnspan=2, sticky="w", pady=(10, 0))
        for text, cmd in ((self._t("pc_add"), _add),
                          (self._t("pc_update"), _update),
                          (self._t("pc_delete"), _delete)):
            FlatButton(btns, text=text, command=cmd,
                       bg=COLORS["bg"], fg=COLORS["text"],
                       hover_bg=COLORS["border"], font=FONT_SMALL,
                       padx=8, pady=2, border_color=COLORS["border"]).pack(
                side="left", padx=(0, 6))

        # photo reference strip: click the photo to sample its color
        def _on_pick(rgb):
            pc_r.set(str(rgb[0]))
            pc_g.set(str(rgb[1]))
            pc_b.set(str(rgb[2]))
            _sync_swatch()

        def _pc_render(base_img, _path):
            """Render current point-color targets onto the preview."""
            from ...grade import apply_point_color
            if not targets:
                return base_img
            return apply_point_color(base_img, list(targets))

        ref = self._add_photo_reference(win, on_pick=_on_pick, max_w=300,
                                        max_h=240,
                                        render_fn=_pc_render)
        ref["frame"].pack(side="left", fill="both", expand=True,
                          padx=(12, 0), pady=(0, 12))
        # live re-render when a target is added/updated/deleted
        _orig_add, _orig_update, _orig_delete = _add, _update, _delete

        def _add_refresh():
            _orig_add()
            ref["refresh"]()

        def _update_refresh():
            _orig_update()
            ref["refresh"]()

        def _delete_refresh():
            _orig_delete()
            ref["refresh"]()

        _add, _update, _delete = _add_refresh, _update_refresh, \
            _delete_refresh

        bottom = tk.Frame(win, bg=COLORS["bg"])
        bottom.pack(fill="x", padx=12, pady=(0, 12))
        FlatButton(bottom, text=self._t("ok"),
                   command=lambda: self._point_color_ok(win, targets),
                   bg=COLORS["bg"], fg=COLORS["text"],
                   hover_bg=COLORS["border"], font=FONT_SMALL,
                   padx=10, pady=3, border_color=COLORS["border"]).pack(
            side="right")
        FlatButton(bottom, text=self._t("cancel"), command=win.destroy,
                   bg=COLORS["bg"], fg=COLORS["text"],
                   hover_bg=COLORS["border"], font=FONT_SMALL,
                   padx=10, pady=3, border_color=COLORS["border"]).pack(
            side="right", padx=(0, 8))
        _sync_swatch()

    def _open_mask_dialog(self):
        """Form editor for masks + mask_adjust, with red-overlay preview."""
        from ...mask import parse_masks, parse_mask_adjust, render_mask
        if self._dlg_cooldown_active():
            return
        win = tk.Toplevel(self.root)
        win.title(self._t("dlt_masks"))
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)

        try:
            specs = [(s.name, s.kind, list(s.params), s.feather, s.invert)
                     for s in parse_masks(self.masks.get())]
        except Exception:
            specs = []
        try:
            adjusts = {k: dict(v) for k, v in
                       parse_mask_adjust(self.mask_adjust.get()).items()}
        except Exception:
            adjusts = {}

        body = tk.Frame(win, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=12, pady=12)

        lst = tk.Listbox(body, width=18, height=6, font=FONT_SMALL,
                         exportselection=False, bg=COLORS["card"],
                         fg=COLORS["text"], relief="flat",
                         highlightthickness=1,
                         highlightbackground=COLORS["border"])
        lst.grid(row=0, column=0, sticky="nw", padx=(0, 12))

        editor = tk.Frame(body, bg=COLORS["bg"])
        editor.grid(row=0, column=1, sticky="nw")
        editor.columnconfigure(1, weight=1)

        m_name = tk.StringVar(value="mask1")
        m_type = tk.StringVar(value="linear")
        m_params = [tk.StringVar(value=v) for v in
                    ("0.5", "0", "0.5", "1")]
        m_feather = tk.DoubleVar(value=0.0)
        m_invert = tk.BooleanVar(value=False)
        # per-mask adjustment sliders (value 0 = untouched)
        adj_vars = {key: tk.DoubleVar(value=0.0) for key in
                    ("exposure", "brightness", "contrast", "saturation",
                     "vibrance", "clarity", "texture", "sharpen",
                     "temp", "tint", "blur")}
        _current = {"name": None}

        tk.Label(editor, text=self._t("mask_name"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).grid(
            row=0, column=0, sticky="w")
        ttk.Entry(editor, textvariable=m_name, font=FONT_BODY,
                  width=10).grid(row=0, column=1, sticky="w", padx=(8, 0))
        tk.Label(editor, text=self._t("mask_type"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).grid(
            row=1, column=0, sticky="w")
        type_box = ttk.Combobox(editor, textvariable=m_type, width=12,
                                state="readonly", values=(
                                    self._t("mask_linear"),
                                    self._t("mask_radial"),
                                    self._t("mask_color"),
                                    self._t("mask_brush")))
        type_box.grid(row=1, column=1, sticky="w", padx=(8, 0))

        param_lbls = [tk.Label(editor, text="", font=FONT_SMALL,
                               fg=COLORS["text_secondary"],
                               bg=COLORS["bg"]) for _ in range(4)]
        param_widgets = []
        for i in range(4):
            param_lbls[i].grid(row=2 + i, column=0, sticky="w")
            e = ttk.Entry(editor, textvariable=m_params[i], font=FONT_BODY,
                          width=8)
            e.grid(row=2 + i, column=1, sticky="w", padx=(8, 0))
            param_widgets.append(e)

        _PARAM_LABELS = {
            "linear": ("x0", "y0", "x1", "y1"),
            "radial": ("cx", "cy", "rx", "ry"),
            "color": ("r", "g", "b", "tol"),
        }

        # ── brush: draw on a small canvas, dots stored as (x, y, r) ──
        m_brush_points = []  # list of (x_rel, y_rel, r_rel)
        _brush_r = tk.DoubleVar(value=0.06)  # radius as fraction of short side
        _brush_canvas = None

        def _type_key():
            for key, label in (("linear", "mask_linear"),
                               ("radial", "mask_radial"),
                               ("color", "mask_color"),
                               ("brush", "mask_brush")):
                if m_type.get() == self._t(label):
                    return key
            return "linear"

        def _sync_type(*_):
            key = _type_key()
            if key == "brush":
                for w in param_widgets + param_lbls:
                    w.grid_remove()
                _brush_canvas.grid()
                return
            for w in param_widgets + param_lbls:
                w.grid()
            _brush_canvas.grid_remove()
            for i, lbl in enumerate(_PARAM_LABELS[key]):
                param_lbls[i].config(text=lbl)

        def _brush_paint(evt):
            """Collect a dot at the canvas position (relative 0-1 coords)."""
            cw = max(1, _brush_canvas.winfo_width())
            ch = max(1, _brush_canvas.winfo_height())
            x, y = evt.x / cw, evt.y / ch
            x, y = max(0.0, min(1.0, x)), max(0.0, min(1.0, y))
            r = max(0.005, min(0.5, _brush_r.get()))
            m_brush_points.append((round(x, 4), round(y, 4), r))
            rad = max(2, r * min(cw, ch))
            _brush_canvas.create_oval(evt.x - rad, evt.y - rad,
                                      evt.x + rad, evt.y + rad,
                                      fill="#ff4444", outline="")

        def _brush_clear():
            m_brush_points.clear()
            _brush_canvas.delete("all")

        _brush_canvas = tk.Canvas(editor, width=180, height=120,
                                  bg=COLORS["card"], highlightthickness=1,
                                  highlightbackground=COLORS["border"])
        _brush_canvas.grid(row=2, column=0, columnspan=2, sticky="w")
        _brush_canvas.bind("<B1-Motion>", _brush_paint)
        _brush_canvas.bind("<Button-1>", _brush_paint)
        tk.Label(editor, text=self._t("mask_brush_size"), font=FONT_TINY,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).grid(
            row=3, column=0, sticky="w")
        ttk.Scale(editor, from_=0.01, to=0.3, variable=_brush_r).grid(
            row=3, column=1, sticky="ew", padx=(8, 0))
        FlatButton(editor, text=self._t("mask_brush_clear"),
                   command=_brush_clear,
                   bg=COLORS["bg"], fg=COLORS["text"],
                   hover_bg=COLORS["border"], font=FONT_SMALL,
                   padx=6, pady=1, border_color=COLORS["border"]).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))

        type_box.bind("<<ComboboxSelected>>", _sync_type)
        _sync_type()

        tk.Label(editor, text=self._t("mask_feather"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).grid(
            row=6, column=0, sticky="w")
        ttk.Scale(editor, from_=0, to=100, variable=m_feather).grid(
            row=6, column=1, sticky="ew", padx=(8, 0))
        ttk.Checkbutton(editor, text=self._t("mask_invert"),
                        variable=m_invert).grid(
            row=7, column=0, columnspan=2, sticky="w")

        # adjustment sliders, two per row
        tk.Label(editor, text=self._t("mask_adjust_sec"), font=FONT_SMALL,
                 fg=COLORS["text"], bg=COLORS["bg"]).grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(8, 2))
        _ADJ_META = (
            ("exposure", -3, 3), ("brightness", -1, 1), ("contrast", -1, 1),
            ("saturation", -1, 1), ("vibrance", -1, 1), ("clarity", -1, 1),
            ("texture", -1, 1), ("sharpen", -1, 1), ("temp", 0, 12000),
            ("tint", -100, 100), ("blur", 0, 50),
        )
        for i, (key, lo, hi) in enumerate(_ADJ_META):
            r, c = 9 + i // 2, (i % 2) * 2
            tk.Label(editor, text=self._t("adj_" + key), font=FONT_TINY,
                     fg=COLORS["text_secondary"], bg=COLORS["bg"]).grid(
                row=r, column=c, sticky="w")
            ttk.Scale(editor, from_=lo, to=hi,
                      variable=adj_vars[key]).grid(
                row=r, column=c + 1, sticky="ew", padx=(6, 10))

        # ── preview: red overlay of the current form spec on the first
        # checked file (geometric masks also work on a neutral canvas)
        preview = tk.Label(body, text=self._t("mask_no_preview"),
                           font=FONT_SMALL, fg=COLORS["text_secondary"],
                           bg=COLORS["card"], width=44, height=14)
        preview.grid(row=1, column=0, columnspan=2, sticky="w",
                     pady=(10, 0))
        _photo = {"img": None}  # keep a ref so ImageTk isn't GC'd

        def _refresh_preview():
            from PIL import Image as PILImage, ImageTk
            files = self._checked_files()
            base = None
            if files:
                try:
                    base = PILImage.open(files[0]).convert("RGB")
                    base.thumbnail((360, 270), PILImage.LANCZOS)
                except Exception:
                    base = None
            if base is None:
                base = PILImage.new("RGB", (360, 240), (60, 60, 60))
            try:
                key = _type_key()
                if key == "brush":
                    if not m_brush_points:
                        raise ValueError("no dots")
                    from ...mask import MaskSpec
                    spec = MaskSpec("brush", tuple(m_brush_points),
                                    feather=0.0, invert=m_invert.get())
                else:
                    vals = []
                    for var in m_params:
                        v = float(var.get())
                        vals.append(v)
                    params = (int(round(vals[0])), int(round(vals[1])),
                              int(round(vals[2])),
                              max(0.02, vals[3] if len(vals) > 3 else 0.15)) \
                        if key == "color" else tuple(vals[:4])
                    from ...mask import MaskSpec
                    spec = MaskSpec(key, params,
                                    feather=m_feather.get() / 100.0,
                                    invert=m_invert.get())
                m = render_mask(spec, base.width, base.height, img=base)
                overlay = PILImage.new("RGB", base.size, (255, 40, 40))
                out = PILImage.blend(base, overlay, 0.45)
                mask_img = PILImage.fromarray(
                    (m * 255).astype("uint8"), "L").convert("L")
                out = PILImage.composite(out, base, mask_img)
                _photo["img"] = ImageTk.PhotoImage(out, master=preview)
                preview.config(image=_photo["img"], text="", width=360,
                               height=270)
                preview.image = _photo["img"]
            except Exception:
                preview.config(image="", text=self._t("mask_no_preview"))

        FlatButton(editor, text=self._t("mask_refresh"),
                   command=_refresh_preview,
                   bg=COLORS["bg"], fg=COLORS["text"],
                   hover_bg=COLORS["border"], font=FONT_SMALL,
                   padx=8, pady=2, border_color=COLORS["border"]).grid(
            row=15, column=0, columnspan=2, sticky="w", pady=(8, 0))

        def _refresh_list():
            lst.delete(0, tk.END)
            for name, kind, params, feather, invert in specs:
                lst.insert(tk.END, f"{name}  [{kind}]")

        def _read_form():
            key = _type_key()
            if key == "brush":
                if not m_brush_points:
                    raise ValueError("no brush dots")
                return (m_name.get().strip() or f"mask{len(specs) + 1}",
                        "brush", list(m_brush_points), 0.0, m_invert.get(),
                        {})
            vals = [float(v.get()) for v in m_params]
            if key == "color":
                params = (int(round(max(0, min(255, vals[0])))),
                          int(round(max(0, min(255, vals[1])))),
                          int(round(max(0, min(255, vals[2])))),
                          max(0.02, min(1.0, vals[3] if vals[3] else 0.15)))
            elif key == "radial":
                params = (max(0.0, min(1.0, vals[0])),
                          max(0.0, min(1.0, vals[1])),
                          max(0.01, vals[2]), max(0.01, vals[3]))
            else:
                params = tuple(max(0.0, min(1.0, v)) for v in vals[:4])
            adjust = {}
            for k, var in adj_vars.items():
                v = round(var.get(), 3)
                if v != 0.0:
                    adjust[k] = v
            return (m_name.get().strip() or f"mask{len(specs) + 1}", key,
                    list(params), m_feather.get() / 100.0, m_invert.get(),
                    adjust)

        def _load_selected(_evt=None):
            sel = lst.curselection()
            if not sel:
                return
            name, kind, params, feather, invert = specs[sel[0]]
            _current["name"] = name
            m_name.set(name)
            m_type.set(self._t({"linear": "mask_linear",
                                "radial": "mask_radial",
                                "color": "mask_color",
                                "brush": "mask_brush"}[kind]))
            _sync_type()
            if kind == "brush":
                m_brush_points[:] = [tuple(p) for p in params]
                _brush_canvas.delete("all")
                for x, y, r in m_brush_points:
                    cw = max(1, _brush_canvas.winfo_width())
                    ch = max(1, _brush_canvas.winfo_height())
                    rad = max(2, r * min(cw, ch))
                    _brush_canvas.create_oval(x * cw - rad, y * ch - rad,
                                              x * cw + rad, y * ch + rad,
                                              fill="#ff4444", outline="")
                return
            for i in range(4):
                m_params[i].set(str(params[i]) if i < len(params) else "0")
            m_feather.set(feather * 100)
            m_invert.set(invert)
            for k, var in adj_vars.items():
                var.set(adjusts.get(name, {}).get(k, 0.0))

        def _add():
            try:
                name, key, params, feather, invert, adjust = _read_form()
            except ValueError:
                return
            specs.append((name, key, params, feather, invert))
            if adjust:
                adjusts[name] = adjust
            _refresh_list()
            lst.selection_clear(0, tk.END)
            lst.selection_set(tk.END)

        def _update():
            sel = lst.curselection()
            if not sel:
                return
            try:
                old = specs[sel[0]][0]
                name, key, params, feather, invert, adjust = _read_form()
            except ValueError:
                return
            specs[sel[0]] = (name, key, params, feather, invert)
            if old in adjusts:
                del adjusts[old]
            if adjust:
                adjusts[name] = adjust
            _refresh_list()
            lst.selection_set(sel[0])

        def _delete():
            sel = lst.curselection()
            if sel:
                name = specs[sel[0]][0]
                del specs[sel[0]]
                adjusts.pop(name, None)
                _refresh_list()

        lst.bind("<<ListboxSelect>>", _load_selected)
        _refresh_list()

        btns = tk.Frame(body, bg=COLORS["bg"])
        btns.grid(row=0, column=2, sticky="nw", padx=(12, 0))
        for text, cmd in ((self._t("pc_add"), _add),
                          (self._t("pc_update"), _update),
                          (self._t("pc_delete"), _delete)):
            FlatButton(btns, text=text, command=cmd,
                       bg=COLORS["bg"], fg=COLORS["text"],
                       hover_bg=COLORS["border"], font=FONT_SMALL,
                       padx=8, pady=2, border_color=COLORS["border"]).pack(
                fill="x", pady=(0, 6))

        bottom = tk.Frame(win, bg=COLORS["bg"])
        bottom.pack(fill="x", padx=12, pady=(0, 12))
        FlatButton(bottom, text=self._t("ok"),
                   command=lambda: self._masks_ok(win, specs, adjusts),
                   bg=COLORS["bg"], fg=COLORS["text"],
                   hover_bg=COLORS["border"], font=FONT_SMALL,
                   padx=10, pady=3, border_color=COLORS["border"]).pack(
            side="right")
        FlatButton(bottom, text=self._t("cancel"), command=win.destroy,
                   bg=COLORS["bg"], fg=COLORS["text"],
                   hover_bg=COLORS["border"], font=FONT_SMALL,
                   padx=10, pady=3, border_color=COLORS["border"]).pack(
            side="right", padx=(0, 8))

    def _masks_ok(self, win, specs, adjusts):
        def _n(v):
            if isinstance(v, str):
                # v1.8 字符串型局部调整（curves={...}/hsl={...}/...）——
                # 原样透传；float() 会崩（弹窗 OK 路径的潜伏 bug，旧测试
                # 只开窗不点 OK 从未触发）
                return v
            v = round(float(v), 4)
            return str(int(v)) if v == int(v) else str(v)
        mask_segs = [_mask_spec_string(*s) for s in specs]
        adj_segs = []
        for name, adjust in adjusts.items():
            if name not in {s[0] for s in specs}:
                continue
            adj_segs.append(name + ":" + ",".join(
                f"{k}={_n(v)}" for k, v in adjust.items()))
        self.masks.set(";".join(mask_segs))
        self.mask_adjust.set(";".join(adj_segs))
        self._refresh_grade_value_labels()
        if win is not None:
            win.destroy()

    def _dev_enter_mask_mode(self):
        """v2.5: 蒙版画布从弹窗升格进 Develop（原 _open_mask_workflow）。

        切到 Develop 并把预览/侧栏换成内嵌蒙版编辑器（作用域 = 勾选照片，
        起始 = 当前 Develop 选择）。编辑即所见：退出时写入 _photo_masks，
        预览/导出队列立即反映（与调色覆盖层同一通道）。
        """
        if self._active_module != "develop":
            self._show_module("develop")
        files = self._checked_files()
        if not files:
            messagebox.showwarning(self._t("dlg_no_files_title"),
                                   self._t("mask_no_check"))
            return
        self._dev_mask_mode = True
        # 每次进入重建：_photo_masks/全局 masks 是事实源，撤销栈按会话计
        if self._dev_mask_frame is not None:
            self._dev_mask_frame.destroy()
        self._dev_mask_frame = tk.Frame(self._dev_mask_host,
                                        bg=COLORS["bg"])
        start = self._dev_selected if self._dev_selected in files else None
        self._dev_mask_ctl = self._build_mask_workflow(
            self._dev_mask_frame, files, hosted=True, start_path=start)
        self._dev_mask_frame.pack(fill="both", expand=True)
        self._dev_mask_apply_layout()

    def _dev_exit_mask_mode(self):
        """退出蒙版模式；内嵌编辑视为即改即生效（退出时应用一次）。"""
        ctl = self._dev_mask_ctl
        self._dev_mask_mode = False
        self._dev_mask_ctl = None
        if ctl is not None:
            ctl["apply"]()
        if self._dev_mask_frame is not None:
            self._dev_mask_frame.destroy()
            self._dev_mask_frame = None
        self._dev_mask_apply_layout()
        # 蒙版变化 → 预览与导出队列即时反映（sig 变化由 dev tick 稳定后
        # 触发；这里直接以当前 sig 立即重渲一次，不等防抖）
        if self._dev_selected:
            self._dev_render(self._dev_current_sig())
        self._refresh_export_queue()

    def _dev_mask_apply_layout(self):
        """Develop 主行切换：调色（预览+侧栏）↔ 蒙版编辑器。v2.6 结构项：
        主行是 ttk.PanedWindow——预览/蒙版在左窗格内 pack 切换；侧栏 pane
        forget/add（sash 位置记住并在退出蒙版时还原；此 Tk 构建的 pane
        无 -hide 选项）。"""
        mask_on = getattr(self, "_dev_mask_mode", False)
        # panes() 在不同 tkinter 版本里返回 widget 或路径串——统一按 str 比
        try:
            names = [str(p) for p in self._dev_main.panes()]
        except (AttributeError, tk.TclError):
            names = []
        managed = str(self._dev_side) in names
        if mask_on:
            self._dev_viewer_card.pack_forget()
            self._dev_mask_host.pack(fill="both", expand=True)
            try:
                if managed:
                    self._dev_side_sash = self._dev_main.sashpos(0)
                    self._dev_main.forget(self._dev_side)
            except (AttributeError, tk.TclError):
                pass  # layout not built / torn down mid-flight
        else:
            self._dev_mask_host.pack_forget()
            self._dev_viewer_card.pack(side="left", fill="both",
                                       expand=True)
            try:
                if not managed:
                    self._dev_main.add(self._dev_side, weight=0)
                    sash = getattr(self, "_dev_side_sash", None)
                    if sash:
                        # add 后布局未重算，直接设会被夹到错误位置——重试至生效
                        self._dev_main.after_idle(
                            lambda v=sash: self._reapply_pane_sash(
                                self._dev_main, v))
            except (AttributeError, tk.TclError):
                pass

    def _dev_mask_key_page(self, event):
        """←/→ 在蒙版模式翻页（输入框聚焦/非激活时不拦截）。"""
        if not getattr(self, "_dev_mask_mode", False) \
                or not self._dev_mask_ctl:
            return
        if self._focus_in_text_widget():
            return
        if event.keysym == "Left":
            self._dev_mask_ctl["page_prev"]()
        else:
            self._dev_mask_ctl["page_next"]()
        return "break"

    def _build_mask_workflow(self, host, files, *, hosted=False,
                             start_path=None):
        """Canvas mask editor, Lightroom-style — 弹窗/Develop 共用构建器。

        Big image + per-photo masks (each photo keeps its own spec list),
        brush/linear/radial/color/AI tools painted on the canvas with a
        translucent colored overlay, prev/next paging across checked files,
        multiple masks stacked with per-mask visibility and color.

        Per-photo state lives in ``self._photo_masks`` (path -> dict of
        masks/mask_adjust strings) and is injected into batch processing
        via the engine's ``per_file_options`` hook.

        ``hosted=True`` 时由 Develop 内嵌（host = 模块内 frame，退出经
        ``self._dev_exit_mask_mode`` 应用）；否则 host 为独立 Toplevel
        （测试/诊断路径）。返回控制器 ``{apply, undo, page_prev,
        page_next}``。
        """
        from ...mask import (MaskError, MaskSpec, parse_masks,
                           parse_mask_adjust, render_mask)

        # ── per-photo state ──────────────────────────────────────────────
        # photo[path] = {"specs": [(name, kind, params, feather, invert)],
        #                "adjusts": {name: {key: val}},
        #                "visible": {name: bool}}
        photo = {}
        bad_masks_warned = [False]
        for f in files:
            pm = (self._photo_masks or {}).get(f)
            masks_s = (pm or {}).get("masks", self.masks.get())
            adj_s = (pm or {}).get("mask_adjust", self.mask_adjust.get())
            try:
                specs = [(s.name, s.kind, list(s.params), s.feather,
                          s.invert) for s in parse_masks(masks_s)]
            except MaskError:
                # 逐段容错：坏段丢弃、合法段保留（整串清空会让 9 个
                # 合法段 + 1 个笔误段全部消失，OK 后整批蒙版被覆盖）
                specs = []
                for seg in masks_s.split(";"):
                    seg = seg.strip()
                    if not seg:
                        continue
                    try:
                        specs.extend(
                            (s.name, s.kind, list(s.params), s.feather,
                             s.invert) for s in parse_masks(seg))
                    except MaskError:
                        continue
                if not bad_masks_warned[0]:
                    bad_masks_warned[0] = True
                    messagebox.showwarning(
                        self._t("mask_tool"),
                        self._t("mask_bad_segment_warn"))
            try:
                adjusts = {k: dict(v) for k, v in
                           parse_mask_adjust(adj_s).items()}
            except MaskError:
                adjusts = {}
            photo[f] = {"specs": specs, "adjusts": adjusts,
                        "visible": {s[0]: True for s in specs}}
        idx = [0]
        if start_path and start_path in files:
            idx[0] = files.index(start_path)
        current = {"name": None}  # selected mask name
        # undo history: deep snapshots of the CURRENT photo's state, pushed
        # before every mutating action; Ctrl+Z / undo button pops one.
        undo_stack = []
        _MAX_UNDO = 50
        tool = tk.StringVar(value="brush")
        brush_r = tk.DoubleVar(value=0.06)
        feather_v = tk.DoubleVar(value=0.0)  # feather as fraction 0..1
        ai_label = tk.StringVar(value="car")
        color_vals = [tk.StringVar(value=v) for v in ("255", "60", "60")]
        _img_photo = {"tk": None, "pil": None, "scale": 1.0,
                      "ox": 0, "oy": 0}  # canvas->image mapping
        _MASK_COLORS = [(255, 70, 70), (70, 140, 255), (70, 220, 110),
                        (250, 200, 60), (220, 90, 240), (90, 230, 230)]

        top = tk.Frame(host, bg=COLORS["bg"])
        top.pack(fill="x", padx=12, pady=(10, 4))
        page_lbl = tk.Label(top, text="", font=FONT_SMALL,
                            fg=COLORS["text_secondary"], bg=COLORS["bg"])
        page_lbl.pack(side="left")
        tk.Label(top, text="", font=FONT_SMALL, bg=COLORS["bg"],
                 fg=COLORS["text_secondary"]).pack(side="left", padx=8)

        body = tk.Frame(host, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=12)

        # left: mask list
        lst_frame = tk.Frame(body, bg=COLORS["bg"])
        lst_frame.pack(side="left", fill="y", padx=(0, 12))
        tk.Label(lst_frame, text=self._t("mask_list"),
                 font=FONT_SECTION, fg=COLORS["text"],
                 bg=COLORS["bg"]).pack(anchor="w")
        lst = tk.Listbox(lst_frame, width=26, height=14, font=FONT_SMALL,
                         exportselection=False, bg=COLORS["card"],
                         fg=COLORS["text"], relief="flat",
                         highlightthickness=1,
                         highlightbackground=COLORS["border"],
                         selectmode=tk.SINGLE)
        lst.pack(fill="both", expand=True)
        order_bar = tk.Frame(lst_frame, bg=COLORS["bg"])
        order_bar.pack(fill="x", pady=(4, 0))
        for key, label in (("up", "mask_up"), ("down", "mask_down")):
            FlatButton(order_bar, text=self._t(label),
                       command=lambda k=key: _move_layer(k),
                       bg=COLORS["bg"], fg=COLORS["text"],
                       hover_bg=COLORS["border"], font=FONT_SMALL,
                       padx=6, pady=1, border_color=COLORS["border"]).pack(
                side="left", padx=(0, 6))
        vis_vars = {}  # name -> tk.BooleanVar

        def _specs():
            return photo[files[idx[0]]]["specs"]

        def _adjusts():
            return photo[files[idx[0]]]["adjusts"]

        def _visible():
            return photo[files[idx[0]]]["visible"]

        def _snapshot():
            """Deep copy of the current photo's mask state (for undo)."""
            return {"specs": [(s[0], s[1], list(s[2]), s[3], s[4])
                              for s in _specs()],
                    "adjusts": {k: dict(v) for k, v in
                                _adjusts().items()},
                    "visible": dict(_visible())}

        def _push_undo():
            undo_stack.append((files[idx[0]], _snapshot()))
            del undo_stack[:-_MAX_UNDO]

        def _undo():
            if not undo_stack:
                return
            path, snap = undo_stack.pop()
            if path == "__all__":  # apply-to-all 快照：还原全部照片
                for f, s in snap.items():
                    photo[f] = s
                current["name"] = None
                ai_cache.clear()
                _load_adjusts()
                _refresh_list()
                _draw_image()
                return
            if path != files[idx[0]]:
                # undo belongs to another photo: jump there, then restore
                idx[0] = files.index(path)
            photo[path] = snap
            current["name"] = None
            mode["add"] = None  # A/B 模式是临时的，跨照片/撤销不残留
            ai_cache.clear()
            _load_adjusts()
            _refresh_list()
            _draw_image()
            page_lbl.config(text=self._t("mask_page",
                                         cur=idx[0] + 1, total=len(files)))

        def _refresh_list(select=None):
            lst.delete(0, tk.END)
            for name, kind, params, feather, invert in _specs():
                lst.insert(tk.END, f"{name}  [{kind}]"
                                   f"  {'✓' if _visible().get(name) else ''}")
            if select is not None:
                for i, s in enumerate(_specs()):
                    if s[0] == select:
                        lst.selection_clear(0, tk.END)
                        lst.selection_set(i)
                        break

        def _move_layer(direction):
            """Reorder the current mask in the layer stack (list order =
            paint order: later entries paint on top)."""
            sel = lst.curselection()
            if not sel:
                return
            idx = sel[0]
            specs = _specs()
            if idx >= len(specs):
                return
            if direction == "up" and idx > 0:
                _push_undo()
                specs[idx], specs[idx - 1] = specs[idx - 1], specs[idx]
                idx -= 1
            elif direction == "down" and idx < len(specs) - 1:
                _push_undo()
                specs[idx], specs[idx + 1] = specs[idx + 1], specs[idx]
                idx += 1
            else:
                return
            name = specs[idx][0]
            current["name"] = name
            _refresh_list(select=name)
            _draw_image()

        # center: big canvas
        canvas = tk.Canvas(body, width=700, height=460, bg=COLORS["card"],
                           highlightthickness=1,
                           highlightbackground=COLORS["border"],
                           cursor="crosshair")
        canvas.pack(side="left", fill="both", expand=True)
        # AI mask cache: (path, mask_name) -> float32 hxw mask; AI inference
        # is slow, so overlay redraws reuse it instead of re-segmenting.
        ai_cache = {}
        ai_skip_warned = [False]  # AI 叠加层渲染失败只警告一次
        # v2.4 WYSIWYG: per-photo develop-rendered base (tone adjustments,
        # no masks — the canvas blends its own live mask overlays)
        adj_cache = {}

        def _draw_image():
            """Fit the current photo into the canvas, with overlay."""
            if not host.winfo_exists():
                return  # 窗口已关闭（<50ms 内关窗时 after 回调仍会触发）
            canvas.delete("all")
            import numpy as np
            from PIL import Image as PILImage, ImageTk
            path = files[idx[0]]
            base = None
            try:
                # _open_image_safe：RAW 回退引擎加载器（rawpy），
                # 摄影师工作流主力格式在画布上正常显示
                base = adj_cache.get(path) or _open_image_safe(path)
                base = base.convert("RGB")
                base.thumbnail((700, 460), PILImage.LANCZOS)
            except Exception:
                base = PILImage.new("RGB", (700, 460), (40, 40, 40))
            if path not in adj_cache and path in self._photo_adjust:

                def _deliver(result, err, _p=path):
                    if not host.winfo_exists() or files[idx[0]] != _p:
                        return
                    if not result:
                        return  # original stays on failure
                    try:
                        img = _open_image_safe(result.output_path)
                        adj_cache[_p] = img
                        if files[idx[0]] == _p:
                            _draw_image()
                    except Exception:
                        pass

                self._render_adjusted_async(
                    path, _deliver, include_masks=False)
            cw, ch = canvas.winfo_width(), canvas.winfo_height()
            if cw < 50 or ch < 50:  # canvas not laid out yet
                cw, ch = 700, 460
            scale = min(cw / base.width, ch / base.height)
            disp = base.resize((max(1, int(base.width * scale)),
                                max(1, int(base.height * scale))),
                               PILImage.LANCZOS)
            ox, oy = (cw - disp.width) // 2, (ch - disp.height) // 2
            _img_photo.update({"pil": base, "scale": scale,
                               "ox": ox, "oy": oy})
            # overlay: blend each visible mask with its color
            specs = _specs()
            # combo 蒙版按名引用其他蒙版——refs + name 缺一不可，
            # 否则 render_mask 报"需要完整蒙版列表"（并误触发 AI 警告）
            refs = {s[0]: MaskSpec(s[1], tuple(s[2]), s[3], s[4], s[0])
                    for s in specs}
            over = np.asarray(disp, dtype=np.float32).copy()
            for i, (name, kind, params, feather, invert) in enumerate(specs):
                if not _visible().get(name, True):
                    continue
                try:
                    if kind in ("subject", "person", "object"):
                        key = (path, name)
                        if key not in ai_cache:
                            ai_cache[key] = render_mask(
                                MaskSpec(kind, tuple(params), feather,
                                         invert, name),
                                base.width, base.height, img=base,
                                refs=refs)
                        m = ai_cache[key]
                    else:
                        m = render_mask(MaskSpec(kind, tuple(params),
                                                 feather, invert, name),
                                        base.width, base.height, img=base,
                                        refs=refs)
                    m = np.asarray(
                        PILImage.fromarray(
                            (m * 255).astype(np.uint8), "L")
                        .resize(disp.size)).astype(np.float32) / 255.0
                    c = _MASK_COLORS[i % len(_MASK_COLORS)]
                    for k in range(3):
                        over[..., k] = over[..., k] * (1 - 0.55 * m) \
                            + c[k] * 0.55 * m
                except MaskError:
                    # AI 蒙版缺 cv2/权重时叠加层静默跳过 → 列表带 ✓ 但画布
                    # 隐形，用户到批量才见失败——一次性点明原因
                    if not ai_skip_warned[0]:
                        ai_skip_warned[0] = True
                        messagebox.showwarning(
                            self._t("mask_tool"),
                            self._t("mask_ai_overlay_warn"))
                    continue
            out = PILImage.fromarray(np.clip(over, 0, 255).astype(np.uint8))
            _img_photo["tk"] = ImageTk.PhotoImage(out, master=canvas)
            canvas.create_image(ox, oy, image=_img_photo["tk"],
                                anchor="nw")

        def _canvas_to_img(evt):
            return ((evt.x - _img_photo["ox"]) / _img_photo["scale"],
                    (evt.y - _img_photo["oy"]) / _img_photo["scale"])

        def _img_to_rel(x, y):
            base = _img_photo["pil"]
            if base is None:
                return 0.0, 0.0
            return (max(0.0, min(1.0, x / base.width)),
                    max(0.0, min(1.0, y / base.height)))

        def _new_spec_name(kind):
            base = kind if kind != "color" else "color"
            existing = {s[0] for s in _specs()}
            i = 1
            while f"{base}{i}" in existing:
                i += 1
            return f"{base}{i}"

        def _set_current_mask(name, spec, adjust=None):
            """Replace or append the named mask in the current photo."""
            _push_undo()
            specs = _specs()
            for i, s in enumerate(specs):
                if s[0] == name:
                    specs[i] = spec
                    break
            else:
                specs.append(spec)
            _visible()[name] = True
            if adjust is not None:
                _adjusts()[name] = adjust
            current["name"] = name
            _refresh_list(select=name)

        def _finish_paint(kind, params, feather=0.0, adjust=None):
            name = current["name"]
            existing = next((s for s in _specs() if s[0] == name), None)
            # 只在与新蒙版同类型时复用名字（A/B 笔画追加）；异类工具
            # 必须新建——否则选中 radial 切 linear 拖一笔会把 radial
            # 静默替换（取色/AI 同理）
            if not existing or existing[1] != kind:
                name = _new_spec_name(kind)
            # brush dots each carry their own radius; feather applies to
            # every kind except color (color has tol, not feather). When
            # appending A/B strokes to an existing mask, keep its feather.
            if kind != "color":
                feather = feather_v.get() if existing is None \
                    else existing[3]
            spec = (name, kind, list(params), feather, False)
            _set_current_mask(name, spec, adjust)

        # ── canvas drag handlers ─────────────────────────────────────────
        drag = {"active": False, "x0": 0, "y0": 0, "x1": 0, "y1": 0,
                "dots": []}
        mode = {"add": None}  # None = paint new; True/False = A add / B
        # subtract strokes onto the current brush mask
        move = {"active": False, "name": None, "dx0": 0, "dy0": 0,
                "orig": None, "moved": False}  # Alt+drag moves an existing mask

        def _mask_at(evt):
            """Return the name of the topmost visible mask under the cursor,
            or None.

            Geometric/brush masks hit-test by distance to their centers/
            axes (a brush stroke is easy to miss through the soft Gaussian
            tail); AI masks hit-test on the rendered mask value (their
            silhouette is the meaningful target).
            """
            base = _img_photo["pil"]
            if base is None:
                return None
            x, y = _canvas_to_img(evt)
            xi = max(0, min(base.width - 1, int(x)))
            yi = max(0, min(base.height - 1, int(y)))
            rx = x / base.width
            ry = y / base.height
            short = float(min(base.width, base.height))
            for name, kind, params, feather, invert in reversed(_specs()):
                if not _visible().get(name, True):
                    continue
                try:
                    if kind in ("subject", "person", "object"):
                        key = (files[idx[0]], name)
                        if key not in ai_cache:
                            ai_cache[key] = render_mask(
                                MaskSpec(kind, tuple(params), feather,
                                         invert),
                                base.width, base.height, img=base)
                        if ai_cache[key][yi, xi] > 0.3:
                            return name
                        continue
                    if kind == "brush":
                        if any((px - rx) ** 2 + (py - ry) ** 2
                               <= (r * 1.5) ** 2
                               for px, py, r in params if r >= 0):
                            return name
                        continue
                    if kind == "linear":
                        x0, y0, x1, y1 = params
                        dx, dy = x1 - x0, y1 - y0
                        l2 = dx * dx + dy * dy
                        if l2 == 0:
                            continue
                        t = ((rx - x0) * dx + (ry - y0) * dy) / l2
                        if 0.0 <= t <= 1.0:
                            px = x0 + t * dx
                            py = y0 + t * dy
                            # 10% of short side, in normalized units
                            tol = 0.1 * short / max(base.width, base.height)
                            if (px - rx) ** 2 + (py - ry) ** 2 <= tol ** 2:
                                return name
                        continue
                    if kind == "radial":
                        cx, cy, rxx, ryy = params
                        d = ((rx - cx) / rxx) ** 2 + ((ry - cy) / ryy) ** 2
                        if d <= 1.0:
                            return name
                        continue
                    # color masks don't move (no spatial center)
                except MaskError:
                    if not ai_skip_warned[0]:
                        ai_skip_warned[0] = True
                        messagebox.showwarning(
                            self._t("mask_tool"),
                            self._t("mask_ai_overlay_warn"))
                    continue
            return None

        def _move_mask(evt):
            """Live-move the mask under Alt+drag: shift params by the
            pointer delta (in relative image coords)."""
            dx_canvas = evt.x - move["dx0"]
            dy_canvas = evt.y - move["dy0"]
            scale = _img_photo["scale"]
            base = _img_photo["pil"]
            if base is None or scale <= 0:
                return
            if abs(dx_canvas) > 1 or abs(dy_canvas) > 1:
                move["moved"] = True  # 无位移的点击不记 undo
            drx = dx_canvas / scale / base.width
            dry = dy_canvas / scale / base.height
            name = move["name"]
            for i, s in enumerate(_specs()):
                if s[0] != name:
                    continue
                kind, params = s[1], move["orig"]
                if kind == "brush":
                    moved = [(max(0.0, min(1.0, x + drx)),
                              max(0.0, min(1.0, y + dry)), r)
                             for x, y, r in params]
                elif kind == "linear":
                    moved = [max(0.0, min(1.0, p + (drx if j % 2 == 0
                                                     else dry)))
                             for j, p in enumerate(params)]
                elif kind == "radial":
                    moved = [max(0.0, min(1.0, params[0] + drx)),
                             max(0.0, min(1.0, params[1] + dry)),
                             params[2], params[3]]
                elif kind == "color":
                    moved = list(params)  # color masks don't move
                else:
                    moved = list(params)
                _specs()[i] = (s[0], kind, moved, s[3], s[4])
                _refresh_list(select=name)
                _draw_image()
                return

        def _on_press(evt):
            # Drag inside an existing mask moves it (LR-style). Exceptions:
            # - A/B mode (user explicitly clicked A or B) with a current
            #   brush mask: pressing paints strokes onto the mask instead
            #   of moving it.
            # - color tool: always picks a color.
            painting = (tool.get() == "brush" and mode["add"] is not None
                        and current["name"] is not None
                        and any(s[0] == current["name"] and s[1] == "brush"
                                for s in _specs()))
            hit = None if painting or tool.get() == "color" \
                else _mask_at(evt)
            if hit:
                for i, s in enumerate(_specs()):
                    if s[0] == hit:
                        # 先存旧蒙版的滑杆编辑再切换，防静默丢失
                        _save_adjusts()
                        move.update({"active": True, "name": hit,
                                     "dx0": evt.x, "dy0": evt.y,
                                     "orig": list(s[2]), "moved": False})
                        current["name"] = hit
                        feather_v.set(s[3] * 100)  # 画布点击同步羽化滑杆
                        _refresh_list(select=hit)
                        _load_adjusts()
                        return
            if tool.get() == "color":
                x, y = _canvas_to_img(evt)
                base = _img_photo["pil"]
                if base is None:
                    return
                px = base.getpixel((max(0, min(base.width - 1, int(x))),
                                    max(0, min(base.height - 1, int(y)))))
                color_vals[0].set(str(px[0]))
                color_vals[1].set(str(px[1]))
                color_vals[2].set(str(px[2]))
                _finish_paint("color",
                              (px[0], px[1], px[2], 0.15))
                _draw_image()
                return
            drag.update({"active": True, "x0": evt.x, "y0": evt.y,
                         "x1": evt.x, "y1": evt.y,
                         "dots": [(evt.x, evt.y)]})

        def _on_drag(evt):
            if move["active"]:
                _move_mask(evt)
                return
            if not drag["active"]:
                return
            drag["x1"], drag["y1"] = evt.x, evt.y
            if tool.get() == "brush":
                drag["dots"].append((evt.x, evt.y))
            canvas.delete("guide")
            if tool.get() == "linear":
                canvas.create_line(drag["x0"], drag["y0"], evt.x, evt.y,
                                   fill="#ffffff", width=1, tags="guide",
                                   dash=(4, 3))
            elif tool.get() == "radial":
                # dashed ellipse: start point is the center, drag extends
                # the radii; bounding box = center ± (dx, dy)
                cx, cy = drag["x0"], drag["y0"]
                rx, ry = abs(evt.x - cx), abs(evt.y - cy)
                canvas.create_oval(cx - rx, cy - ry, cx + rx, cy + ry,
                                   outline="#ffffff", width=1.5,
                                   tags="guide", dash=(5, 4))
                canvas.create_line(drag["x0"], drag["y0"], evt.x, evt.y,
                                   fill="#ffffff", width=1, tags="guide",
                                   dash=(2, 3))
            elif tool.get() == "brush":
                for px, py in drag["dots"]:
                    r = max(2, brush_r.get() * 30)
                    canvas.create_oval(px - r, py - r, px + r, py + r,
                                       fill="#ff4444", stipple="gray50",
                                       outline="", tags="guide")

        def _on_release(evt):
            if move["active"]:
                # moving is undoable as one step
                move["active"] = False
                if move["moved"]:
                    _push_undo()
                move["moved"] = False
                return
            if not drag["active"]:
                return
            drag["active"] = False
            canvas.delete("guide")
            if tool.get() == "brush":
                dots = []
                for px, py in drag["dots"]:
                    x, y = _canvas_to_img(type("E", (), {"x": px, "y": py})())
                    rx, ry = _img_to_rel(x, y)
                    dots.append((rx, ry, brush_r.get()))
                if not dots:
                    return
                # A/B modes: append to the current brush mask instead of
                # replacing it (subtract dots get a negative radius).
                cur = current["name"]
                cur_spec = None
                for s in _specs():
                    if s[0] == cur and s[1] == "brush":
                        cur_spec = s
                        break
                if cur_spec is not None and mode["add"] is False:
                    neg = [(x, y, -r) for x, y, r in dots]
                    _finish_paint("brush", list(cur_spec[2]) + neg)
                    return
                if cur_spec is not None and mode["add"]:
                    _finish_paint("brush", list(cur_spec[2]) + dots)
                    return
                _finish_paint("brush", dots)
            elif tool.get() == "linear":
                x0, y0 = _img_to_rel(*_canvas_to_img(
                    type("E", (), {"x": drag["x0"], "y": drag["y0"]})()))
                x1, y1 = _img_to_rel(*_canvas_to_img(
                    type("E", (), {"x": drag["x1"], "y": drag["y1"]})()))
                # 点击未拖动 → 零长度渐变：画布上隐形（全 NaN→全 0）、
                # 批量时 parse 必失败——不创建蒙版
                if (x1 - x0) ** 2 + (y1 - y0) ** 2 < 1e-12:
                    return
                _finish_paint("linear", (x0, y0, x1, y1))
            elif tool.get() == "radial":
                cx, cy = _img_to_rel(*_canvas_to_img(
                    type("E", (), {"x": drag["x0"], "y": drag["y0"]})()))
                ex, ey = _img_to_rel(*_canvas_to_img(
                    type("E", (), {"x": drag["x1"], "y": drag["y1"]})()))
                rx = max(0.01, abs(ex - cx))
                ry = max(0.01, abs(ey - cy))
                _finish_paint("radial", (cx, cy, rx, ry))
            _draw_image()

        canvas.bind("<Button-1>", _on_press)
        canvas.bind("<B1-Motion>", _on_drag)
        canvas.bind("<ButtonRelease-1>", _on_release)

        def _ai_mask(kind, label=None):
            """Add an AI mask (subject/person/object) to the current photo."""
            try:
                from ...segmask import segment
                base = _img_photo["pil"]
                if base is None:
                    return
                # CPU 推理耗时数秒：先落 watch 光标 + 状态提示，避免
                # 无反馈冻结（异步化需要 queue 模式，超出本对话框范围）
                host.config(cursor="watch")
                host.update_idletasks()
                try:
                    m = segment(base, kind, label=label)
                finally:
                    host.config(cursor="")
                if m.max() < 0.01:
                    messagebox.showwarning(
                        self._t("mask_ai_empty"), self._t("mask_ai_empty"))
                    return
                # 仅同类型蒙版才复用名字（重跑同一分割）；异类蒙版
                # 被选中时新建，防静默替换
                name = current["name"] if current["name"] and any(
                    s[0] == current["name"] and s[1] == kind
                    for s in _specs()) else None
                if not name:
                    name = _new_spec_name(kind)
                ai_cache.pop((files[idx[0]], name), None)
                _set_current_mask(name, (name, kind, [label] if label
                                         else [],
                                         feather_v.get() / 100.0, False))
                _refresh_list(select=name)
                _draw_image()
            except (ImportError, RuntimeError) as e:
                messagebox.showwarning(self._t("mask_tool"), f"AI: {e}")

        # right: tools + adjustments
        right = tk.Frame(body, bg=COLORS["bg"])
        right.pack(side="right", fill="y", padx=(12, 0))
        tk.Label(right, text=self._t("mask_tool"), font=FONT_SECTION,
                 fg=COLORS["text"], bg=COLORS["bg"]).pack(anchor="w")
        tools = (("brush", "mask_tool_brush"), ("linear", "mask_tool_linear"),
                 ("radial", "mask_tool_radial"), ("color", "mask_tool_color"),
                 ("subject", "mask_tool_subject"),
                 ("person", "mask_tool_person"),
                 ("object", "mask_tool_object"))
        for key, label in tools:
            if key in ("subject", "person", "object"):
                FlatButton(
                    right, text=self._t(label),
                    command=lambda k=key: _ai_mask(
                        k, ai_label.get().strip() if k == "object" else None),
                    bg=COLORS["bg"], fg=COLORS["text"],
                    hover_bg=COLORS["border"], font=FONT_SMALL,
                    padx=8, pady=2, border_color=COLORS["border"]).pack(
                    fill="x", pady=(0, 4))
            else:
                FlatButton(right, text=self._t(label),
                           command=lambda k=key: tool.set(k),
                           bg=COLORS["bg"], fg=COLORS["text"],
                           hover_bg=COLORS["border"], font=FONT_SMALL,
                           padx=8, pady=2,
                           border_color=COLORS["border"]).pack(
                    fill="x", pady=(0, 4))
        tk.Label(right, text=self._t("mask_ai_label"), font=FONT_TINY,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).pack(anchor="w")
        ttk.Entry(right, textvariable=ai_label, font=FONT_BODY,
                  width=12).pack(fill="x", pady=(0, 6))
        mode_frame = tk.Frame(right, bg=COLORS["bg"])
        mode_frame.pack(fill="x", pady=(0, 6))
        for key, label in (("add", "mask_mode_add"),
                           ("subtract", "mask_mode_subtract")):
            FlatButton(mode_frame, text=self._t(label),
                       command=lambda k=key: mode.__setitem__(
                           "add", k == "add"),
                       bg=COLORS["bg"], fg=COLORS["text"],
                       hover_bg=COLORS["border"], font=FONT_SMALL,
                       padx=8, pady=2, border_color=COLORS["border"]).pack(
                side="left", padx=(0, 6))
        FlatButton(mode_frame, text=self._t("mask_mode_off"),
                   command=lambda: mode.__setitem__("add", None),
                   bg=COLORS["bg"], fg=COLORS["text"],
                   hover_bg=COLORS["border"], font=FONT_SMALL,
                   padx=8, pady=2, border_color=COLORS["border"]).pack(
            side="left")
        tk.Label(right, text=self._t("mask_brush_size"), font=FONT_TINY,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).pack(anchor="w")
        ttk.Scale(right, from_=0.01, to=0.3, variable=brush_r).pack(
            fill="x", pady=(0, 2))
        tk.Label(right, text=self._t("mask_feather"), font=FONT_TINY,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).pack(anchor="w")
        ttk.Scale(right, from_=0, to=100, variable=feather_v,
                  command=lambda _v: _apply_feather()).pack(
            fill="x", pady=(0, 8))
        FlatButton(right, text=self._t("mask_add"), command=lambda:
                   current.__setitem__("name", None),
                   bg=COLORS["bg"], fg=COLORS["text"],
                   hover_bg=COLORS["border"], font=FONT_SMALL,
                   padx=8, pady=2, border_color=COLORS["border"]).pack(
            fill="x", pady=(0, 4))
        FlatButton(right, text=self._t("mask_del"),
                   command=lambda: _delete_current(),
                   bg=COLORS["bg"], fg=COLORS["text"],
                   hover_bg=COLORS["border"], font=FONT_SMALL,
                   padx=8, pady=2, border_color=COLORS["border"]).pack(
            fill="x", pady=(0, 4))

        def _delete_current():
            name = current["name"]
            if not name:
                return
            _push_undo()
            _specs()[:] = [s for s in _specs() if s[0] != name]
            _adjusts().pop(name, None)
            _visible().pop(name, None)
            current["name"] = None
            ai_cache.clear()  # 该蒙版的分割缓存随删除失效
            _refresh_list()
            _draw_image()

        def _toggle_visible(name):
            if not name:
                return
            _push_undo()
            _visible()[name] = not _visible().get(name, True)
            _refresh_list(select=name)
            _draw_image()

        lst.bind("<<ListboxSelect>>", lambda e: _select_from_list())
        lst.bind("<space>", lambda e: _toggle_visible(
            current["name"]) if current["name"] else None)

        def _select_from_list():
            sel = lst.curselection()
            if sel and sel[0] < len(_specs()):
                current["name"] = _specs()[sel[0]][0]
                feather_v.set(_specs()[sel[0]][3] * 100)

        feather_undo = {"name": None, "val": None}  # 拖动过程只 push 一次

        def _apply_feather(*_):
            """Live-update the selected mask's feather from the slider."""
            name = current["name"]
            if not name:
                return
            for i, s in enumerate(_specs()):
                if s[0] == name and s[1] != "color":
                    v = feather_v.get() / 100.0
                    if abs(s[3] - v) > 1e-6:
                        # 逐 tick push 会把 50 cap 的旧快照全挤出栈；
                        # 同一次拖动（值单调变化）只记录一个 undo
                        if feather_undo["name"] != name or \
                                abs(feather_undo["val"] - s[3]) > 1e-9:
                            _push_undo()
                            feather_undo.update(name=name, val=v)
                        _specs()[i] = (s[0], s[1], list(s[2]), v, s[4])
                        _refresh_list(select=name)
                        _draw_image()
                        return

        # ── adjustments for the current mask ─────────────────────────────
        adj_vars = {key: tk.DoubleVar(value=0.0) for key in (
            "exposure", "brightness", "contrast", "saturation", "vibrance",
            "clarity", "texture", "sharpen", "temp", "tint", "blur")}
        tk.Label(right, text=self._t("mask_adjust_sec"), font=FONT_SECTION,
                 fg=COLORS["text"], bg=COLORS["bg"]).pack(anchor="w",
                                                          pady=(10, 0))
        _ADJ_META = (
            ("exposure", -3, 3), ("brightness", -1, 1), ("contrast", -1, 1),
            ("saturation", -1, 1), ("vibrance", -1, 1), ("clarity", -1, 1),
            ("texture", -1, 1), ("sharpen", -1, 1), ("temp", 0, 12000),
            ("tint", -100, 100), ("blur", 0, 50),
        )
        for i, (key, lo, hi) in enumerate(_ADJ_META):
            tk.Label(right, text=self._t("adj_" + key), font=FONT_TINY,
                     fg=COLORS["text_secondary"], bg=COLORS["bg"]).pack(
                anchor="w")
            ttk.Scale(right, from_=lo, to=hi, variable=adj_vars[key]).pack(
                fill="x")

        def _save_adjusts():
            name = current["name"]
            if not name:
                return
            # 从既有 dict 合并而非整体替换：滑杆只覆盖标量键，
            # 字符串键（curves/hsl/... 来自 CLI/预设）不被静默丢掉
            adjust = _adjusts().get(name, {})
            for k, var in adj_vars.items():
                v = round(var.get(), 3)
                if v != 0.0:
                    adjust[k] = v
                else:
                    adjust.pop(k, None)
            _adjusts()[name] = adjust

        def _load_adjusts():
            name = current["name"]
            for k, var in adj_vars.items():
                var.set(0.0)
            if not name:
                return
            for k, v in _adjusts().get(name, {}).items():
                if k in adj_vars:
                    adj_vars[k].set(v)

        lst.bind("<<ListboxSelect>>",
                 lambda e: (_save_adjusts(), _select_from_list(),
                            _load_adjusts()))

        # ── paging ───────────────────────────────────────────────────────
        def _page(delta):
            _save_adjusts()
            idx[0] = (idx[0] + delta) % len(files)
            current["name"] = None
            mode["add"] = None  # A/B 模式不跨照片残留
            ai_cache.clear()    # 缓存按 (path, name) 键，翻页后旧图不清理会无界增长
            _load_adjusts()
            _refresh_list()
            _draw_image()
            page_lbl.config(text=self._t("mask_page",
                                         cur=idx[0] + 1, total=len(files)))

        def _page_prev():
            _page(-1)

        def _page_next():
            _page(1)

        host.bind("<Left>", lambda e: _page_prev())
        host.bind("<Right>", lambda e: _page_next())
        host.bind("<Command-z>", lambda e: _undo())
        host.bind("<Control-z>", lambda e: _undo())

        bottom = tk.Frame(host, bg=COLORS["bg"])
        bottom.pack(fill="x", padx=12, pady=(6, 12))
        FlatButton(bottom, text=self._t("mask_prev"), command=_page_prev,
                   bg=COLORS["bg"], fg=COLORS["text"],
                   hover_bg=COLORS["border"], font=FONT_SMALL,
                   padx=8, pady=2, border_color=COLORS["border"]).pack(
            side="left")
        FlatButton(bottom, text=self._t("mask_next"), command=_page_next,
                   bg=COLORS["bg"], fg=COLORS["text"],
                   hover_bg=COLORS["border"], font=FONT_SMALL,
                   padx=8, pady=2, border_color=COLORS["border"]).pack(
            side="left", padx=(6, 0))
        FlatButton(bottom, text=self._t("mask_apply_all"),
                   command=lambda: _apply_all(),
                   bg=COLORS["bg"], fg=COLORS["text"],
                   hover_bg=COLORS["border"], font=FONT_SMALL,
                   padx=8, pady=2, border_color=COLORS["border"]).pack(
            side="left", padx=(24, 0))
        FlatButton(bottom, text=self._t("mask_undo"), command=_undo,
                   bg=COLORS["bg"], fg=COLORS["text"],
                   hover_bg=COLORS["border"], font=FONT_SMALL,
                   padx=8, pady=2, border_color=COLORS["border"]).pack(
            side="left", padx=(8, 0))

        def _apply_all():
            """Copy current photo's masks to every checked photo (deep)."""
            # 全量快照：Ctrl+Z 还原所有照片，而不是只剩当前一张
            undo_stack.append(("__all__", {
                f: {"specs": [(s[0], s[1], list(s[2]), s[3], s[4])
                              for s in photo[f]["specs"]],
                    "adjusts": {k: dict(v) for k, v in
                                photo[f]["adjusts"].items()},
                    "visible": dict(photo[f]["visible"])}
                for f in files}))
            del undo_stack[:-_MAX_UNDO]
            src = photo[files[idx[0]]]
            for f in files:
                photo[f] = {
                    "specs": [(s[0], s[1], list(s[2]), s[3], s[4])
                              for s in src["specs"]],
                    "adjusts": {k: dict(v) for k, v in
                                src["adjusts"].items()},
                    "visible": dict(src["visible"])}
            self.masks.set(_serialize_masks(photo[f]["specs"],
                                            photo[f]["adjusts"]))

        def _n(v):
            if isinstance(v, str):
                return v  # v1.8 字符串型局部调整（curves={...} 等）透传
            v = round(float(v), 4)
            return str(int(v)) if v == int(v) else str(v)

        def _serialize_masks(specs, adjusts):
            """Per-photo state -> (masks_str, mask_adjust_str)."""
            mask_segs = [_mask_spec_string(*s) for s in specs]
            adj_segs = []
            for name, adjust in adjusts.items():
                if not adjust or name not in {s[0] for s in specs}:
                    continue
                adj_segs.append(name + ":" + ",".join(
                    f"{k}={_n(v)}" for k, v in adjust.items()))
            return ";".join(mask_segs), ";".join(adj_segs)

        def _apply_state():
            """序列化全部照片的蒙版状态到 _photo_masks（弹窗 OK 与
            Develop 退出共用——纯写入，不触碰 UI 生命周期）。"""
            _save_adjusts()
            if self._photo_masks is None:
                self._photo_masks = {}
            for f in files:
                masks_s, adj_s = _serialize_masks(
                    photo[f]["specs"], photo[f]["adjusts"])
                if masks_s == self.masks.get().strip() and \
                        adj_s == self.mask_adjust.get().strip():
                    self._photo_masks.pop(f, None)  # same as global
                else:
                    self._photo_masks[f] = {"masks": masks_s,
                                            "mask_adjust": adj_s}

        if hosted:
            # 内嵌：完成 = 应用 + 退回调色视图（退出路径单一，防重入）
            FlatButton(bottom, text=self._t("mask_done"),
                       command=self._dev_exit_mask_mode,
                       bg=COLORS["bg"], fg=COLORS["text"],
                       hover_bg=COLORS["border"], font=FONT_SMALL,
                       padx=10, pady=3, border_color=COLORS["border"]).pack(
                side="right")
        else:
            def _ok_close():
                _apply_state()
                host.destroy()

            FlatButton(bottom, text=self._t("ok"), command=_ok_close,
                       bg=COLORS["bg"], fg=COLORS["text"],
                       hover_bg=COLORS["border"], font=FONT_SMALL,
                       padx=10, pady=3, border_color=COLORS["border"]).pack(
                side="right")
            FlatButton(bottom, text=self._t("cancel"),
                       command=host.destroy,
                       bg=COLORS["bg"], fg=COLORS["text"],
                       hover_bg=COLORS["border"], font=FONT_SMALL,
                       padx=10, pady=3, border_color=COLORS["border"]).pack(
                side="right", padx=(0, 8))

        tk.Label(host, text=self._t("mask_overlay_hint"), font=FONT_TINY,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).pack(
            fill="x", padx=12, pady=(0, 2))
        tk.Label(host, text=self._t("mask_drag_hint"), font=FONT_TINY,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).pack(
            fill="x", padx=12, pady=(0, 8))

        _refresh_list()
        _draw_image()
        page_lbl.config(text=self._t("mask_page", cur=idx[0] + 1,
                                     total=len(files)))
        host.after(50, _draw_image)  # canvas size settled after layout

        return {"apply": _apply_state, "undo": _undo,
                "page_prev": _page_prev, "page_next": _page_next}

        def _set_current_mask(name, spec, adjust=None):
            """Replace or append the named mask in the current photo."""
            _push_undo()
            specs = _specs()
            for i, s in enumerate(specs):
                if s[0] == name:
                    specs[i] = spec
                    break
            else:
                specs.append(spec)
            _visible()[name] = True
            if adjust is not None:
                _adjusts()[name] = adjust
            current["name"] = name
            _refresh_list(select=name)

        def _mask_at(evt):
            """Return the name of the topmost visible mask under the cursor,
            or None.

            Geometric/brush masks hit-test by distance to their centers/
            axes (a brush stroke is easy to miss through the soft Gaussian
            tail); AI masks hit-test on the rendered mask value (their
            silhouette is the meaningful target).
            """
            base = _img_photo["pil"]
            if base is None:
                return None
            x, y = _canvas_to_img(evt)
            xi = max(0, min(base.width - 1, int(x)))
            yi = max(0, min(base.height - 1, int(y)))
            rx = x / base.width
            ry = y / base.height
            short = float(min(base.width, base.height))
            for name, kind, params, feather, invert in reversed(_specs()):
                if not _visible().get(name, True):
                    continue
                try:
                    if kind in ("subject", "person", "object"):
                        key = (files[idx[0]], name)
                        if key not in ai_cache:
                            ai_cache[key] = render_mask(
                                MaskSpec(kind, tuple(params), feather,
                                         invert),
                                base.width, base.height, img=base)
                        if ai_cache[key][yi, xi] > 0.3:
                            return name
                        continue
                    if kind == "brush":
                        if any((px - rx) ** 2 + (py - ry) ** 2
                               <= (r * 1.5) ** 2
                               for px, py, r in params if r >= 0):
                            return name
                        continue
                    if kind == "linear":
                        x0, y0, x1, y1 = params
                        dx, dy = x1 - x0, y1 - y0
                        l2 = dx * dx + dy * dy
                        if l2 == 0:
                            continue
                        t = ((rx - x0) * dx + (ry - y0) * dy) / l2
                        if 0.0 <= t <= 1.0:
                            px = x0 + t * dx
                            py = y0 + t * dy
                            # 10% of short side, in normalized units
                            tol = 0.1 * short / max(base.width, base.height)
                            if (px - rx) ** 2 + (py - ry) ** 2 <= tol ** 2:
                                return name
                        continue
                    if kind == "radial":
                        cx, cy, rxx, ryy = params
                        d = ((rx - cx) / rxx) ** 2 + ((ry - cy) / ryy) ** 2
                        if d <= 1.0:
                            return name
                        continue
                    # color masks don't move (no spatial center)
                except MaskError:
                    if not ai_skip_warned[0]:
                        ai_skip_warned[0] = True
                        messagebox.showwarning(
                            self._t("mask_tool"),
                            self._t("mask_ai_overlay_warn"))
                    continue
            return None

        def _move_mask(evt):
            """Live-move the mask under Alt+drag: shift params by the
            pointer delta (in relative image coords)."""
            dx_canvas = evt.x - move["dx0"]
            dy_canvas = evt.y - move["dy0"]
            scale = _img_photo["scale"]
            base = _img_photo["pil"]
            if base is None or scale <= 0:
                return
            if abs(dx_canvas) > 1 or abs(dy_canvas) > 1:
                move["moved"] = True  # 无位移的点击不记 undo
            drx = dx_canvas / scale / base.width
            dry = dy_canvas / scale / base.height
            name = move["name"]
            for i, s in enumerate(_specs()):
                if s[0] != name:
                    continue
                kind, params = s[1], move["orig"]
                if kind == "brush":
                    moved = [(max(0.0, min(1.0, x + drx)),
                              max(0.0, min(1.0, y + dry)), r)
                             for x, y, r in params]
                elif kind == "linear":
                    moved = [max(0.0, min(1.0, p + (drx if j % 2 == 0
                                                     else dry)))
                             for j, p in enumerate(params)]
                elif kind == "radial":
                    moved = [max(0.0, min(1.0, params[0] + drx)),
                             max(0.0, min(1.0, params[1] + dry)),
                             params[2], params[3]]
                elif kind == "color":
                    moved = list(params)  # color masks don't move
                else:
                    moved = list(params)
                _specs()[i] = (s[0], kind, moved, s[3], s[4])
                _refresh_list(select=name)
                _draw_image()
                return

        def _ai_mask(kind, label=None):
            """Add an AI mask (subject/person/object) to the current photo."""
            try:
                from ...segmask import segment
                base = _img_photo["pil"]
                if base is None:
                    return
                # CPU 推理耗时数秒：先落 watch 光标 + 状态提示，避免
                # 无反馈冻结（异步化需要 queue 模式，超出本对话框范围）
                host.config(cursor="watch")
                host.update_idletasks()
                try:
                    m = segment(base, kind, label=label)
                finally:
                    host.config(cursor="")
                if m.max() < 0.01:
                    messagebox.showwarning(
                        self._t("mask_ai_empty"), self._t("mask_ai_empty"))
                    return
                # 仅同类型蒙版才复用名字（重跑同一分割）；异类蒙版
                # 被选中时新建，防静默替换
                name = current["name"] if current["name"] and any(
                    s[0] == current["name"] and s[1] == kind
                    for s in _specs()) else None
                if not name:
                    name = _new_spec_name(kind)
                ai_cache.pop((files[idx[0]], name), None)
                _set_current_mask(name, (name, kind, [label] if label
                                         else [],
                                         feather_v.get() / 100.0, False))
                _refresh_list(select=name)
                _draw_image()
            except (ImportError, RuntimeError) as e:
                messagebox.showwarning(self._t("mask_tool"), f"AI: {e}")
