"""B站字幕抓取。

思路沿用 bilibili-subtitle 的 src/inject/inject.ts:187-204：

    BV号 → /x/web-interface/view        拿 aid / cid / 标题 / UP主 / 发布时间
         → /x/player/wbi/v2?aid=&cid=   拿 subtitles[]（含 AI 字幕 ai-zh）
         → subtitle_url 的 JSON         拿 body[].from/to/content

两个坑：
  1. 这些接口匿名也能调通（返回 code:0），但**字幕列表是空的** ——
     AI 字幕只在登录态下返回，所以必须先带上 SESSDATA。
  2. 弹幕（danmaku）也挂在同一个 subtitles 列表里，但它是 XML 不是字幕，必须排除。
"""

import re
from datetime import datetime

import requests

from ..cookies import cookie_header_for_bilibili
from ..schemas import Segment, Transcript
from .base import NoSubtitle, Platform

API_VIEW = "https://api.bilibili.com/x/web-interface/view"
API_PLAYER = "https://api.bilibili.com/x/player/wbi/v2"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com",
}

# 字幕语言优先级：中文人工 > 中文AI > 英文人工 > 英文AI > 其它
PREFERRED = ["zh-CN", "zh-Hans", "zh-Hant", "zh", "ai-zh", "en-US", "en", "ai-en"]


def _pick_subtitle(subs: list[dict]) -> dict | None:
    """从字幕列表里挑一条最合适的。"""
    # 弹幕是 XML，不是字幕
    usable = [s for s in subs if s.get("subtitle_url") and s.get("lan") != "danmaku"]
    if not usable:
        return None

    by_lan = {s.get("lan"): s for s in usable}
    for lan in PREFERRED:
        if lan in by_lan:
            return by_lan[lan]
    return usable[0]


def _normalize_subtitle_url(url: str) -> str:
    """subtitle_url 有时是 http:// 甚至协议相对的 //，统一成 https。"""
    if url.startswith("//"):
        return "https:" + url
    return url.replace("http://", "https://", 1)


def _parse_ids(url: str) -> tuple[str, str]:
    """从 URL 里取出 (id 类型, id 值)。支持 BV号 / av号。"""
    m = re.search(r"(BV[0-9A-Za-z]{10})", url)
    if m:
        return "bvid", m.group(1)
    m = re.search(r"/video/av(\d+)", url, re.I)
    if m:
        return "aid", m.group(1)
    raise NoSubtitle(f"没能从链接里认出 BV 号或 av 号：{url}")


class BilibiliPlatform(Platform):
    name = "bilibili"
    display = "B站"

    def fetch(self, url: str, on_progress=None) -> Transcript:
        log = on_progress or (lambda _: None)

        if "/bangumi/" in url:
            raise NoSubtitle("番剧页面暂不支持，请用普通视频链接（/video/BV...）")

        kind, value = _parse_ids(url)
        cookie = cookie_header_for_bilibili()
        session = requests.Session()
        session.headers.update(HEADERS)
        if cookie:
            session.headers["Cookie"] = cookie

        log("正在读取视频信息…")
        params = {kind: value}
        info = self._get(session, API_VIEW, params)
        data = info.get("data") or {}
        if not data:
            raise NoSubtitle(f"读不到视频信息：{info.get('message') or '接口无数据'}")

        title = data.get("title") or ""
        author = (data.get("owner") or {}).get("name") or ""
        ctime = data.get("ctime")
        created = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M:%S") if ctime else ""
        aid = data.get("aid")

        # 分P视频：?p=2 要取对应的 cid，否则拿到的是第一P的字幕
        cid = data.get("cid")
        page_no = self._page_number(url)
        pages = data.get("pages") or []
        if page_no > 1 and len(pages) >= page_no:
            page = pages[page_no - 1]
            cid = page.get("cid")
            title = f"{title} - P{page_no} {page.get('part', '')}".strip()
        elif len(pages) > 1:
            title = f"{title} - P1"

        log("正在查询字幕列表…")
        player = self._get(session, API_PLAYER, {"aid": aid, "cid": cid})
        sub_obj = ((player.get("data") or {}).get("subtitle")) or {}
        subs = sub_obj.get("subtitles") or []

        chosen = _pick_subtitle(subs)
        if not chosen:
            # 区分"真没字幕"和"没登录所以看不到"，前者还能走 ASR，后者提示去登录
            if sub_obj.get("need_login_subtitle") or not cookie:
                hint = "" if cookie else "；当前也没检测到B站登录态，去 Chrome 登录一次可解锁 AI 字幕"
                raise NoSubtitle(f"这个视频没有可用的字幕轨{hint}")
            raise NoSubtitle("这个视频没有字幕轨")

        log(f"正在下载字幕（{chosen.get('lan_doc') or chosen.get('lan')}）…")
        raw = self._get_absolute(session, _normalize_subtitle_url(chosen["subtitle_url"]))
        segments = [
            Segment(
                start=float(item.get("from", 0)),
                end=float(item.get("to", 0)),
                text=(item.get("content") or "").strip(),
            )
            for item in raw.get("body") or []
            if (item.get("content") or "").strip()
        ]
        if not segments:
            raise NoSubtitle("字幕文件是空的")

        return Transcript(
            platform=self.name,
            title=title,
            url=url,
            author=author,
            created=created,
            segments=segments,
            source="subtitle",
        )

    @staticmethod
    def _page_number(url: str) -> int:
        m = re.search(r"[?&]p=(\d+)", url)
        return int(m.group(1)) if m else 1

    @staticmethod
    def _get(session: requests.Session, api: str, params: dict) -> dict:
        r = session.get(api, params=params, timeout=20)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _get_absolute(session: requests.Session, url: str) -> dict:
        r = session.get(url, timeout=20)
        r.raise_for_status()
        return r.json()
