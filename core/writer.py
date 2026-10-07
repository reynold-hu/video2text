"""把 Transcript 渲染成各种可下载格式。

格式定义移植自 bilibili-subtitle 的 src/components/MoreBtn.tsx:85-125，
时间格式化移植自 src/utils/util.ts:17-70，保持输出完全一致。
"""

import re

from .schemas import Transcript

# 下载按钮 → (显示名, 文件后缀)
FORMATS: dict[str, tuple[str, str]] = {
    "text": ("纯文本", "txt"),
    "textWithTime": ("带时间戳", "txt"),
    "article": ("连成一段", "txt"),
    "srt": ("SRT 字幕", "srt"),
    "vtt": ("WebVTT 字幕", "vtt"),
}


def format_time(seconds: float) -> str:
    """MM:SS，超过一小时则为 HH:MM:SS。对应 util.ts:17 的 formatTime。"""
    if not isinstance(seconds, (int, float)) or seconds != seconds or seconds <= 0:
        return "00:00"

    total = int(seconds)
    hours, minutes, secs = total // 3600, (total % 3600) // 60, total % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_srt_time(seconds: float) -> str:
    """HH:MM:SS,mmm —— SRT 的毫秒用逗号分隔。对应 util.ts:47。"""
    if not seconds:
        return "00:00:00,000"

    hours = int(seconds // 3600)
    minutes = int(seconds // 60 % 60)
    secs = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def format_vtt_time(seconds: float) -> str:
    """HH:MM:SS.mmm —— WebVTT 用点号。对应 util.ts:60。"""
    if not seconds:
        return "00:00:00.000"

    hours = int(seconds // 3600)
    minutes = int(seconds // 60 % 60)
    secs = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def safe_filename(title: str, fallback: str = "transcript") -> str:
    """标题里有 / : 等字符会让下载文件名出问题，统一清掉。"""
    name = re.sub(r'[/\\:*?"<>|\n\r\t]', "_", title or "").strip(" .")
    return name[:80] or fallback


def _header(t: Transcript) -> str:
    """三个 txt 格式共用的文件头，对应 MoreBtn.tsx:89。"""
    return f"{t.title or '无标题'}\n{t.url or '无链接'}\n{t.author or '无作者'} {t.created}\n\n"


def _notes(t: Transcript) -> str:
    """小红书笔记正文之类的附注，接在正文后面。"""
    return f"\n\n---\n笔记正文：\n{t.extra}\n" if t.extra.strip() else ""


def render(t: Transcript, fmt: str) -> tuple[str, str]:
    """渲染成 (文件名, 内容)。文件名不含后缀。"""
    if fmt not in FORMATS:
        raise ValueError(f"未知格式：{fmt}")
    suffix = FORMATS[fmt][1]
    name = safe_filename(t.title)
    body = _render_body(t, fmt)
    return f"{name}.{suffix}", body


def _render_body(t: Transcript, fmt: str) -> str:
    segs = t.segments

    if fmt == "text":
        lines = "\n".join(s.text for s in segs)
        return _header(t) + lines + _notes(t)

    if fmt == "textWithTime":
        lines = "\n".join(f"{format_time(s.start)} {s.text}" for s in segs)
        return _header(t) + lines + _notes(t)

    if fmt == "article":
        # 用逗号连成整段，适合直接丢给大模型
        joined = ", ".join(s.text.strip() for s in segs if s.text.strip())
        return _header(t) + joined + _notes(t)

    if fmt == "srt":
        blocks = [
            f"{i}\n{format_srt_time(s.start)} --> {format_srt_time(s.end)}\n{s.text.strip()}\n"
            for i, s in enumerate(segs, start=1)
        ]
        return "\n".join(blocks).rstrip("\n")

    if fmt == "vtt":
        blocks = [
            f"{format_vtt_time(s.start)} --> {format_vtt_time(s.end)}\n{s.text.strip()}\n"
            for s in segs
        ]
        return "WEBVTT - " + (t.title or "") + "\n\n" + "\n".join(blocks).rstrip("\n")

    raise ValueError(f"未知格式：{fmt}")
