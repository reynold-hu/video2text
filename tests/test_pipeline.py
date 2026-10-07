"""流水线编排的测试。

这是整个工具的业务逻辑所在：「先试现成字幕，没有才本地转写」。
网络、平台、ASR 全部被桩掉，只验证编排决策是否正确。
"""

import unittest
from pathlib import Path
from unittest import mock

from core import pipeline
from core.platforms.base import NoSubtitle, Unsupported
from core.schemas import Segment, Transcript

FAKE_WAV = Path("/tmp/fake/v2t.wav")

SUB_TITLES = [
    Segment(0.0, 1.0, "字幕第一句"),
    Segment(1.0, 2.0, "字幕第二句"),
]

ASR_SEGMENTS = [
    Segment(0.0, 1.0, "转写第一句"),
]


def subtitle_transcript() -> Transcript:
    return Transcript(
        platform="bilibili",
        title="来自字幕",
        url="https://example.com/v",
        author="UP",
        segments=SUB_TITLES,
        source="subtitle",
    )


class FakePlatform:
    """可配置行为的平台桩。"""

    def __init__(self, behavior: str):
        self.behavior = behavior
        self.fetch_calls = 0

    def fetch(self, url, on_progress=None):
        self.fetch_calls += 1
        if self.behavior == "subtitle":
            return subtitle_transcript()
        if self.behavior == "nosubtitle":
            raise NoSubtitle("没有字幕轨", meta={
                "title": "来自转写",
                "author": "某作者",
                "created": "2026-01-01",
                "extra": "笔记正文内容",
            })
        raise Unsupported("这是图文笔记，没法转写")


def fake_engine(segments=None, error=None):
    class E:
        name = "fake"
        display = "假引擎"

        def transcribe(self, wav, language=None, on_progress=None):
            if error:
                raise error
            return list(segments if segments is not None else ASR_SEGMENTS)

    return E()


class PipelineTestCase(unittest.TestCase):
    """统一装上 router / platform / audio / asr 的桩。"""

    def setUp(self):
        self.audio_prepare = mock.patch.object(pipeline.audio, "prepare", return_value=FAKE_WAV)
        self.audio_cleanup = mock.patch.object(pipeline.audio, "cleanup")
        self.m_prepare = self.audio_prepare.start()
        self.m_cleanup = self.audio_cleanup.start()
        self.addCleanup(self.audio_prepare.stop)
        self.addCleanup(self.audio_cleanup.stop)

    def install(self, behavior, engine=None):
        platform = FakePlatform(behavior)
        m = mock.patch.object(pipeline, "_get_platform", return_value=platform)
        m.start()
        self.addCleanup(m.stop)
        if engine is not None:
            me = mock.patch.object(pipeline.asr, "get_engine", return_value=engine)
            me.start()
            self.addCleanup(me.stop)
        return platform


class TestSubtitlePath(PipelineTestCase):
    def test_returns_transcript_without_touching_audio(self):
        self.install("subtitle")
        t = pipeline.run("https://www.bilibili.com/video/BV1xx411c7mD")
        self.assertEqual(t.source, "subtitle")
        self.assertEqual(len(t.segments), 2)
        # 有字幕就绝不该下载音频 —— 这是整个设计的核心
        self.m_prepare.assert_not_called()

    def test_reports_progress(self):
        self.install("subtitle")
        seen = []
        pipeline.run("https://www.bilibili.com/video/BV1xx411c7mD", on_progress=seen.append)
        self.assertTrue(any("B站" in s for s in seen), seen)
        self.assertTrue(any("完成" in s for s in seen), seen)


class TestASRFallback(PipelineTestCase):
    def test_falls_back_and_carries_metadata(self):
        self.install("nosubtitle", fake_engine())
        t = pipeline.run("https://www.xiaohongshu.com/explore/abc")
        self.assertEqual(t.source, "asr")
        self.assertEqual(t.engine, "mlx")
        self.assertEqual(len(t.segments), 1)
        # NoSubtitle 里带的元信息要接住，否则标题作者全丢
        self.assertEqual(t.title, "来自转写")
        self.assertEqual(t.author, "某作者")
        self.assertEqual(t.created, "2026-01-01")
        self.assertEqual(t.extra, "笔记正文内容")

    def test_downloads_audio_and_cleans_up(self):
        self.install("nosubtitle", fake_engine())
        pipeline.run("https://www.xiaohongshu.com/explore/abc")
        self.m_prepare.assert_called_once()
        # 音频可能几百 MB，不管成功失败都要删
        self.m_cleanup.assert_called_once()

    def test_passes_site_to_audio_download(self):
        # 站点要传下去，否则挑浏览器登录态时会拿错
        self.install("nosubtitle", fake_engine())
        pipeline.run("https://www.xiaohongshu.com/explore/abc")
        args, kwargs = self.m_prepare.call_args
        self.assertEqual(kwargs.get("site"), "xiaohongshu")

    def test_cleans_up_even_when_transcription_fails(self):
        from core.asr import ASRError

        self.install("nosubtitle", fake_engine(error=ASRError("模型炸了")))
        with self.assertRaises(pipeline.PipelineError):
            pipeline.run("https://www.xiaohongshu.com/explore/abc")
        self.m_cleanup.assert_called_once()

    def test_simplified_conversion_applied(self):
        traditional = [Segment(0.0, 1.0, "歡迎來到這個視頻")]
        self.install("nosubtitle", fake_engine(traditional))
        t = pipeline.run("https://www.xiaohongshu.com/explore/abc")
        self.assertNotIn("歡", t.segments[0].text)
        self.assertIn("欢迎", t.segments[0].text)

    def test_default_engine_is_mlx(self):
        self.install("nosubtitle", fake_engine())
        t = pipeline.run("https://www.xiaohongshu.com/explore/abc")
        self.assertEqual(t.engine, "mlx")


class TestErrorHandling(PipelineTestCase):
    def test_unsupported_does_not_try_asr(self):
        self.install("unsupported")
        with self.assertRaises(pipeline.PipelineError):
            pipeline.run("https://www.xiaohongshu.com/explore/abc")
        # 图文笔记没有音轨，下载音频纯属浪费时间
        self.m_prepare.assert_not_called()

    def test_unknown_url_raises_pipeline_error(self):
        with self.assertRaises(pipeline.PipelineError):
            pipeline.run("https://weibo.com/something")

    def test_audio_error_becomes_pipeline_error(self):
        from core.audio import AudioError

        self.install("nosubtitle", fake_engine())
        self.m_prepare.side_effect = AudioError("下载不到音频")
        with self.assertRaises(pipeline.PipelineError) as ctx:
            pipeline.run("https://www.xiaohongshu.com/explore/abc")
        self.assertIn("下载不到音频", str(ctx.exception))

    def test_asr_error_becomes_pipeline_error(self):
        from core.asr import ASRError

        self.install("nosubtitle", fake_engine(error=ASRError("引擎不可用")))
        with self.assertRaises(pipeline.PipelineError) as ctx:
            pipeline.run("https://www.xiaohongshu.com/explore/abc")
        self.assertIn("引擎不可用", str(ctx.exception))

    def test_empty_transcription_is_an_error(self):
        self.install("nosubtitle", fake_engine([]))
        with self.assertRaises(pipeline.PipelineError) as ctx:
            pipeline.run("https://www.xiaohongshu.com/explore/abc")
        self.assertIn("为空", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
