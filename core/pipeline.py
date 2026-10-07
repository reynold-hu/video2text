"""流水线编排：URL → 字幕（快）或本地转写（慢）→ Transcript。

这是唯一知道"先试字幕、失败再转写"这条策略的地方，
平台适配器和 ASR 引擎互相不知道对方存在。
"""

from typing import Callable

from . import asr, audio, router
from .platforms.base import NoSubtitle, Platform, Unsupported
from .schemas import Transcript

ProgressFn = Callable[[str], None]


class PipelineError(RuntimeError):
    """给用户看的错误，message 已经是可以直接显示的文案。"""


def _get_platform(platform: str) -> Platform:
    if platform == "bilibili":
        from .platforms.bilibili import BilibiliPlatform

        return BilibiliPlatform()
    if platform == "youtube":
        from .platforms.youtube import YouTubePlatform

        return YouTubePlatform()
    if platform == "xiaohongshu":
        from .platforms.xiaohongshu import XiaohongshuPlatform

        return XiaohongshuPlatform()
    raise PipelineError(f"不支持的平台：{platform}")


def run(
    text: str,
    engine: str = "mlx",
    language: str | None = "zh",
    on_progress: ProgressFn | None = None,
) -> Transcript:
    """跑完整条流水线。中途的进度和错误都通过 on_progress 汇报。

    language 默认 'zh'：这个工具主要面向 B站/小红书 的中文内容，指定中文比
    自动检测更稳 —— 自动检测偶尔会把中文判成粤语或日文，而且不指定就压不住
    繁体输出。英文内容请传 'en'，不确定就传 None 交给自动检测。
    """
    log: ProgressFn = on_progress or (lambda _: None)

    try:
        platform, url = router.resolve(text)
    except router.UnsupportedURL as e:
        raise PipelineError(str(e)) from e
    except Exception as e:
        raise PipelineError(f"解析链接失败：{str(e)[:150]}") from e

    log(f"识别到{router.PLATFORM_NAMES.get(platform, platform)}链接")
    adapter = _get_platform(platform)

    # ---- 第一步：试试有没有现成字幕轨（B站/YouTube 常常有，秒出）----
    meta: dict = {}
    try:
        transcript = adapter.fetch(url, log)
        log(f"完成，共 {len(transcript.segments)} 句")
        return transcript
    except Unsupported as e:
        # 链接本身就没法处理，别再浪费时间走 ASR
        raise PipelineError(str(e)) from e
    except NoSubtitle as e:
        meta = e.meta
        log(f"{e.reason}，改用本地转写")

    # ---- 第二步：下载音频 + 本地转写 ----
    return _transcribe(url, platform, meta, engine, language, log)


def run_from_page(
    payload: dict,
    engine: str = "mlx",
    language: str | None = "zh",
    on_progress: ProgressFn | None = None,
) -> Transcript:
    """给浏览器扩展用的入口：页面里已经拿到了需要的一切，不用再解析一遍。

    payload 形如：
        {"url": 页面地址, "platform": "xiaohongshu",
         "media_url": 页面里读到的媒体直链（可选）,
         "title"/"author"/"created"/"extra": 页面里读到的元信息}

    有 media_url 时直接下这个地址 —— 那是带签名的 CDN 直链，既省一次页面解析，
    也绕开了「服务端返回降级页面」这类问题（小红书的 token 过期就是这个表现）。
    """
    log: ProgressFn = on_progress or (lambda _: None)

    url = (payload or {}).get("url") or ""
    if not url:
        raise PipelineError("没拿到页面地址")

    try:
        platform = payload.get("platform") or router.detect(url)
    except router.UnsupportedURL as e:
        raise PipelineError(str(e)) from e

    meta = {
        "title": payload.get("title") or "",
        "author": payload.get("author") or "",
        "created": payload.get("created") or "",
        "extra": payload.get("extra") or "",
    }
    media_url = payload.get("media_url") or ""

    # 有直链就走直链；否则退回按页面地址解析（B站/YouTube 本来就靠这个）
    log(f"识别到{router.PLATFORM_NAMES.get(platform, platform)}链接")
    if not media_url:
        adapter = _get_platform(platform)
        try:
            transcript = adapter.fetch(url, log)
            log(f"完成，共 {len(transcript.segments)} 句")
            return transcript
        except Unsupported as e:
            raise PipelineError(str(e)) from e
        except NoSubtitle as e:
            meta = {**e.meta, **{k: v for k, v in meta.items() if v}}
            log(f"{e.reason}，改用本地转写")
    else:
        log("页面里拿到了媒体地址，直接使用")

    return _transcribe(url, platform, meta, engine, language, log, media_url=media_url)


def _transcribe(
    url: str,
    platform: str,
    meta: dict,
    engine: str,
    language: str | None,
    log: ProgressFn,
    media_url: str = "",
) -> Transcript:
    """下载音频并转写，返回 Transcript。"""
    wav = None
    try:
        if media_url:
            raw = audio.download_direct(media_url, referer=url, on_progress=log)
            wav = audio.to_wav(raw, on_progress=log)
        else:
            wav = audio.prepare(url, site=platform, on_progress=log)

        asr_engine = asr.get_engine(engine)
        log(f"正在用 {asr_engine.display} 转写…")
        segments = asr_engine.transcribe(wav, language=language, on_progress=log)
        # Whisper 中文默认吐繁体。对已经是简体的文本这是空操作，对英文也是空操作，
        # 所以无条件跑一遍最省心。
        segments = asr.to_simplified(segments)
    except audio.AudioError as e:
        raise PipelineError(str(e)) from e
    except asr.ASRError as e:
        raise PipelineError(str(e)) from e
    except Exception as e:
        raise PipelineError(f"转写失败：{str(e)[:200]}") from e
    finally:
        # 音频文件可能几百 MB，不管成功失败都要清掉
        audio.cleanup(wav)

    if not segments:
        raise PipelineError("转写结果为空，可能是没有人声的纯音乐/环境音视频")

    log(f"完成，共 {len(segments)} 句")
    return Transcript(
        platform=platform,
        title=meta.get("title") or "",
        url=url,
        author=meta.get("author") or "",
        created=meta.get("created") or "",
        segments=segments,
        source="asr",
        extra=meta.get("extra") or "",
        engine=engine,
    )
