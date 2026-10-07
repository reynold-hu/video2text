<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.png">
  <img alt="OpenVideo2Text" src="docs/logo.png" width="460">
</picture>

粘贴链接 → 提取文字 → 下载 txt。支持 **B站 / 小红书 / YouTube**，全程本地运行，不需要任何付费 API，也不上传你的数据。

---

## 快速开始

```bash
brew install uv ffmpeg    # 只需要装这两个
```

然后**双击 `run.command`**。浏览器会自动打开 `http://127.0.0.1:8756`。

首次运行会自动建虚拟环境并安装依赖（要几分钟，见下面的「首次安装慢」）。

## 它怎么工作

核心是一条**先便宜后昂贵**的流水线：

```
粘贴链接
  ↓ 识别平台（自动展开 b23.tv / xhslink.com 短链，能从整段分享文案里提出链接）
  ↓ ① 有现成字幕轨吗？
        B站 ✅   YouTube ✅   →  直接抓，秒出
        ↓ 没有
  ↓ ② yt-dlp 只下音频流（不是整个视频）
  ↓ ③ ffmpeg 转 16kHz 单声道 wav
  ↓ ④ 本地语音转写
  ↓ ⑤ 输出 txt / srt
```

**「有字幕就不转写」是重点。** B站和 YouTube 上大量视频本来就有字幕轨（含 AI 自动字幕），
抓下来是秒级的；只有真的没有字幕，才值得花几十秒跑语音识别。

结果页会用徽章标出这份文字是哪来的：

| 徽章 | 含义 |
|---|---|
| 🟢 **来自字幕** | 平台提供的原始字幕，准确度高，秒出 |
| 🔵 **本地转写** | 语音识别生成，可能有错字，慢一些 |

## 转写引擎

| 引擎 | 速度 | 中文准确率 | 说明 |
|---|---|---|---|
| **mlx-whisper** | 快 | 一般 | Apple 芯片专用，跑在 GPU 上，默认选它 |
| **FunASR Paraformer** | 慢（只能跑 CPU） | 好，错字率约为 Whisper 的一半 | 中文内容值得忍受慢 |

两个都装了，页面上随时可切。

模型可以换（默认 `large-v3-turbo`，中文建议就用它）：

```bash
V2T_MLX_MODEL=mlx-community/whisper-small-mlx python app.py
```

可选 `tiny`(75MB) / `base`(145MB) / `small`(480MB) / `large-v3-turbo`(1.6GB)。

## 浏览器扩展（可选）

`extension/` 里带了一个 Chrome 扩展。装不装都能用 —— 网页版是完整的；
装上之后不用复制粘贴，在视频页面上点一下图标就行。

它更实际的价值在于**小红书**：人在页面上，`xsec_token` 永远是新鲜的，
媒体地址也能直接从页面里读出来，绕开了「链接十分钟就过期」这个问题。

安装方式见 [extension/README.md](extension/README.md)。

## 各平台说明

### B站

**AI 字幕必须登录才返回**，匿名请求永远拿到空列表。所以：

1. 在 Chrome（或 Safari / Edge）里登录一次 bilibili.com
2. 刷新本页 —— 顶部黄色提示消失即表示已就绪

没登录也能用，只是会退到本地转写。支持 BV 号、av 号、分P（`?p=2`），番剧页面暂不支持。

### YouTube

开箱即用。人工字幕优先，没有就用自动字幕。年龄限制视频需要浏览器登录态。

### 小红书

小红书**从来没有字幕轨**，所以永远走本地转写。

三个硬约束：

- **必须粘完整分享链接**（形如 `https://www.xiaohongshu.com/explore/xxxx?xsec_token=...`）。
  `xsec_token` 是笔记一对一的，缺了会解析失败。App 里复制的那一整段分享文案可以整个粘进来，链接会自动识别。
- **只支持视频笔记**，图文笔记没有音轨。
- **链接会失效，而且会触发风控。** 实测同一条链接十分钟内从可用变为不可用 ——
  小红书返回 HTTP 200 但页面里不含笔记数据（`noteDetailMap` 为空），yt-dlp 因此报
  `No video formats found`。遇到这个提示就回 App 重新分享一次拿新链接，不要连续重试，
  请求越密越容易被限。

笔记正文文案会一并抓下来，附在结果末尾。

<details>
<summary>它是怎么做到的</summary>

小红书网页的 HTML 里内嵌了一坨 `window.__INITIAL_STATE__` JSON，里面有视频的真实地址。
解析它不需要算签名，也不需要无头浏览器 —— yt-dlp 内置的 extractor 一共 109 行。

那些「小红书视频下载」小程序做的事其实一样，只不过解析跑在它们自己的服务器上。

</details>

## 输出格式

| 格式 | 用途 |
|---|---|
| 纯文本 | 每句一行，最干净 |
| 带时间戳 | 每行前面加 `MM:SS`，方便定位 |
| 连成一段 | 用逗号连成整段，适合直接丢给大模型 |
| SRT / WebVTT | 标准字幕文件，可导入播放器 |

## 目录结构

```
run.command            双击启动
app.py                 FastAPI 服务：任务管理 + 下载
static/index.html      前端（单文件，无构建步骤）
core/
  router.py            URL 识别、短链展开
  cookies.py           浏览器登录态探测
  pipeline.py          流水线编排
  audio.py             yt-dlp 下载音频 + ffmpeg 转换
  writer.py            五种输出格式
  schemas.py           统一数据模型
  ytdlp_util.py        yt-dlp 的共用静音配置
  platforms/           三个平台的适配器，各自独立
  asr/                 两个转写引擎，接口统一
tests/                 自动化测试
extension/             可选的 Chrome 扩展（见它的 README）
docs/                  README 用的图
```

## 跑测试

用标准库 `unittest`，不需要额外装东西：

```bash
.venv/bin/python -m unittest discover -s tests   # 92 个
node extension/test/extract.test.js               # 14 个，扩展的提取逻辑
```

覆盖了输出格式、URL 路由、三个平台的解析逻辑，以及**流水线的降级决策**
（有字幕时绝不下载音频、无字幕时元信息要接住、图文笔记不该浪费时间走 ASR）。
Python 那套全程不联网。

加一个平台只需要在 `core/platforms/` 下加一个文件实现 `fetch()`，
拿不到字幕就抛 `NoSubtitle` —— 剩下的流水线会自动接管。

## 常见问题

**B站提取出来是空的 / 提示没有字幕轨**
没登录。去浏览器登录 bilibili.com，刷新页面。

**小红书解析失败**
检查链接是否完整（要带 `xsec_token`）。短链 `xhslink.com` 会自动展开，
但如果 App 给的分享链接本身不完整，展开后也拿不到 token。

**转写很慢**
首次要下载模型（默认那个约 1.6 GB），之后就快了。赶时间可以换 `small` 或 `tiny` 模型。

**mlx-whisper 一直说「模型待下载」，或者下载总是失败**
默认模型 1.6 GB，网络不稳时很难拉下来。两个办法：

- 换国内镜像重试：`HF_ENDPOINT=https://hf-mirror.com python app.py`
- **直接用 FunASR 引擎** —— 它的模型通常更小、更易下载，而且中文准确率更好

页面上会标出每个引擎的模型是否已经在本机（「模型待下载」= 点下去要先联网拉权重）。

**首次安装慢**
正常。两个转写引擎都要 PyTorch，加起来 1 GB 以上。挂了代理会更慢，
可以加国内源：`uv pip install --index-url https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt`

**依赖装到一半失败**
`funasr` 的依赖声明里 `transformers` 没锁版本，包管理器可能挑到 2021 年的老版本，
它依赖的 `tokenizers` 又没有 Apple 芯片的预编译包，会去编译 Rust 然后失败。
`requirements.txt` 里已经钉了 `transformers>=4.40,<5` 绕开 —— 如果还是失败，
删掉 `.venv` 重新来一遍。

**提示找不到 ffmpeg**
`brew install ffmpeg`

## 致谢

- 字幕抓取思路和输出格式移植自 [bilibili-subtitle](https://github.com/IndieKKY/bilibili-subtitle)（MIT）
- 下载能力来自 [yt-dlp](https://github.com/yt-dlp/yt-dlp)（Unlicense）
- 转写来自 [mlx-whisper](https://github.com/ml-explore/mlx-examples)（MIT）和 [FunASR](https://github.com/modelscope/FunASR)（MIT）

## 说明

本项目仅供个人学习使用。请遵守各平台的服务条款，不要用于批量抓取或商业用途。
