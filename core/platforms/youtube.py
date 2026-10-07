"""YouTube 字幕抓取。

用 yt-dlp 的 Python API 取元信息（不下载视频），从 subtitles（人工字幕）和
automatic_captions（自动生成）里挑一条，再把字幕文件拉下来解析。

两个格式来源：
  - json3  YouTube 原生结构化格式，最好解析，优先用
  - vtt    兜底。自动字幕的 VTT 里带 <00:00:00.000><c>词</c> 这类内联时间标签，要清掉
"""

import json
import re

import requests

from ..schemas import Segment, Transcript
from ..ytdlp_util import base_opts
from .base import NoSubtitle, Platform

# 语言偏好：中文优先，其次英文
PREFERRED = [
    "zh-Hans", "zh-CN", "zh", "zh-Hant", "zh-TW",
    "en", "en-US", "en-GB", "en-orig",
]

_TAG = re.compile(r"<[^>]+>")


def _pick_language(tracks: dict) -> str | None:
    if not tracks:
        return None
    for lan in PREFERRED:
        if lan in tracks:
            return lan
    # 偏好列表都没命中就退回前缀匹配（zh-Hans-CN 之类）
    for lan in tracks:
        if lan.startswith(("zh", "en")):
            return lan
    return next(iter(tracks))


def _parse_json3(data: dict) -> list[Segment]:
    segments = []
    for ev in data.get("events") or []:
        segs = ev.get("segs")
        if not segs:
            continue
        text = _TAG.sub("", "".join(s.get("utf8", "") for s in segs)).replace("\n", " ").strip()
        if not text:
            continue
        start = (ev.get("tStartMs") or 0) / 1000
        end = start + (ev.get("dDurationMs") or 0) / 1000
        segments.append(Segment(start=start, end=end, text=text))
    return segments


def _ts_to_seconds(ts: str) -> float:
    """把 00:01:02.500 或 01:02.500 转成秒。"""
    parts = ts.strip().replace(",", ".").split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return 0.0
    seconds = 0.0
    for n in nums:
        seconds = seconds * 60 + n
    return seconds


def _parse_vtt(text: str) -> list[Segment]:
    segments = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "-->" not in line:
            i += 1
            continue

        left, _, right = line.partition("-->")
        start = _ts_to_seconds(left)
        # 右侧可能跟着 position:xx% 之类的设置，只取时间部分
        end = _ts_to_seconds(right.strip().split(" ")[0])

        i += 1
        buf = []
        while i < len(lines) and lines[i].strip():
            buf.append(_TAG.sub("", lines[i]).strip())
            i += 1

        content = " ".join(x for x in buf if x).strip()
        if content:
            segments.append(Segment(start=start, end=end, text=content))
        i += 1

    return segments


def _dedupe(segments: list[Segment]) -> list[Segment]:
    """YouTube 自动字幕的滚动窗口会让同一句重复出现，去掉相邻重复。"""
    out: list[Segment] = []
    for s in segments:
        if out and out[-1].text == s.text:
            out[-1].end = s.end
            continue
        out.append(s)
    return out


def _fetch_track(session: requests.Session, formats: list[dict]) -> list[Segment]:
    """从一条字幕轨的多个格式里挑一个拉下来解析。"""
    if not formats:
        return []

    by_ext = {f.get("ext"): f for f in formats}
    json3 = by_ext.get("json3")
    if json3:
        url = re.sub(r"fmt=[^&]*", "fmt=json3", json3["url"])
        r = session.get(url, timeout=20)
        if r.ok:
            segs = _parse_json3(r.json())
            if segs:
                return _dedupe(segs)

    # json3 拿不到就退回任意一个 vtt/srv3
    fallback = by_ext.get("vtt") or by_ext.get("srv3") or formats[0]
    r = session.get(fallback["url"], timeout=20)
    r.raise_for_status()
    if fallback.get("ext") == "json3" or r.text.lstrip().startswith("{"):
        return _dedupe(_parse_json3(json.loads(r.text)))
    return _dedupe(_parse_vtt(r.text))


class YouTubePlatform(Platform):
    name = "youtube"
    display = "YouTube"

    def fetch(self, url: str, on_progress=None) -> Transcript:
        import yt_dlp

        log = on_progress or (lambda _: None)
        log("正在读取视频信息…")

        opts = {
            **base_opts(),
            "skip_download": True,
            "noplaylist": True,
        }
        # 年龄限制视频需要登录态，有就带上
        browser = self._cookie_browser()
        if browser:
            opts["cookiesfrombrowser"] = (browser,)

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if info.get("_type") == "playlist":
            entries = [e for e in (info.get("entries") or []) if e]
            if not entries:
                raise NoSubtitle("这个播放列表是空的")
            info = entries[0]

        manual = info.get("subtitles") or {}
        auto = info.get("automatic_captions") or {}

        lan = _pick_language(manual)
        tracks, kind = (manual, "人工字幕") if lan else (_pick_language(auto), "自动字幕")
        if not lan:
            raise NoSubtitle("这个视频没有字幕（人工和自动都没有）")
        tracks = manual if kind == "人工字幕" else auto

        log(f"正在下载{kind}（{lan}）…")
        session = requests.Session()
        segments = _fetch_track(session, tracks[lan])
        if not segments:
            raise NoSubtitle("字幕内容是空的")

        upload_date = info.get("upload_date") or ""  # YYYYMMDD
        created = (
            f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
            if len(upload_date) == 8
            else ""
        )

        return Transcript(
            platform=self.name,
            title=info.get("title") or "",
            url=info.get("webpage_url") or url,
            author=info.get("uploader") or "",
            created=created,
            segments=segments,
            source="subtitle",
        )

    @staticmethod
    def _cookie_browser() -> str | None:
        from ..cookies import best_browser

        try:
            return best_browser("youtube") or best_browser("bilibili")
        except Exception:
            return None
