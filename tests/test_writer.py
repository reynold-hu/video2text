"""输出格式的测试。参考实现是 bilibili-subtitle 的 MoreBtn.tsx / util.ts。"""

import unittest

from core.schemas import Segment, Transcript
from core.writer import (
    format_srt_time,
    format_time,
    format_vtt_time,
    render,
    safe_filename,
)


def sample() -> Transcript:
    return Transcript(
        platform="bilibili",
        title="测试/视频:第1集",
        url="https://example.com/x",
        author="某UP",
        created="2026-01-01",
        segments=[
            Segment(0.0, 5.4, "第一句"),
            Segment(65.2, 70.0, "第二句"),
            Segment(3725.5, 3730.0, "跨小时"),
        ],
    )


class TestFormatTime(unittest.TestCase):
    def test_under_one_hour_is_mm_ss(self):
        self.assertEqual(format_time(0), "00:00")
        self.assertEqual(format_time(65), "01:05")
        self.assertEqual(format_time(3599), "59:59")

    def test_over_one_hour_is_hh_mm_ss(self):
        self.assertEqual(format_time(3600), "01:00:00")
        self.assertEqual(format_time(3725), "01:02:05")

    def test_invalid_input(self):
        self.assertEqual(format_time(-5), "00:00")
        self.assertEqual(format_time(float("nan")), "00:00")


class TestFormatSrtTime(unittest.TestCase):
    def test_uses_comma_for_milliseconds(self):
        # SRT 规范要求毫秒用逗号，用成点号播放器会认不出来
        self.assertEqual(format_srt_time(5.4), "00:00:05,400")
        self.assertIn(",", format_srt_time(1.5))
        self.assertNotIn(".", format_srt_time(1.5))

    def test_zero_and_hours(self):
        self.assertEqual(format_srt_time(0), "00:00:00,000")
        self.assertEqual(format_srt_time(3725.5), "01:02:05,500")


class TestFormatVttTime(unittest.TestCase):
    def test_uses_dot_for_milliseconds(self):
        self.assertEqual(format_vtt_time(5.4), "00:00:05.400")
        self.assertIn(".", format_vtt_time(1.5))
        self.assertNotIn(",", format_vtt_time(1.5))


class TestSafeFilename(unittest.TestCase):
    def test_strips_path_separators_and_colons(self):
        self.assertNotIn("/", safe_filename("测试/视频:第1集"))
        self.assertNotIn(":", safe_filename("测试/视频:第1集"))

    def test_empty_falls_back(self):
        self.assertEqual(safe_filename(""), "transcript")
        self.assertEqual(safe_filename("   "), "transcript")

    def test_truncates_long_titles(self):
        self.assertLessEqual(len(safe_filename("啊" * 300)), 80)


class TestRender(unittest.TestCase):
    def test_header_has_title_url_author(self):
        _, body = render(sample(), "text")
        self.assertIn("测试/视频:第1集", body)
        self.assertIn("https://example.com/x", body)
        self.assertIn("某UP 2026-01-01", body)

    def test_text_is_one_line_per_segment(self):
        _, body = render(sample(), "text")
        self.assertIn("第一句\n第二句\n跨小时", body)

    def test_text_with_time_prefixes_timestamp(self):
        _, body = render(sample(), "textWithTime")
        self.assertIn("00:00 第一句", body)
        self.assertIn("01:05 第二句", body)
        self.assertIn("01:02:05 跨小时", body)

    def test_article_joins_with_commas(self):
        _, body = render(sample(), "article")
        self.assertIn("第一句, 第二句, 跨小时", body)

    def test_srt_numbering_starts_at_one_and_increments(self):
        _, body = render(sample(), "srt")
        self.assertTrue(body.startswith("1\n"))
        self.assertIn("\n2\n", body)
        self.assertIn("\n3\n", body)

    def test_srt_has_no_header(self):
        _, body = render(sample(), "srt")
        self.assertNotIn("某UP", body)
        self.assertTrue(body.startswith("1\n"))

    def test_vtt_starts_with_webvtt(self):
        _, body = render(sample(), "vtt")
        self.assertTrue(body.startswith("WEBVTT"))

    def test_extension_matches_format(self):
        self.assertTrue(render(sample(), "srt")[0].endswith(".srt"))
        self.assertTrue(render(sample(), "vtt")[0].endswith(".vtt"))
        self.assertTrue(render(sample(), "text")[0].endswith(".txt"))

    def test_unknown_format_raises(self):
        with self.assertRaises(ValueError):
            render(sample(), "docx")

    def test_notes_appended_only_when_present(self):
        t = sample()
        self.assertNotIn("笔记正文", render(t, "text")[1])
        t.extra = "这是笔记正文"
        self.assertIn("这是笔记正文", render(t, "text")[1])


if __name__ == "__main__":
    unittest.main()
