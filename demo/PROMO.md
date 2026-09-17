# PhotoS 宣传包 — 发布节奏与分平台文案

> 配套物料：`demo/video/photos-demo.mp4`（128 秒正片，含 TTS 中文旁白）、`photos-demo.srt`（字幕）、
> `photos-demo-cover.png`（封面）、`demo/screenshots/*.png`（5 张功能截图）。
> 截图与视频按平台重新裁过再发：横版 16:9 给 B 站/YouTube/X，
> 竖版 9:16（1080×1920）给小红书/抖音/视频号。

---

## 0. 一句话定位（所有平台的锚）

**中文**：PhotoS —— Lightroom 的批量自动化层，也是给 AI agent 的照片管线。
本地推理、不传云端；还能用你自己的 Lightroom 修图记录训出专属调色模型。

**English**: PhotoS — batch automation layer for Lightroom, and a photo pipeline
built for AI agents. Local-only inference. Train a personal color model from
your own Lightroom edit history.

**不要用的表述**（会把项目拉进红海比价）：
❌「又一个图片批量处理工具」 ❌「在线修图/一键美化」 ❌「免费 Lightroom 替代品」

---

## 1. 发布顺序（重要：先冷启动，再冲量）

| 顺序 | 平台 | 为什么这个顺序 | 时机 |
|---|---|---|---|
| 1 | 即刻 / X / 朋友圈 | 小圈子试水，收集第一轮反馈与 bug | 视频做完当天 |
| 2 | V2EX（`/go/create` 或分享创造） | 中文技术社区最容易拿到第一批真实用户，会挑刺也会给建议 | 次日 |
| 3 | 掘金 / 少数派 | 需要一篇有信息量的文章；把 V2EX 的质疑补进文章 | +1~3 天 |
| 4 | Show HN | 英文技术圈；必须带可跑通的一行命令和英文 README | +3~5 天 |
| 5 | r/Lightroom、r/photography、r/postprocessing | **摄影师**，不是开发者——文案要全部换成效果语言 | +5~7 天 |
| 6 | 小红书 / B 站 / 抖音 | 面向摄影爱好者，靠画面和 before/after，不講技术 | 持续 |
| 7 | Product Hunt | 需要英文落地页 + 更好看的素材后再上 | 2~4 周 |
| 8 | ModelScope / 知乎 / 公众号 | 长文沉淀，把「数据闭环」讲透 | 持续 |

> 铁律：**每个平台发完 24 小时内必须回复每一条评论**。
> 0 star 项目的转折点从来不是功能，而是"作者在认真回我"。

---

## 2. V2EX 文案（首发主贴）

**标题（三选一，A/B 测）**
1. `[分享创造] 我做了一个 Lightroom 批量自动化工具，还顺手用自己 1295 条修图记录训了个调色模型`
2. `[分享创造] 用 AI agent 批量修图：本地推理 + 写完 XMP 能回 Lightroom 继续改`
3. `[分享创造] 一个人写了 3.5 万行，做了个给 AI agent 用的照片处理管线`

**正文**

```
先放链接和一行命令：
  https://github.com/Dongwu259/photo_s
  pip install photo-s-tools

做这个的起因很具体：我每次拍完几百张 RAW，挑片、修色、导出、回写 Lightroom
这一套至少要一整天。市面上的批量工具要么只会压缩转格式，要么就是云端一键
美化——照片要传上去，我不能接受。

所以 PhotoS 是两个东西叠在一起：

1) Lightroom 的批量自动化层
   - 39 个 CLI 子命令：批量 RAW→JPEG、按目标体积压缩、选片分拣、去重、
     联系表、HDR 合并、抠图、水印、EXIF 批量打标……
   - 关键点：v2.5 起支持 XMP 双向互通。修完能把调整写回 .xmp / 内嵌进 JPEG，
     在 Lightroom 里打开原图就能继续改（这一块是我拿自己的 LR 导出结果逐值
     对齐过的，蒙版、径向渐变、评分关键词都能往返）。
   - autopilot 无人值守：监视目录 → 规则修偏 → 质量闸门 → 自动分流到
     passed/ review/，并留一份 JSONL 轨迹。

2) 给 AI agent 的照片管线
   - MCP server 31 个工具（Claude Desktop / Claude Code 直接挂）
   - REST API（异步任务 + SSE 进度）、CLI --json、Python 库直调
   - 所有 JSON 输出带 schema_version，只做加性演进，升级不破坏调用方
   - 有现成的 SKILL.md，cp 一下就能用

还有一个我自己最满意的部分——数据闭环：
   photo-s lr-scan    # 扫描你的 Lightroom 目录/XMP，导出「修图记录 + 原图」
   photo-s lr-merge   # 多台机器汇总
   photo-s lr-train   # 用你自己的修图历史训调色模型
   photo-s lr-predict # 新照片 → 9 项 Lightroom 参数

我在 1295 条自己的 LR 修改记录上训了 SigLIP+MLP，PSNR 32.21。模型只有 4.6MB，
全在本机推理，你的照片和修图记录不会离开你的电脑。

工程情况：3.5 万行 Python，1490 个测试全绿，CI 覆盖 Linux 3.12/Windows 真实 Tk，
MIT 许可（模型权重非商用，商用可授权），中英双语 CLI/GUI。

想听的意见：
- 摄影师朋友：XMP 往返和 autopilot 分流这两个场景，对你们的实际工作流有用吗？
- 搞 agent 的朋友：MCP 工具集里还缺什么你们会真的用的能力？
- 有人愿意贡献自己的修图数据一起来训模型吗（可以只在本机训，不上传）？

有任何跑不通的地方直接回帖，我现场修。
```

**首评（自己占一楼，放截图）**
```
补几张图：Develop 实时预览 / Export 队列 / autopilot 分流结果
（见上方图片）
```

---

## 3. X / Twitter 文案

**主推文（英文，配视频）**
```
I built PhotoS: a batch automation layer for Lightroom that's also a photo
pipeline for AI agents.

• 39 CLI commands, 31 MCP tools, GUI + REST + Python
• Writes real XMP back — open the RAW in Lightroom and keep editing
• Train a personal color model from YOUR Lightroom edit history
• 100% local inference. Photos never leave the machine

pip install photo-s-tools
github.com/Dongwu259/photo_s
```

**中文版（配视频）**
```
给摄影师：Lightroom 的批量自动化层（修完写回 XMP，LR 里继续改）
给 agent：31 个 MCP 工具的照片管线（CLI/REST/Python 同一套 JSON 契约）
给自己：用你的 Lightroom 修图记录训一个专属调色模型，4.6MB，本机推理

pip install photo-s-tools
github.com/Dongwu259/photo_s
```

**跟进推文（发主推后 12~24 小时，拆技术点，每条独立成帖）**
1. 「为什么我坚持不做云端」：照片是私人数据，本地推理是产品原则不是省钱。
2. 「XMP 往返有多难」：LR 的蒙版结构没文档，我是拿 LR 导出结果逐值对齐的；
   附一张 Lr 里看到 PhotoS 调整的截图。
3. 「用自己 1295 条修图记录训模型」：附 lr-scan → lr-train → lr-predict 终端截图。
4. 「31 个 MCP 工具长什么样」：附 --list-tools 的一屏输出。

---

## 4. 小红书 / 抖音（摄影师向，不要出现技术名词）

**标题**
```
我把「修图一整天」压成了 10 分钟｜摄影师的批量修图工作流
```

**正文**
```
拍完 800 张 RAW，最痛苦的不是拍，是回到电脑前那一整套：
挑片 → 调色 → 导出 → 再导回 Lightroom。

我做了个工具，现在是这样：
1️⃣ 整个文件夹丢进去，自动挑出曝光/清晰度有问题的，好的坏的自动分文件夹
2️⃣ 自动按你的风格修一遍（可以学你自己在 Lightroom 里怎么修的）
3️⃣ 导出成片，同时把调整写回 Lightroom —— 打开原图，参数全在，想改继续改

重点：全程在你自己的电脑上跑，照片不上传任何云端。

支持 macOS / Windows / Linux，命令行一条就能装：
pip install photo-s-tools

开源免费（个人使用），GitHub 搜 PhotoS 就行，或者评论我发你链接 👇
```

**配图顺序**：封面（before/after 对比大字）→ Develop 截图 → Export 截图 →
autopilot 分流结果 → 「照片不上传云端」示意图。
**话题**：#摄影 #修图 #Lightroom #摄影师 #后期修图 #批量修图

---

## 5. B 站 / YouTube

**标题**
```
【开源】用 AI agent 批量修图：Lightroom 数据闭环 + 本机推理（PhotoS 全流程演示）
```

**简介**
```
项目：https://github.com/Dongwu259/photo_s
安装：pip install photo-s-tools

00:00 开场：一次拍摄 800 张，手工要一整天
00:10 通用批量工具的问题
00:18 autopilot：一条命令跑完修偏 → 质检 → 分流
00:29 agent 闭环：analyze → suggest → process → audit
00:39 MCP：让 AI agent 直接操作照片（31 个工具）
00:57 GUI：Develop 实时预览
01:10 Export 队列与配方
01:21 写回 XMP：回 Lightroom 继续修
01:35 用自己的修图记录训调色模型
01:48 四个入口同一套 JSON 契约
01:59 安装与结尾```

---

## 6. Show HN

**Title**
```
Show HN: PhotoS – Batch photo pipeline for AI agents, with Lightroom round-trip
```

**Body**
```
PhotoS started as a tool to stop losing a full day to post-processing a shoot.
It grew into two things:

1. A batch automation layer for Lightroom. The part I'm most confident about is
   the XMP round-trip: PhotoS can write its adjustments (global tone, linear and
   radial masks, ratings, keywords) into a .xmp sidecar or embed it directly into
   JPEGs, so Lightroom opens the original with everything editable. I aligned it
   value-by-value against real Lightroom exports, including the undocumented mask
   XML structure.

2. A photo pipeline built for agents: 31 MCP tools, a REST API with async jobs
   and SSE progress, a --json CLI, and a Python API. Every JSON output carries a
   schema_version and only evolves additively.

There's also a data loop I care about: lr-scan extracts your Lightroom edit
history into training records, and lr-train fits a color model on it. On my
1,295 records the SigLIP+MLP head gets PSNR 32.21. It's 4.6MB and runs locally —
the point is that photos and edit history never leave the machine.

3.5k lines... sorry, 35k lines of Python, 1,490 tests passing, CI on Linux and
real-Tk Windows. MIT for code.

pip install photo-s-tools

Happy to answer anything about the XMP reverse-engineering, the agent contract
design, or the (still modest) model quality.
```

> HN 注意：**不要在正文里请求 upvote**；发完留在评论区 3 小时以上认真答技术问题，
> 这是 HN 上唯一真正有效的推广方式。

---

## 7. r/Lightroom + r/photography

**Title（r/Lightroom）**
```
I built an open-source batch tool that writes its edits back into Lightroom (XMP round-trip, tested against LR)
```

**Body**
```
Full disclosure: I'm the author.

The problem I kept hitting: batch tools can resize and convert, but nothing lets
me automate a shoot and then keep working in Lightroom. So PhotoS writes its
adjustments to .xmp sidecars (or embeds XMP for JPEG), and Lightroom opens the
original with the adjustments intact — global tone, linear/radial masks, ratings,
and keywords all survive the round-trip.

What it does that might be useful here:
- Autopilot: point it at a folder, it flags under/over-exposed and soft frames,
  applies conservative corrections, then sorts into passed/ and review/ so you
  only open the ones that need a human.
- Batch RAW -> JPEG with demosaic choice, 16-bit TIFF, chroma subsampling.
- Culling by exposure/sharpness, burst best-pick, duplicates, contact sheets,
  watermarking, HTML galleries.

Everything runs locally. No cloud, no account.

It also can learn your style: it reads your Lightroom history and fits a small
model that predicts 9 tone parameters for a new photo. On my own 1,295 edits it's
decent, not magic — I'd genuinely like feedback on whether that's useful to
anyone but me.

pip install photo-s-tools (macOS/Windows/Linux)
github.com/Dongwu259/photo_s

MIT code; the style-model weights are non-commercial (trained on my personal
edits), everything else is free for commercial use.
```

**r/photography 版本**：去掉 pip/技术细节，改成"我用它把选片+初调压到 10 分钟"
的体验叙述 + 2 张 before/after 图，评论区再放链接（该版块对自我推广严格）。

---

## 8. 评论区高频问题的标准回答（提前备好）

**Q：和 ExifTool / ImageMagick / XnConvert 有什么区别？**
> 那些是通用图片工具；PhotoS 是**围绕 Lightroom 工作流**做的：XMP 双向往返、
> autopilot 质检分流、RAW 质量档位（去马赛克算法/16-bit/色彩空间）。另外它同时
> 是 agent 接口（MCP/REST/JSON 契约），这是通用工具完全没有的。

**Q：为什么要用命令行？摄影师不会用。**
> 有完整 GUI（Library/Develop/Export/Tools 四模块，实时预览 + 直方图 + 蒙版画布）。
> 命令行是给自动化和 AI agent 用的那一半——同一套引擎，两种入口。

**Q：凭什么信你的"AI 调色"？**
> 目前不吹它。它在我的 1295 条数据上 PSNR 32.21，是个**个人风格模型**，不是通用
> 一键美化。价值在于它是用你自己的数据训的，而且只有 4.6MB、本机跑。想试的话
> `photo-s suggest` 是无模型的规则版，可以先看它给的建议合不合理。

**Q：会上传我的照片吗？**
> 不会。整个项目没有云端组件。模型权重首次使用时从 GitHub/ModelScope 下载到本地，
> 之后纯本地推理；`lr-scan --sanitize` 还能把路径也脱敏。

**Q：star 这么少，靠谱吗？**
> 项目 2026-08 才开始，还很年轻。可以自己验：1490 个测试、CI 跨平台、24 个版本、
> 文档全在仓库里。有 issue 我当天回。

---

## 9. 发完之后（比发文更重要）

1. **回复每一条评论**（24 小时内），把反馈直接转成 issue。
2. **把有价值的质疑写进 README 的 FAQ**——下一个访客会看到。
3. **每周发一次进展**（X/即刻/V2EX 跟帖）：修了哪些 bug、模型涨了多少 dB、
   新增了什么。0→100 star 靠的是"这项目还活着"的持续信号。
4. **给早期用户一个身份**：把他们的建议写进 CHANGELOG 的致谢。
5. **准备 3 个"可被引用"的数字**，后续所有文案复用：
   - 39 个 CLI 子命令 / 31 个 MCP 工具
   - 1295 条修图记录 → PSNR 32.21，权重 4.6MB，全本地
   - 1490 个测试，CI 覆盖 macOS/Windows/Linux
