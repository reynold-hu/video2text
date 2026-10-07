"""音频获取与预处理。

有字幕的视频根本不会走到这里 —— 只有小红书（永远没字幕轨）和少数无字幕视频需要。

关键点：用 yt-dlp 的 -f bestaudio **只下音频流**，不是整个视频。
一个 10 分钟的视频，视频流可能上百 MB，音轨通常只有几 MB。
"""

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from .ytdlp_util import base_opts

WORK_DIR = Path(__file__).resolve().parent.parent / ".work"

# whisper 系模型统一要求 16kHz 单声道
SAMPLE_RATE = 16000


class AudioError(RuntimeError):
    pass


def _workdir() -> Path:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    return WORK_DIR


def _require_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise AudioError("找不到 ffmpeg。请先安装：brew install ffmpeg")
    return exe


def download(url: str, site: str | None = None, on_progress=None) -> Path:
    """用 yt-dlp 只抓音频流，返回下载到的文件路径。

    site 指明这个链接属于哪个站点，用来挑对浏览器 —— 如果小红书和 B站 的登录态
    分别在两个浏览器里，不区分就会拿错 cookie。
    """
    import yt_dlp

    log = on_progress or (lambda _: None)
    workdir = _workdir()
    job_dir = workdir / uuid.uuid4().hex[:12]
    job_dir.mkdir(parents=True, exist_ok=True)

    state = {"last": -1}

    def hook(d):
        if d.get("status") != "downloading":
            return
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        done = d.get("downloaded_bytes") or 0
        if not total:
            return
        pct = int(done * 100 / total)
        if pct >= state["last"] + 10:
            state["last"] = pct
            log(f"正在下载音频… {pct}%")

    opts = {
        **base_opts(),
        "format": "bestaudio/best",
        "outtmpl": str(job_dir / "audio.%(ext)s"),
        "noplaylist": True,
        # 进度由我们自己的 hook 汇报给前端，不走 yt-dlp 的输出
        "progress_hooks": [hook],
    }

    # 小红书的部分内容要登录态才给高码率
    try:
        from .cookies import best_browser

        browser = best_browser(site) if site else None
        if browser:
            opts["cookiesfrombrowser"] = (browser,)
    except Exception:
        pass

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as e:
        raise AudioError(_friendly(str(e))) from e

    files = [f for f in job_dir.iterdir() if f.is_file()]
    if not files:
        raise AudioError("没下载到音频，可能是图文笔记或链接已失效")
    return max(files, key=lambda f: f.stat().st_size)


def to_wav(src: Path, on_progress=None) -> Path:
    """转成 16kHz 单声道 wav —— 所有 ASR 引擎都吃这个格式。"""
    log = on_progress or (lambda _: None)
    log("正在转换音频格式…")

    ffmpeg = _require_ffmpeg()
    dst = src.with_suffix(".wav")

    proc = subprocess.run(
        [ffmpeg, "-y", "-i", str(src), "-vn",
         "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", str(dst)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not dst.exists():
        tail = (proc.stderr or "").strip().splitlines()[-3:]
        raise AudioError("ffmpeg 转换失败：" + " / ".join(tail))
    return dst


def prepare(url: str, site: str | None = None, on_progress=None) -> Path:
    """一步到位：下载音频 → 转 wav。"""
    raw = download(url, site, on_progress)
    return to_wav(raw, on_progress)


def cleanup(path: Path | None) -> None:
    """删掉整个 job 临时目录。"""
    if not path:
        return
    job_dir = path.parent
    try:
        if job_dir != WORK_DIR and job_dir.is_dir() and WORK_DIR in job_dir.parents:
            shutil.rmtree(job_dir, ignore_errors=True)
    except OSError:
        pass


def sweep() -> None:
    """清掉上次异常退出残留的临时目录。"""
    if not WORK_DIR.exists():
        return
    for d in WORK_DIR.iterdir():
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)


def _friendly(msg: str) -> str:
    """把 yt-dlp 的英文报错转成能看懂的话。"""
    low = msg.lower()
    if "unsupported url" in low:
        return "yt-dlp 不认这个链接，可能是图文笔记或链接不完整（小红书需要带 xsec_token 的完整分享链接）"
    if "no video formats" in low or "requested format" in low:
        # 小红书最常见的失败：页面能打开，但服务端返回的是不含笔记数据的降级页面，
        # 于是 yt-dlp 找不到任何视频流。表现为报这个错，而不是 HTTP 错误。
        return (
            "解析不到视频流。如果是小红书，多半是分享链接里的 xsec_token 过期了，"
            "或者短时间请求太多触发了风控 —— 回 App 重新分享一次拿条新链接即可。"
            "图文笔记（没有视频）也会是这个提示。"
        )
    if "login" in low or "cookies" in low or "sign in" in low:
        return "需要登录态才能访问，请在浏览器里登录后重试"
    if "403" in low or "forbidden" in low:
        return "被平台拒绝了（403），可能需要登录或稍后重试"
    if "404" in low or "not found" in low or "deleted" in low:
        return "内容不存在或已被删除"
    return msg.splitlines()[0][:200]
