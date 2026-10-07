"""YouTube 字幕解析的测试。重点是两种格式的解析和自动字幕的去重。"""

import unittest

from core.platforms.youtube import (
    _dedupe,
    _parse_json3,
    _parse_vtt,
    _pick_language,
    _ts_to_seconds,
)
from core.schemas import Segment


class TestPickLanguage(unittest.TestCase):
    def test_prefers_simplified_chinese(self):
        self.assertEqual(_pick_language({"en": [], "zh-Hans": [], "zh-Hant": []}), "zh-Hans")

    def test_chinese_before_english(self):
        self.assertEqual(_pick_language({"en": [], "zh-CN": []}), "zh-CN")

    def test_english_when_no_chinese(self):
        self.assertEqual(_pick_language({"en": [], "ja": []}), "en")

    def test_unknown_language_falls_back_to_first(self):
        self.assertEqual(_pick_language({"ja": [], "ko": []}), "ja")

    def test_empty(self):
        self.assertIsNone(_pick_language({}))


class TestTsToSeconds(unittest.TestCase):
    def test_hh_mm_ss_millis(self):
        self.assertAlmostEqual(_ts_to_seconds("00:01:02.500"), 62.5)

    def test_mm_ss_millis(self):
        self.assertAlmostEqual(_ts_to_seconds("01:02.500"), 62.5)

    def test_comma_separator(self):
        self.assertAlmostEqual(_ts_to_seconds("00:00:05,400"), 5.4)

    def test_garbage_returns_zero(self):
        self.assertEqual(_ts_to_seconds("abc"), 0.0)


class TestParseJson3(unittest.TestCase):
    def test_extracts_text_and_timing(self):
        data = {
            "events": [
                {"tStartMs": 0, "dDurationMs": 1500, "segs": [{"utf8": "Hello"}]},
                {"tStartMs": 1500, "dDurationMs": 2000, "segs": [{"utf8": "World"}]},
            ]
        }
        segs = _parse_json3(data)
        self.assertEqual([s.text for s in segs], ["Hello", "World"])
        self.assertAlmostEqual(segs[1].start, 1.5)
        self.assertAlmostEqual(segs[1].end, 3.5)

    def test_joins_multiple_segs(self):
        data = {"events": [{"tStartMs": 0, "dDurationMs": 1000,
                            "segs": [{"utf8": "foo"}, {"utf8": " bar"}]}]}
        self.assertEqual(_parse_json3(data)[0].text, "foo bar")

    def test_skips_events_without_segs(self):
        data = {"events": [{"tStartMs": 0, "dDurationMs": 100, "segs": []},
                           {"tStartMs": 100, "dDurationMs": 100,
                            "segs": [{"utf8": "keep"}]}]}
        self.assertEqual(len(_parse_json3(data)), 1)

    def test_empty(self):
        self.assertEqual(_parse_json3({}), [])


class TestParseVtt(unittest.TestCase):
    def test_basic_cues(self):
        vtt = (
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:02.000\n"
            "First line\n\n"
            "00:00:02.000 --> 00:00:04.000\n"
            "Second line\n"
        )
        segs = _parse_vtt(vtt)
        self.assertEqual([s.text for s in segs], ["First line", "Second line"])
        self.assertAlmostEqual(segs[1].start, 2.0)

    def test_strips_inline_timing_tags(self):
        # 自动字幕的 VTT 里每个词都带内联时间标签
        vtt = (
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:02.000\n"
            "<00:00:00.000><c>Hello</c> <00:00:01.000><c>world</c>\n"
        )
        self.assertEqual(_parse_vtt(vtt)[0].text, "Hello world")

    def test_ignores_cue_settings(self):
        vtt = (
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:02.000 align:start position:10%\n"
            "Text\n"
        )
        segs = _parse_vtt(vtt)
        self.assertEqual(len(segs), 1)
        self.assertAlmostEqual(segs[0].end, 2.0)

    def test_multiline_cue_joined(self):
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nline one\nline two\n"
        self.assertEqual(_parse_vtt(vtt)[0].text, "line one line two")

    def test_header_only(self):
        self.assertEqual(_parse_vtt("WEBVTT\n"), [])


class TestDedupe(unittest.TestCase):
    def test_collapses_adjacent_duplicates(self):
        # 自动字幕的滚动窗口会让同一句反复出现
        segs = [
            Segment(0.0, 1.0, "same"),
            Segment(1.0, 2.0, "same"),
            Segment(2.0, 3.0, "other"),
        ]
        out = _dedupe(segs)
        self.assertEqual([s.text for s in out], ["same", "other"])
        # 合并时结束时间要跟着延长
        self.assertAlmostEqual(out[0].end, 2.0)

    def test_keeps_non_adjacent_repeats(self):
        segs = [
            Segment(0.0, 1.0, "a"),
            Segment(1.0, 2.0, "b"),
            Segment(2.0, 3.0, "a"),
        ]
        self.assertEqual(len(_dedupe(segs)), 3)

    def test_empty(self):
        self.assertEqual(_dedupe([]), [])


if __name__ == "__main__":
    unittest.main()
