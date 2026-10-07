"""小红书解析。

小红书**从来就没有字幕轨** —— 所以这个适配器的 fetch() 永远抛 NoSubtitle，
它的全部价值在于：用 yt-dlp 把笔记元信息捞出来（标题/作者/正文），
让后面的 ASR 分支能带着这些信息生成结果，而不是白跑一趟。

原理（yt-dlp 的 XiaoHongShuIE，仅 109 行）：
    分享链接 → 302 → xiaohongshu.com/explore/<24位id>?xsec_token=XXX
            → GET 网页 → HTML 里内嵌 window.__INITIAL_STATE__ 这坨 JSON
            → 正则抠出来 + js_to_json 解析 → video.media.stream[].masterUrl

不需要算签名，也不需要无头浏览器。但有两个硬约束：
  1. 必须传**完整带 xsec_token 的**分享链接，token 是笔记一对一的，缺了会解析为空
  2. yt-dlp 只支持视频笔记，图文笔记会直接失败
"""

import yt_dlp

from ..schemas import Transcript
from .base import NoSubtitle, Platform, ProgressFn, Unsupported

# 小红书的笔记正文（作者写的文案）本身往往就是有价值的内容，
# 所以额外抓下来放进 extra，跟转写结果一起输出。


class XiaohongshuPlatform(Platform):
    name = "xiaohongshu"
    display = "小红书"

    def fetch(self, url: str, on_progress: ProgressFn = None) -> Transcript:
        log = on_progress or (lambda _: None)
        log("正在解析笔记…")

        info = self._extract(url)

        if info.get("_type") == "playlist":
            entries = [e for e in (info.get("entries") or []) if e]
            if not entries:
                raise Unsupported("这个链接里没有可解析的笔记")
            info = entries[0]

        meta = {
            "title": info.get("title") or "",
            "author": info.get("uploader") or info.get("channel") or "",
            "created": self._format_date(info.get("upload_date")),
            "extra": (info.get("description") or "").strip(),
        }

        if not info.get("formats") and not info.get("url"):
            raise Unsupported(
                "这是一个图文笔记，没有视频也就没有音频，无法转成文字。"
                "目前只支持视频笔记。"
            )

        # 小红书没有字幕轨，直接交给 ASR 分支
        raise NoSubtitle("小红书没有字幕轨，需要下载音频本地转写", meta=meta)

    @staticmethod
    def _extract(url: str) -> dict:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
        }

        # 登录态能解锁更高码率，但不是必需
        try:
            from ..cookies import best_browser

            browser = best_browser("xiaohongshu")
            if browser:
                opts["cookiesfrombrowser"] = (browser,)
        except Exception:
            pass

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False) or {}
        except Exception as e:
            raise Unsupported(_friendly(str(e), url)) from e

    @staticmethod
    def _format_date(upload_date: str | None) -> str:
        if not upload_date or len(upload_date) != 8:
            return ""
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"


def _friendly(msg: str, url: str) -> str:
    low = msg.lower()
    if "unsupported url" in low:
        return (
            "yt-dlp 不认这个链接。小红书要粘**完整分享链接**"
            "（形如 https://www.xiaohongshu.com/explore/xxxx?xsec_token=...），"
            "短链 xhslink.com 会自动展开，但缺 xsec_token 会解析失败。"
        )
    if "unable to extract" in low or "no video" in low:
        return "解析不出内容，可能是图文笔记、私密笔记，或链接已失效"
    if "404" in low or "not found" in low:
        return "笔记不存在或已被删除"
    return msg.splitlines()[0][:200]
