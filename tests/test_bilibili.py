"""B站字幕解析的测试。网络层被桩掉，只测解析逻辑。"""

import unittest

from core.platforms.base import NoSubtitle
from core.platforms.bilibili import (
    BilibiliPlatform,
    _normalize_subtitle_url,
    _parse_ids,
    _pick_subtitle,
)


class TestPickSubtitle(unittest.TestCase):
    def test_excludes_danmaku(self):
        # 弹幕挂在同一个 subtitles 列表里，但它是 XML 不是字幕
        subs = [{"lan": "danmaku", "subtitle_url": "http://x/d.xml"}]
        self.assertIsNone(_pick_subtitle(subs))

    def test_prefers_human_chinese_over_ai(self):
        subs = [
            {"lan": "ai-zh", "subtitle_url": "http://x/ai.json"},
            {"lan": "zh-CN", "subtitle_url": "http://x/human.json"},
        ]
        self.assertEqual(_pick_subtitle(subs)["lan"], "zh-CN")

    def test_prefers_chinese_over_english(self):
        subs = [
            {"lan": "en", "subtitle_url": "http://x/en.json"},
            {"lan": "ai-zh", "subtitle_url": "http://x/zh.json"},
        ]
        self.assertEqual(_pick_subtitle(subs)["lan"], "ai-zh")

    def test_skips_entries_without_url(self):
        # AI 字幕条目在未登录时会存在但 url 为空
        subs = [
            {"lan": "zh-CN", "subtitle_url": ""},
            {"lan": "en", "subtitle_url": "http://x/en.json"},
        ]
        self.assertEqual(_pick_subtitle(subs)["lan"], "en")

    def test_empty_list(self):
        self.assertIsNone(_pick_subtitle([]))

    def test_falls_back_to_first_usable(self):
        subs = [{"lan": "ja", "subtitle_url": "http://x/ja.json"}]
        self.assertEqual(_pick_subtitle(subs)["lan"], "ja")


class TestNormalizeSubtitleUrl(unittest.TestCase):
    def test_protocol_relative(self):
        self.assertEqual(
            _normalize_subtitle_url("//aisubtitle.hdslb.com/x.json"),
            "https://aisubtitle.hdslb.com/x.json",
        )

    def test_http_upgraded_to_https(self):
        self.assertEqual(
            _normalize_subtitle_url("http://aisubtitle.hdslb.com/x.json"),
            "https://aisubtitle.hdslb.com/x.json",
        )

    def test_https_unchanged(self):
        url = "https://aisubtitle.hdslb.com/x.json"
        self.assertEqual(_normalize_subtitle_url(url), url)


class TestParseIds(unittest.TestCase):
    def test_bvid(self):
        self.assertEqual(
            _parse_ids("https://www.bilibili.com/video/BV1xx411c7mD"),
            ("bvid", "BV1xx411c7mD"),
        )

    def test_avid(self):
        self.assertEqual(
            _parse_ids("https://www.bilibili.com/video/av12345"),
            ("aid", "12345"),
        )

    def test_bvid_with_query_and_trailing_slash(self):
        self.assertEqual(
            _parse_ids("https://www.bilibili.com/video/BV1xx411c7mD/?spm_id_from=333"),
            ("bvid", "BV1xx411c7mD"),
        )

    def test_unrecognized_raises(self):
        with self.assertRaises(NoSubtitle):
            _parse_ids("https://www.bilibili.com/list/watchlater")


class TestPageNumber(unittest.TestCase):
    def test_default_is_one(self):
        self.assertEqual(BilibiliPlatform._page_number("https://b.com/video/BV1"), 1)

    def test_reads_p_param(self):
        self.assertEqual(
            BilibiliPlatform._page_number("https://b.com/video/BV1?p=3"), 3
        )


class StubPlatform(BilibiliPlatform):
    """把网络调用换成固定返回，用来测完整流程。"""

    def __init__(self, subs, body):
        self._subs = subs
        self._body = body

    def _get(self, session, api, params):
        if "view" in api:
            return {
                "data": {
                    "aid": 123,
                    "cid": 456,
                    "title": "测试视频",
                    "ctime": 1735689600,
                    "owner": {"name": "某UP"},
                    "pages": [{"cid": 456, "page": 1, "part": "P1"}],
                }
            }
        return {"data": {"subtitle": {"subtitles": self._subs}}}

    def _get_absolute(self, session, url):
        return self._body


class TestFetch(unittest.TestCase):
    def test_parses_body_into_segments(self):
        subs = [{"lan": "zh-CN", "subtitle_url": "https://x/z.json"}]
        body = {
            "body": [
                {"from": 0.0, "to": 2.5, "content": "第一句"},
                {"from": 2.5, "to": 5.0, "content": "第二句"},
            ]
        }
        t = StubPlatform(subs, body).fetch("https://www.bilibili.com/video/BV1xx411c7mD")
        self.assertEqual(len(t.segments), 2)
        self.assertEqual(t.segments[0].text, "第一句")
        self.assertEqual(t.segments[1].start, 2.5)
        self.assertEqual(t.source, "subtitle")
        self.assertEqual(t.author, "某UP")
        self.assertEqual(t.created, "2025-01-01 08:00:00")

    def test_blank_segments_filtered(self):
        subs = [{"lan": "zh-CN", "subtitle_url": "https://x/z.json"}]
        body = {
            "body": [
                {"from": 0.0, "to": 1.0, "content": "有内容"},
                {"from": 1.0, "to": 2.0, "content": "   "},
                {"from": 2.0, "to": 3.0, "content": ""},
            ]
        }
        t = StubPlatform(subs, body).fetch("https://www.bilibili.com/video/BV1xx411c7mD")
        self.assertEqual(len(t.segments), 1)

    def test_only_danmaku_raises_nosubtitle(self):
        subs = [{"lan": "danmaku", "subtitle_url": "http://x/d.xml"}]
        with self.assertRaises(NoSubtitle):
            StubPlatform(subs, {}).fetch("https://www.bilibili.com/video/BV1xx411c7mD")

    def test_empty_body_raises_nosubtitle(self):
        subs = [{"lan": "zh-CN", "subtitle_url": "https://x/z.json"}]
        with self.assertRaises(NoSubtitle):
            StubPlatform(subs, {"body": []}).fetch("https://www.bilibili.com/video/BV1xx411c7mD")

    def test_bangumi_rejected_early(self):
        with self.assertRaises(NoSubtitle):
            StubPlatform([], {}).fetch("https://www.bilibili.com/bangumi/play/ep123")


if __name__ == "__main__":
    unittest.main()
