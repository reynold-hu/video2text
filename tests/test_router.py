"""URL 识别、短链展开、域名归一化的测试。"""

import unittest

from core import router


class TestExtractUrl(unittest.TestCase):
    def test_pulls_url_out_of_share_text(self):
        # 小红书 App 分享出来是一整段话，链接夹在中间
        text = "39 这个博主讲得真好 😆 http://xhslink.com/a/abc123 复制本条信息，打开【小红书】"
        self.assertEqual(router.extract_url(text), "http://xhslink.com/a/abc123")

    def test_plain_url_passes_through(self):
        url = "https://www.bilibili.com/video/BV1xx411c7mD"
        self.assertEqual(router.extract_url(url), url)

    def test_strips_trailing_punctuation(self):
        # 中文句号跟在链接后面很常见，不能带进 URL
        self.assertEqual(
            router.extract_url("看这个 https://b23.tv/abc。"),
            "https://b23.tv/abc",
        )

    def test_empty_input(self):
        self.assertEqual(router.extract_url(""), "")


class TestDetect(unittest.TestCase):
    def test_bilibili_variants(self):
        for url in [
            "https://www.bilibili.com/video/BV1xx411c7mD",
            "https://m.bilibili.com/video/BV1xx411c7mD",
            "https://b23.tv/abc",
        ]:
            self.assertEqual(router.detect(url), "bilibili", url)

    def test_youtube_variants(self):
        for url in [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        ]:
            self.assertEqual(router.detect(url), "youtube", url)

    def test_xiaohongshu_variants(self):
        for url in [
            "https://www.xiaohongshu.com/explore/abc123",
            "https://xhslink.com/a/xyz",
            "https://www.rednote.com/explore/abc123",
        ]:
            self.assertEqual(router.detect(url), "xiaohongshu", url)

    def test_unknown_platform_raises(self):
        with self.assertRaises(router.UnsupportedURL):
            router.detect("https://weibo.com/something")

    def test_domain_lookalike_is_not_matched(self):
        # 防止 notbilibili.com 被误判
        with self.assertRaises(router.UnsupportedURL):
            router.detect("https://notbilibili.com/video/x")


class TestNormalize(unittest.TestCase):
    def test_rednote_rewritten_to_xiaohongshu(self):
        # 小红书改名 rednote 后 yt-dlp 还不认（issue #16519）
        self.assertEqual(
            router.normalize("https://www.rednote.com/explore/abc"),
            "https://www.xiaohongshu.com/explore/abc",
        )

    def test_mobile_domains_normalized(self):
        self.assertEqual(
            router.normalize("https://m.bilibili.com/video/BV1xx"),
            "https://www.bilibili.com/video/BV1xx",
        )
        self.assertEqual(
            router.normalize("https://m.youtube.com/watch?v=x"),
            "https://www.youtube.com/watch?v=x",
        )


class TestResolve(unittest.TestCase):
    def test_resolve_returns_platform_and_url(self):
        platform, url = router.resolve("https://www.bilibili.com/video/BV1xx411c7mD")
        self.assertEqual(platform, "bilibili")
        self.assertIn("BV1xx411c7mD", url)

    def test_non_short_link_is_not_expanded(self):
        # expand() 只对短链发请求，普通链接必须原样返回（否则每条都要多一次网络往返）
        url = "https://www.bilibili.com/video/BV1xx411c7mD"
        self.assertEqual(router.expand(url), url)


if __name__ == "__main__":
    unittest.main()
