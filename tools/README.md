# tools/ — 训练与演示脚本

这里放**不进 wheel** 的一次性脚本：模型训练、以及演示物料生成。

## 训练

| 脚本 | 用途 |
|---|---|
| `train_tone_torch.py` | CLIP/SigLIP 冻结塔 + MLP 回归 9 项调色参数 → npz（配 `photo-s lr-predict`） |
| `train_verifier.py` | 美学回归头（SigLIP + 星级评分），供 `photo-s audit --aesthetic` |
| `prep_local_labels.py` | 局部调整训练标签准备 |
| `llama_factory_lora.yaml` | Qwen3-VL LoRA 训练模板（LLaMA-Factory） |

训练数据流程见 [`docs/TRAINING.md`](../docs/TRAINING.md)。

## 演示物料

两个脚本把 README / 社媒用的截图与视频**可复现地**生成出来
（不靠手动录屏，中文排版可控，换台机器照样跑）。

### 1. GUI 截图

```bash
# 素材目录默认 /tmp/ps_demo/photos（放几张你自己的 JPEG 就行）
python3 tools/make_screenshots.py            # → demo/screenshots/*.png
```

以脚本方式驱动 GUI 到 Library / Develop / Export / Tools 四个状态，
再用 `screencapture` **按窗口 ID** 截图（不受其它窗口遮挡）。
注意：macOS 下必须先 `-topmost` 把窗口提到最前，否则 Canvas 内容可能
抓到未合成的空 backing store（截图整片空白）。

要求：macOS（用了 `screencapture` 与 CoreGraphics 窗口枚举）。

### 2. 演示视频

```bash
python3 tools/make_demo_video.py              # 全量渲染 → demo/video/
python3 tools/make_demo_video.py --audio-only # 只重混音轨（3 秒，调音量/换 BGM 用）
```

产出：

| 文件 | 说明 |
|---|---|
| `photos-demo.mp4` | 正片，1920×1080 / 30fps / **128s**，含 TTS 旁白 + 配乐 + 音效 |
| `photos-demo.srt` | 字幕（**就是旁白原文**，与语音逐句对齐） |
| `photos-demo-cover.png` | 封面 |
| `frames/*.png` | 各场景首帧（可直接当社媒配图） |
| `timeline.json` | 场景时长/旁白/音效事件时间轴（供 `--audio-only` 复用） |

逐帧用 PIL 渲染后 raw RGB 管道给 ffmpeg，场景之间用 `xfade` 交叉淡入。
终端画面是真命令、真输出（见脚本里的 `SCENES`），中英混排用
Menlo + Hiragino 分段绘制，避免等宽字体缺中文字形变豆腐块。

**音轨**由三层混成（`build_audio()`）：

1. **旁白**：调用本机 Kokoro TTS 的 MCP 服务（见下）逐场景合成，`zm_058` 男声。
   场景时长由旁白实测时长决定（`旁白 + 0.9s 入画 + 停留`），所以音画天然对齐，
   字幕文本就是旁白文本。
2. **配乐床**：ffmpeg 正弦叠加合成的氛围 pad（原创，无版权问题），有旁白时压到 0.55。
3. **音效**：macOS 系统音效（`/System/Library/Sounds/` 的 Tink / Pop / Glass），
   打字是轻点击、工具返回是 blip、场景切换是 chime。

音效事件在渲染每个场景时用 `mark(音效名, offset)` 记录，串片时按 `xfade`
重叠量自动前移。换 BGM：把 `build_audio()` 里的 `[pad]` 链换成 `-i your.mp3`。

#### 旁白（本机 TTS over MCP）

```bash
# 服务地址默认 http://127.0.0.1:8740/mcp，可用 PHOTOS_TTS_URL 覆盖
curl -s http://127.0.0.1:8740/mcp ...        # 或在 tools/make_demo_video.py 里直接跑
python3 tools/make_demo_video.py             # 自动合成旁白（缓存在 /tmp/photos_vo/）
```

- 旁白文案与停留时长写在脚本的 `NARRATION` 字典里（**改文案只改这里**）。
- 音色改 `VOICE = "zm_058"`；可用音色用
  `python3 tools/tts_mcp_client.py call tts_list_voices '{}'` 查询。
- 合成结果缓存在 `/tmp/photos_vo/`，删掉该目录即可重新合成。
- **TTS 服务不可用时自动降级**：无旁白，场景回落到固定时长，仍有配乐与音效。
- `tools/tts_mcp_client.py` 是个零依赖的极简 MCP streamable-HTTP 客户端
  （`list` / `call` 两个子命令），也顺便当"PhotoS 之外怎么调 MCP"的例子。

依赖：`Pillow` + `ffmpeg`（PATH 内）；旁白需要本机 TTS 服务（可选）。

### 素材与隐私

`demo/assets/`、`demo/screenshots/`、`demo/video/` 都在 `.gitignore` 里——
演示用的是真实照片，**不进公开仓库**。要对外发物料，请自行确认照片可用。
配套的发布文案（V2EX / X / 小红书 / B 站 / HN / Reddit）见
[`demo/PROMO.md`](../demo/PROMO.md)。
