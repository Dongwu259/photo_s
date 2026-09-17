#!/usr/bin/env python3
"""PhotoS 演示视频生成器。

逐帧用 PIL 渲染，raw RGB 管道给 ffmpeg 编码——不依赖录屏，中文排版可控，
任意机器可复现。音频由 ffmpeg 合成配乐床 + macOS 系统音效，零版权风险。

用法：
    python3 tools/make_demo_video.py

产出（默认 demo/video/）：
    photos-demo.mp4          正片（1920x1080 / 30fps，带音轨）
    photos-demo.srt          字幕（平台单独上传用）
    photos-demo-cover.png    封面
    frames/                  各场景首帧（可当静态图发社媒）

依赖：Pillow、ffmpeg（PATH 内）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "demo" / "video"
SHOTS = REPO / "demo" / "screenshots"

W, H, FPS = 1920, 1080, 30
FADE = 0.6  # 场景间交叉淡入时长

# ── 配色（跟随 PhotoS 暗色主题观感） ────────────────────────────────────────
BG = (18, 20, 23)
CARD = (32, 36, 41)
BORDER = (52, 58, 65)
FG = (232, 236, 240)
DIM = (150, 158, 168)
ACCENT = (86, 156, 214)
GREEN = (92, 190, 122)
AMBER = (222, 176, 92)
TERM_BG = (14, 16, 18)

CJK = "/System/Library/Fonts/Hiragino Sans GB.ttc"
CJK_BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"
MONO = "/System/Library/Fonts/Menlo.ttc"

SYS_SOUNDS = Path("/System/Library/Sounds")


def font(path: str, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size, index=index)


_FM: dict = {}


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (0x3000 <= o <= 0x9FFF) or (0xFF00 <= o <= 0xFFEF)


def _fonts(size: int, bold: bool = False):
    key = (size, bold)
    if key not in _FM:
        _FM[key] = (font(MONO, size, 1 if bold else 0), font(CJK, size))
    return _FM[key]


def text_mixed(d: ImageDraw.ImageDraw, xy, s, size, fill, bold=False):
    """按字符类型混排：ASCII 走 Menlo（等宽），CJK 走 Hiragino（避免豆腐块）。

    终端里命令/输出保持等宽的代码观感，同时中文注释可读。
    注意：切换字体时先把当前字符并进缓冲再结算，否则边界字符会被吞掉。
    """
    f_lat, f_cjk = _fonts(size, bold)
    x, y = xy
    buf = ""
    for ch in s:
        if buf and _is_cjk(ch) != _is_cjk(buf[-1]):
            f = f_cjk if _is_cjk(buf[-1]) else f_lat
            d.text((x, y), buf, font=f, fill=fill)
            x += d.textlength(buf, font=f)
            buf = ""
        buf += ch
    if buf:
        f = f_cjk if _is_cjk(buf[-1]) else f_lat
        d.text((x, y), buf, font=f, fill=fill)
        x += d.textlength(buf, font=f)
    return x


def text_width_mixed(d: ImageDraw.ImageDraw, s, size, bold=False) -> float:
    f_lat, f_cjk = _fonts(size, bold)
    w = 0.0
    for ch in s:
        w += d.textlength(ch, font=f_cjk if _is_cjk(ch) else f_lat)
    return w


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)


def text(d: ImageDraw.ImageDraw, xy, s, f, fill=FG, anchor="la"):
    d.text(xy, s, font=f, fill=fill, anchor=anchor)


def center(d, y, s, f, fill=FG):
    d.text((W // 2, y), s, font=f, fill=fill, anchor="ma")


def rounded(d: ImageDraw.ImageDraw, box, r=12, fill=CARD, outline=BORDER, width=1):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


# ── 场景元素 ────────────────────────────────────────────────────────────────

def terminal_frame(lines, *, title="photo-s — zsh", typed_chars=None,
                   caret=True, pad=36, size=20):
    """画一个终端窗口；typed_chars 控制"正在输入"的字符数（画在最后一行之后）。"""
    img, d = canvas()
    x0, y0, x1, y1 = 140, 120, W - 140, H - 120
    rounded(d, (x0, y0, x1, y1), r=14, fill=TERM_BG, outline=BORDER)
    d.rounded_rectangle((x0, y0, x1, y0 + 46), radius=14, fill=(38, 42, 47))
    d.rectangle((x0, y0 + 32, x1, y0 + 46), fill=(38, 42, 47))
    for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        cx = x0 + 22 + i * 22
        d.ellipse((cx - 7, y0 + 16, cx + 7, y0 + 30), fill=c)
    text(d, ((x0 + x1) // 2, y0 + 14), title, font(MONO, 17), DIM, anchor="ma")

    y = y0 + 76
    lh = int(size * 1.62)
    for ln in lines:
        if ln.startswith("$ "):
            text_mixed(d, (x0 + pad, y), "$", size, GREEN)
            text_mixed(d, (x0 + pad + 22, y), ln[2:], size, FG, bold=True)
        elif ln.startswith("[ok]"):
            text_mixed(d, (x0 + pad, y), "✓", size, GREEN)
            text_mixed(d, (x0 + pad + 26, y), ln[4:], size, DIM)
        elif ln.startswith("[warn]"):
            text_mixed(d, (x0 + pad, y), "!", size, AMBER)
            text_mixed(d, (x0 + pad + 26, y), ln[6:], size, DIM)
        elif ln.startswith("[dim]"):
            text_mixed(d, (x0 + pad, y), ln[5:], size, DIM)
        elif ln.startswith("[green]"):
            text_mixed(d, (x0 + pad, y), ln[7:], size, GREEN)
        elif ln.startswith("[amber]"):
            text_mixed(d, (x0 + pad, y), ln[7:], size, AMBER)
        else:
            text_mixed(d, (x0 + pad, y), ln, size, FG)
        y += lh

    if typed_chars is not None:
        text_mixed(d, (x0 + pad, y), "$", size, GREEN)
        text_mixed(d, (x0 + pad + 22, y), typed_chars, size, FG, bold=True)
        if caret:
            tw = text_width_mixed(d, typed_chars, size, bold=True)
            d.rectangle((x0 + pad + 28 + tw, y + 3,
                         x0 + pad + 34 + tw, y + size + 5), fill=ACCENT)
    return img


def agent_frame(*, used, steps, typing=None, active_idx=None, plain=None):
    """模拟 MCP 客户端的对话：用户提问 → agent 逐个调用 PhotoS 工具。

    used  : 已显示的用户提问
    steps : 已完成的工具调用 [(工具名, 参数摘要, 结果, 状态)]
    typing: 正在"流式输出"的文本（None 表示不显示）
    """
    img, d = canvas()
    x0, y0, x1, y1 = 140, 120, W - 140, H - 120
    rounded(d, (x0, y0, x1, y1), r=14, fill=TERM_BG, outline=BORDER)
    d.rounded_rectangle((x0, y0, x1, y0 + 50), radius=14, fill=(38, 42, 47))
    d.rectangle((x0, y0 + 36, x1, y0 + 50), fill=(38, 42, 47))
    for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        cx = x0 + 22 + i * 22
        d.ellipse((cx - 7, y0 + 18, cx + 7, y0 + 32), fill=c)
    text(d, ((x0 + x1) // 2, y0 + 15),
         "AI agent  ←→  PhotoS MCP server（31 个工具）",
         font(CJK, 18), DIM, anchor="ma")

    # 用户气泡（右对齐）
    y = y0 + 76
    if used:
        f_u = font(CJK, 21)
        wl = int(d.textlength(used, font=f_u)) + 40
        bx1 = x1 - 40
        bx0 = bx1 - wl
        d.rounded_rectangle((bx0, y, bx1, y + 46), radius=12,
                            fill=(38, 70, 110), outline=(52, 92, 140))
        text(d, (bx0 + 20, y + 11), used, f_u, FG)
        y += 74

    # 工具调用卡
    for i, (name, args, result, ok) in enumerate(steps):
        by = y + i * 85
        col = GREEN if ok else AMBER
        rounded(d, (x0 + 40, by, x1 - 40, by + 76), r=10,
                fill=(24, 28, 33), outline=BORDER)
        d.rectangle((x0 + 40, by + 11, x0 + 44, by + 65), fill=col)
        text_mixed(d, (x0 + 66, by + 8), name, 20, ACCENT, bold=True)
        text_mixed(d, (x0 + 66, by + 35), args, 17, DIM)
        text_mixed(d, (x0 + 66, by + 55), result, 17, col)

    if typing is not None:
        ty = y + len(steps) * 85 + 16
        text_mixed(d, (x0 + 44, ty), typing, 20, FG)
        tw = text_width_mixed(d, typing, 20)
        d.rectangle((x0 + 48 + tw, ty + 2, x0 + 58 + tw, ty + 24), fill=ACCENT)
    return img


def screenshot_frame(path: Path, *, title: str, bullets, scale=0.62,
                     center_y=None, dim_bg=True):
    """把 GUI 截图放进一个"应用窗口"里，下方列要点。"""
    img, d = canvas()
    if dim_bg:
        d.rectangle((0, 0, W, H), fill=(12, 13, 15))
    shot = Image.open(path).convert("RGB")
    tw = int(shot.width * scale)
    th = int(shot.height * scale)
    shot = shot.resize((tw, th), Image.LANCZOS)
    x = (W - tw) // 2
    y = center_y if center_y is not None else (H - th) // 2 + 40
    d.rounded_rectangle((x - 3, y - 3, x + tw + 3, y + th + 3), radius=10,
                        fill=CARD, outline=BORDER)
    img.paste(shot, (x, y))

    text(d, (W // 2, y - 78), title, font(CJK_BOLD, 44), FG, anchor="ma")

    f_b = font(CJK, 30)
    by = y + th + 30
    total = sum(d.textlength(b, font=f_b) + 46 for b in bullets)
    bx = (W - total) // 2
    for b in bullets:
        d.ellipse((bx, by + 11, bx + 9, by + 20), fill=ACCENT)
        tw_ = d.textlength(b, font=f_b)
        text(d, (bx + 22, by), b, f_b, DIM)
        bx += tw_ + 46
    return img


def card_frame(*, kicker, title, subtitle=None, lines=None, accent=ACCENT,
               logo=True):
    img, d = canvas()
    for i in range(0, 260, 4):
        a = int(28 * (1 - i / 260))
        d.rectangle((0, i, W, i + 4), fill=(BG[0] + a, BG[1] + a, BG[2] + a))
    y = 300
    if logo:
        center(d, y, "PhotoS", font(CJK_BOLD, 132), FG)
        y += 190
    if kicker:
        center(d, y - 96, kicker, font(CJK, 34), accent)
    center(d, y, title, font(CJK_BOLD, 68), FG)
    if subtitle:
        center(d, y + 110, subtitle, font(CJK, 34), DIM)
    if lines:
        ly = y + 210
        for ln in lines:
            wl = text_width_mixed(d, ln, 28)
            text_mixed(d, ((W - wl) // 2, ly), ln, 28, DIM)
            ly += 48
    return img


# ── 音轨事件收集 ────────────────────────────────────────────────────────────
# 每个事件 = (绝对时间秒, 音效名)；在编码分段视频时按场景记录，串片时平移。
SFX: list = []


def mark(sfx: str, offset: float = 0.0) -> None:
    """在当前场景内记录一个音效事件（offset 为场景内偏移秒）。"""
    SFX.append((_scene_t + offset, sfx))


_scene_t = 0.0


# ── 场景定义 ────────────────────────────────────────────────────────────────

def hold(img: Image.Image, seconds: float):
    n = max(1, int(seconds * FPS))
    for _ in range(n):
        yield img


def pad_frames(gen, target: float | None):
    """把场景补/裁到目标时长：不够就重复末帧，超出就截断。

    有了它，场景时长完全由旁白决定，脚本里的固定秒数只是兜底。
    """
    if target is None:
        yield from gen
        return
    n_target = max(1, int(target * FPS))
    last = None
    n = 0
    for img in gen:
        if n >= n_target:
            return
        last = img
        yield img
        n += 1
    while n < n_target and last is not None:
        yield last
        n += 1


def type_command(base, cmd, after, *, pre, cps, tail):
    """先静止 pre 秒，再逐字符打出命令，最后逐行显示 after 并停留 tail 秒。"""
    t = 0.0
    for _ in range(int(pre * FPS)):
        yield terminal_frame(base, typed_chars="")
        t += 1 / FPS
    step = max(1, int(FPS / cps))
    for i in range(0, len(cmd) + 1):
        if i and i % 5 == 0:
            mark("tick", t)
        f = terminal_frame(base, typed_chars=cmd[:i])
        for _ in range(step):
            yield f
            t += 1 / FPS
    mark("enter", t)
    echo = base + ["$ " + cmd]
    per = max(1, int((tail / (len(after) + 1)) * FPS))
    for k in range(len(after) + 1):
        if k:
            mark("blip", t)
        img = terminal_frame(echo + after[:k])
        for _ in range(per):
            yield img
            t += 1 / FPS


def scene_title(dur=None):
    yield from pad_frames(hold(card_frame(
        kicker="批量照片处理工具箱",
        title="Lightroom 的批量自动化层",
        subtitle="也是给 AI agent 的照片管线",
        lines=["39 个 CLI 子命令 · 31 个 MCP 工具 · GUI + REST + Python 库"],
    ), 4.0), dur)


def scene_pain(dur=None):
    yield from pad_frames(hold(card_frame(
        kicker="问题",
        title="一次拍摄 = 800 张 RAW",
        subtitle="挑片、调色、导出、回写 LR —— 手工要一整天",
        lines=["· 逐张调色，风格难统一",
               "· 批量工具不懂 Lightroom",
               "· 让 AI 帮你修图，照片却要上传云端"],
        accent=AMBER, logo=False,
    ), 5.0), dur)


def scene_autopilot(dur=None):
    base = [
        "[dim]# 一条命令：规则修偏 → 质量闸门 → 自动分流",
        "[dim]# 全程本机执行，照片不上传",
        "",
    ]
    after = [
        "",
        "[green]✓ 4 张处理完成",
        "[ok]passed/  3 张（audit 通过）",
        "[warn]review/  1 张（DSC_0004 欠曝，转人工复核）",
        "[dim]轨迹: ap_out/autopilot.jsonl（逐张参数 + 判定）",
    ]
    yield from pad_frames(type_command(
        base, "photo-s autopilot ~/shoot -r --scan-existing --mode suggest",
        after, pre=1.2, cps=17, tail=8.0), dur)


def scene_agent_loop(dur=None):
    base = [
        "[dim]# 给 agent 的四步闭环：感知 → 建议 → 执行 → 验收",
        "",
    ]
    after = [
        "",
        "[amber]suggest: ev +0.42 · levels 31,215,1.0",
        "[dim]依据: mean luminance 0.373 → 目标 ~0.5",
        "[green]✓ 已套用并导出 · audit 通过（无过曝/欠曝）",
        "[dim]全程零模型、可解释、离线可用",
    ]
    yield from pad_frames(type_command(
        base, "photo-s suggest ~/shoot/raw.jpg --json",
        after, pre=1.2, cps=17, tail=8.0), dur)


# ── MCP 场景：agent 直接调工具操作照片 ──────────────────────────────────────

MCP_STEPS = [
    ("analyze", 'paths: ["~/shoot"]', "→ 324 张：过曝 12 · 欠曝 31 · 模糊 18", True),
    ("dedup", 'action: "scan"', "→ 发现 9 组重复，保留最清晰", True),
    ("select", 'keep_min: 4, dry_run: true', "→ 精选 87 · 淘汰 42 · 原地 195", True),
    ("process", 'ev: 0.42, levels: "31,215,1.0"', "→ 124 张已导出 out/", True),
    ("audit", 'blur_min: 0.05', "→ pass 96% · 5 张转人工复核", True),
    ("xmp-export", '--embed --rating', "→ 调整写回 XMP，LR 可直接续修", True),
]


def scene_mcp(dur=None):
    """AI agent 通过 MCP 直接操作照片：逐个工具调用 + 结果。"""
    q = "帮我把这次拍摄整理一下：挑出能用的，统一调色，导出。"
    t = 0.0
    # 1) 用户提问逐字打出
    for i in range(1, len(q) + 1):
        if i % 3 == 0:
            mark("tick", t)
        img = agent_frame(used=q[:i], steps=[])
        for _ in range(2):
            yield img
            t += 1 / FPS
    for _ in range(12):
        yield agent_frame(used=q, steps=[], typing="")
        t += 1 / FPS
    # 2) 逐个工具调用（每次工具结果出现时给一个 blip）
    typing_text = "收到。先分析这批照片…"
    for i in range(1, len(typing_text) + 1):
        img = agent_frame(used=q, steps=[], typing=typing_text[:i])
        for _ in range(2):
            yield img
            t += 1 / FPS
    for k in range(1, len(MCP_STEPS) + 1):
        img = agent_frame(used=q, steps=MCP_STEPS[:k])
        mark("blip", t)
        for _ in range(int(1.5 * FPS)):
            yield img
            t += 1 / FPS
    # 3) 收尾结论
    done = "全部完成：124 张已导出，调整已写回 XMP —— 在 Lightroom 里继续微调即可。"
    for i in range(1, len(done) + 1):
        if i % 4 == 0:
            mark("tick", t)
        img = agent_frame(used=q, steps=MCP_STEPS, typing=done[:i])
        for _ in range(2):
            yield img
            t += 1 / FPS
    mark("chime", t)
    for _ in range(int(2.2 * FPS)):
        yield agent_frame(used=q, steps=MCP_STEPS, typing=done)
        t += 1 / FPS
    if dur is not None:  # 旁白更长时，定格在收尾画面
        final = agent_frame(used=q, steps=MCP_STEPS, typing=done)
        while t < dur:
            yield final
            t += 1 / FPS


def scene_develop(dur=None):
    yield from pad_frames(hold(screenshot_frame(
        SHOTS / "03-develop-adjusted.png",
        title="Develop — 真实管线实时预览",
        bullets=["滑杆即时驱动真管线", "常驻直方图与曝光读数",
                 "AI 调色 / 蒙版 / XMP 往返"],
        scale=0.60), 6.0), dur)


def scene_export(dur=None):
    yield from pad_frames(hold(screenshot_frame(
        SHOTS / "05-export.png",
        title="Export — 队列 · 配方 · 随输出写 XMP",
        bullets=["勾选照片与体积合计", "导出配方复用", "LR 打开即可续修"],
        scale=0.60), 6.0), dur)


def scene_lr_roundtrip(dur=None):
    yield from pad_frames(hold(card_frame(
        kicker="v2.5 起",
        title="修完写回 XMP，Lightroom 里继续修",
        subtitle="经 LR 逐值实测对齐：全局调色 / 线性蒙版 / 径向蒙版 / 评分关键词",
        lines=["photo-s xmp-export ~/shoot -r --embed    # JPEG 直写内嵌 XMP",
               "photo-s batch '*.ARW' -o out/ --write-xmp  # 批量附带 sidecar"],
        logo=False), 5.5), dur)


def scene_model(dur=None):
    yield from pad_frames(hold(card_frame(
        kicker="数据闭环",
        title="用你自己的修图记录，训你自己的调色模型",
        subtitle="lr-scan 采集 → lr-merge 汇总 → lr-train 训练 → auto-tone 推理",
        lines=["1295 条 Lightroom 修改记录",
               "SigLIP 主模型 PSNR 32.21 · 权重 4.6MB",
               "全在本机推理，修图数据永不出本机"],
        accent=GREEN, logo=False), 7.0), dur)


def scene_agents(dur=None):
    yield from pad_frames(hold(card_frame(
        kicker="原生 agent 接口",
        title="一个契约，四个入口",
        subtitle="CLI --json · REST API · MCP server · Python 库",
        lines=["schema_version: 1 —— 加性演进，升级永不破坏调用方",
               "claude mcp add photo-s -- photo-s mcp",
               "31 个核心工具，装插件自动扩展"],
        logo=False), 5.5), dur)


def scene_outro(dur=None):
    yield from pad_frames(hold(card_frame(
        kicker="MIT 开源 · 本机推理 · 无云端",
        title="pip install photo-s-tools",
        subtitle="github.com/Dongwu259/photo_s",
        lines=["★ Star 是对独立开发最大的支持",
               "docs/ROADMAP.md 公开全部路线"],
        accent=GREEN), 5.0), dur)


SCENES = [
    ("title", scene_title, "PhotoS — Lightroom 的批量自动化层"),
    ("pain", scene_pain, "一次拍摄 800 张，手工要一整天"),
    ("autopilot", scene_autopilot,
     "photo-s autopilot：修偏 → 质检 → 自动分流，全在本机"),
    ("agent-loop", scene_agent_loop,
     "agent 闭环：analyze → suggest → process → audit"),
    ("mcp", scene_mcp, "AI agent 通过 MCP 直接操作照片（31 个工具）"),
    ("develop", scene_develop, "Develop：滑杆驱动真实管线，实时预览"),
    ("export", scene_export, "Export：队列 + 配方，并可随输出写 XMP"),
    ("lrxmp", scene_lr_roundtrip, "写回 XMP，回到 Lightroom 继续修"),
    ("model", scene_model, "用你自己的 Lightroom 数据训专属调色模型"),
    ("agents", scene_agents, "CLI / REST / MCP / Python 库，同一套 JSON 契约"),
    ("outro", scene_outro, "pip install photo-s-tools · github.com/Dongwu259/photo_s"),
]


# ── 音频 ────────────────────────────────────────────────────────────────────
# 配乐床：ffmpeg 正弦叠加成氛围 pad（原创合成，无版权问题）。
# 旁白：本机 Kokoro TTS（MCP 服务），音色 zm_058。
PAD_FREQS = [110.0, 164.81, 220.0, 261.63, 329.63, 440.0]
PAD_GAIN = 0.45          # 有旁白时压低，给说话留空间
VOICE = "zm_058"
VO_DIR = Path(tempfile.gettempdir()) / "photos_vo"

# 每个场景的旁白（也是字幕文本）与"旁白之后停留"的秒数
NARRATION: dict[str, tuple[str, float]] = {
    "title": ("拍完一场，几百张照片堆在硬盘里。挑片、调色、导出、"
              "再导回 Lightroom，一整天就这么没了。", 0.7),
    "pain": ("通用的批量工具只会压缩和转格式，它们不懂 Lightroom，"
             "也不懂你的风格。", 0.7),
    "autopilot": ("PhotoS 把这些变成一条命令。自动修偏、质量质检，"
                  "再按结果分流到通过和待复核，过程全在本机。", 0.8),
    "agent-loop": ("对 AI agent 来说，它是一个完整的闭环：先分析照片，"
                   "给出可解释的参数建议，执行，再验收。", 0.8),
    "mcp": ("接入 MCP 之后，你只要说一句话。修图 agent 会自己调用三十一个工具，"
            "分析、去重、选片、调色、导出，最后把调整写回 Lightroom。", 1.0),
    "develop": ("当然也有一套给人用的图形界面。滑杆驱动真实管线实时预览，"
                "直方图常驻，调色、蒙版、写回 XMP 都在这里。", 0.7),
    "export": ("导出队列支持命名配方，可以同时把调色参数写成 XMP，"
               "交付给客户或回到 Lightroom 继续修。", 0.7),
    "lrxmp": ("这条往返链路是拿 Lightroom 的导出结果逐项对齐过的："
              "全局调色、线性蒙版、径向蒙版、评分和关键词，都能原样读回。", 0.7),
    "model": ("更有意思的是数据闭环。它能读取你自己的 Lightroom 修图记录，"
              "在本机训练一个只属于你的调色模型，权重只有四点六兆。", 0.8),
    "agents": ("命令行、REST、MCP，还有 Python 库，共用同一套带版本号的 JSON 契约，"
               "升级不会破坏调用方。", 0.7),
    "outro": ("代码 MIT 开源，模型在本地跑，照片和修图记录永远不出你的机器。"
              "装一条命令就能开始。", 1.0),
}


def synth_narration() -> dict[str, dict]:
    """为每个场景合成旁白（带缓存），返回 {scene: {path, duration, text}}。"""
    VO_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = VO_DIR / "voiceover.json"
    if meta_path.exists():
        cached = json.loads(meta_path.read_text(encoding="utf-8"))
        if all(k in cached for k in NARRATION):
            print(f"[tts] 复用已合成旁白（{VO_DIR}）")
            return cached
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from tts_mcp_client import connect, call
    except Exception as e:  # noqa: BLE001
        print(f"[tts] 无法加载 MCP 客户端: {e}", file=sys.stderr)
        return {}
    sid = connect()
    meta: dict[str, dict] = {}
    for scene, (text, _tail) in NARRATION.items():
        out = VO_DIR / f"{scene}.wav"
        try:
            res = call(sid, "tts_generate",
                       {"text": text, "voice": VOICE, "fmt": "wav",
                        "out_path": str(out)})
            sc = res.get("structuredContent") or json.loads(
                res["content"][0]["text"])
            meta[scene] = {"path": sc.get("file", str(out)),
                           "duration": float(sc.get("duration") or 0.0),
                           "text": text}
            print(f"[tts] {scene:11} {meta[scene]['duration']:5.2f}s")
        except Exception as e:  # noqa: BLE001
            print(f"[tts] {scene} 合成失败: {e}", file=sys.stderr)
    if meta:
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    return meta


def shutil_which(name: str):
    from shutil import which
    return which(name)


def build_audio(total: float, out_wav: Path, narr: list[tuple[float, Path]],
                sfx_gain: float = 0.5) -> Path | None:
    """混出音轨：旁白（主角）+ 配乐床 + 音效。

    narr: [(场景起点秒, 旁白 wav 路径)]——旁白在场景开始后 0.9s 出现。
    """
    if not shutil_which("ffmpeg"):
        return None
    args: list[str] = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    n_pad = len(PAD_FREQS)
    for f in PAD_FREQS:
        args += ["-f", "lavfi", "-t", f"{total:.3f}", "-i",
                 f"sine=frequency={f}:sample_rate=48000"]
    sound_inputs = [SYS_SOUNDS / f"{n}.aiff"
                    for n in ("Tink", "Pop", "Glass")]
    sound_inputs = [p for p in sound_inputs if p.exists()]
    for p in sound_inputs:
        args += ["-i", str(p)]
    base_sfx = n_pad + len(sound_inputs)
    narr = [(t, Path(p)) for t, p in narr if Path(p).exists()]
    for _, p in narr:
        args += ["-i", str(p)]

    fc: list[str] = []
    pad_in = "".join(f"[{i}:a]" for i in range(n_pad))
    fc.append(f"{pad_in}amix=inputs={n_pad}:normalize=0,"
              f"volume={PAD_GAIN},tremolo=f=0.12:d=0.40,lowpass=f=2000,"
              f"afade=t=in:st=0:d=2.5,"
              f"afade=t=out:st={max(0.0, total - 3.0):.2f}:d=3.0[pad]")

    idx = {p.stem.lower(): n_pad + i for i, p in enumerate(sound_inputs)}
    sfx_labels = []
    for i, (t, kind) in enumerate([(t, s) for t, s in SFX
                                   if s in ("tick", "enter", "blip", "chime")]):
        src = {"tick": "tink", "enter": "pop",
               "blip": "tink", "chime": "glass"}[kind]
        if src not in idx:
            continue
        vol = {"tick": 0.14, "enter": 0.5, "blip": 0.38,
               "chime": 0.7}[kind] * sfx_gain
        ms = int(max(0.0, t) * 1000)
        lbl = f"s{i}"
        fc.append(f"[{idx[src]}:a]aformat=sample_rates=48000:"
                  f"channel_layouts=stereo,volume={vol:.3f},highpass=f=400,"
                  f"adelay={ms}|{ms}[{lbl}]")
        sfx_labels.append(lbl)
    if sfx_labels:
        fc.append("".join(f"[{l}]" for l in sfx_labels)
                  + f"amix=inputs={len(sfx_labels)}:normalize=0[sfx]")

    # 旁白：0.9s 后进画，标准化响度，轻微高通去闷响
    vo_labels = []
    for i, (t, _p) in enumerate(narr):
        lbl = f"v{i}"
        ms = int((t + 0.9) * 1000)
        fc.append(f"[{base_sfx + i}:a]aformat=sample_rates=48000:"
                  f"channel_layouts=stereo,highpass=f=90,"
                  f"dynaudnorm=f=200:g=4:p=0.9,volume=1.0,"
                  f"adelay={ms}|{ms}[{lbl}]")
        vo_labels.append(lbl)

    layers = ["[pad]"]
    if sfx_labels:
        layers.append("[sfx]")
    if vo_labels:
        fc.append("".join(f"[{l}]" for l in vo_labels)
                  + f"amix=inputs={len(vo_labels)}:normalize=0[vo]")
        layers.append("[vo]")
    fc.append("".join(layers)
              + f"amix=inputs={len(layers)}:normalize=0,"
                "alimiter=limit=0.85,volume=0.92[out]")

    args += ["-filter_complex", ";".join(fc), "-map", "[out]",
             "-ar", "48000", "-ac", "2", str(out_wav)]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"!! 音频合成失败: {r.stderr.strip()[:500]}", file=sys.stderr)
        return None
    return out_wav


def srt_time(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")


def main() -> int:
    global _scene_t
    audio_only = "--audio-only" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    frames_dir = OUT / "frames"
    frames_dir.mkdir(exist_ok=True)

    # 0) 旁白（本机 TTS；不可用则退化为纯配乐版）
    vo = synth_narration()
    timeline_path = OUT / "timeline.json"

    if audio_only and timeline_path.exists():
        tl = json.loads(timeline_path.read_text(encoding="utf-8"))
        durs = tl["durs"]
        srt = [tuple(x) for x in tl["srt"]]
        vo_tracks = [(t, Path(p)) for t, p in tl["vo"]]
        SFX[:] = [(t, k) for t, k in tl["sfx"]]
        total = sum(durs) - FADE * (len(durs) - 1)
        final = OUT / "photos-demo.mp4"
        wav = build_audio(total, OUT / ".audio.wav", vo_tracks)
        if wav is None:
            print("!! 音频重混失败", file=sys.stderr)
            return 1
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(final), "-i", str(wav),
             "-map", "0:v", "-map", "1:a", "-c:v", "copy",
             "-c:a", "aac", "-b:a", "192k", "-shortest",
             "-movflags", "+faststart", str(final.with_suffix(".tmp.mp4"))],
            check=True)
        final.with_suffix(".tmp.mp4").replace(final)
        wav.unlink(missing_ok=True)
        print(f"[video] 仅重混音频完成: {final} "
              f"({final.stat().st_size / 1e6:.1f} MB, {total:.1f}s)")
        return 0

    # 1) 逐场景渲染；有旁白时场景时长 = 旁白时长 + 停留，并记录旁白起点
    clips, durs, srt, vo_tracks = [], [], [], []
    t_cursor = 0.0
    for i, (name, fn, caption) in enumerate(SCENES, 1):
        clip = OUT / f"{i:02d}-{name}.mp4"
        _scene_t = t_cursor
        if i > 1:  # 场景切换的提示音
            mark("chime", 0.25)
        info = vo.get(name)
        text, tail_pad = NARRATION.get(name, ("", 0.0))
        scene_start = t_cursor
        if info:
            limit = info["duration"] + 0.9 + tail_pad
            srt.append((scene_start, scene_start + info["duration"] + 0.9,
                        text))
            vo_tracks.append((scene_start, Path(info["path"])))
        else:
            limit = None
            srt.append((scene_start, scene_start + 5.0, caption))
        gen = fn(limit) if limit is not None else fn()

        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", str(clip),
        ]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        n_frames, first = 0, None
        for img in gen:
            if first is None:
                first = img.copy()
            p.stdin.write(img.tobytes())
            n_frames += 1
        p.stdin.close()
        if p.wait() != 0:
            print(f"!! ffmpeg 失败: {name}", file=sys.stderr)
            return 1
        dur = n_frames / FPS
        durs.append(dur)
        t_cursor += dur
        clips.append(clip)
        if first is not None:
            first.save(frames_dir / f"{i:02d}-{name}.png")
        print(f"[video] {i:02d}-{name}: {dur:5.1f}s ({n_frames} 帧)")

    # 2) 视频流串片（xfade）
    silent = OUT / ".silent.mp4"
    inputs = []
    for c in clips:
        inputs += ["-i", str(c)]
    fc, prev, acc = [], "0:v", durs[0]
    for k in range(1, len(clips)):
        lbl = f"v{k}"
        fc.append(f"[{prev}][{k}:v]xfade=transition=fade:"
                  f"duration={FADE}:offset={acc - FADE:.3f}[{lbl}]")
        prev = lbl
        acc = acc - FADE + durs[k]
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
         "-filter_complex", ";".join(fc), "-map", f"[{prev}]",
         "-c:v", "libx264", "-preset", "slow", "-crf", "18",
         "-pix_fmt", "yuv420p", str(silent)], check=True)

    total = sum(durs) - FADE * (len(durs) - 1)

    # 落盘时间轴（供 --audio-only 重混，避免重渲视频）
    timeline_path.write_text(json.dumps({
        "durs": durs,
        "srt": [list(x) for x in srt],
        "vo": [[t, str(p)] for t, p in vo_tracks],
        "sfx": [[t, k] for t, k in SFX],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    # 3) 音效事件按 xfade 重叠前移；旁白起点同样前移
    def shift(t: float) -> float:
        a, k = 0.0, 0
        for d in durs:
            if t < a + d:
                break
            a += d
            k += 1
        return max(0.0, t - FADE * k)

    SFX[:] = sorted((shift(t), sfx) for t, sfx in SFX)
    vo_tracks = [(shift(t), p) for t, p in vo_tracks]
    wav = build_audio(total, OUT / ".audio.wav", vo_tracks)

    # 4) 合流
    final = OUT / "photos-demo.mp4"
    if wav is not None:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(silent), "-i", str(wav),
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-shortest", "-movflags", "+faststart", str(final)], check=True)
        print(f"[video] 音轨：旁白 {len(vo_tracks)} 段 + "
              f"{len(SFX)} 个音效 + 合成配乐床")
    else:
        silent.replace(final)
        print("[video] 警告：未生成音轨", file=sys.stderr)
    silent.unlink(missing_ok=True)
    if wav is not None:
        wav.unlink(missing_ok=True)

    # 5) 字幕（旁白文本；时间轴扣 xfade 重叠）
    srt_path = OUT / "photos-demo.srt"
    with srt_path.open("w", encoding="utf-8") as f:
        for i, (a, b, cap) in enumerate(srt, 1):
            sh = FADE * (i - 1)
            f.write(f"{i}\n{srt_time(max(0.0, a - sh))} --> "
                    f"{srt_time(max(0.0, b - sh))}\n{cap}\n\n")

    # 6) 封面
    cover = card_frame(
        kicker="批量照片处理工具箱",
        title="Lightroom 的批量自动化层",
        subtitle="也是给 AI agent 的照片管线",
        lines=["39 个 CLI 子命令 · 31 个 MCP 工具"],
    )
    cover.save(OUT / "photos-demo-cover.png")

    # 7) 清理分段
    for c in clips:
        c.unlink(missing_ok=True)

    print(f"[video] 完成: {final} ({final.stat().st_size / 1e6:.1f} MB, "
          f"{total:.1f}s) + {srt_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
