"""小红书适配器的测试。

这里的重点不是"能否解析成功"（那要靠真实链接，测不了），
而是**失败时给出的提示是否准确** —— 之前就是这里误导过。
"""

import unittest

from core.platforms.xiaohongshu import _friendly

# yt-dlp 在页面没有笔记数据时抛的真实报错
NO_FORMATS = (
    "ERROR: [XiaoHongShu] 6ac3474a000000000202a171: No video formats found!; "
    "please report this issue on https://github.com/yt-dlp/yt-dlp/issues"
)


class TestFriendlyErrors(unittest.TestCase):
    def test_no_formats_explains_token_expiry(self):
        msg = _friendly(NO_FORMATS, "https://x")
        # 这是最常见的失败原因，提示里必须说到 token 或风控
        self.assertTrue("xsec_token" in msg or "风控" in msg, msg)
        # 并且要给出可操作的建议
        self.assertIn("重新分享", msg)

    def test_no_formats_does_not_claim_image_note(self):
        # 原来的措辞说"可能是图文笔记"，实测下来这是误导 ——
        # 图文只是可能之一，且远不如 token 过期常见
        msg = _friendly(NO_FORMATS, "https://x")
        self.assertNotIn("可能是图文笔记、私密笔记", msg)

    def test_unsupported_url_mentions_full_link(self):
        msg = _friendly("ERROR: Unsupported URL: https://xhslink.com/x", "https://x")
        self.assertIn("分享链接", msg)

    def test_not_found(self):
        msg = _friendly("ERROR: HTTP Error 404: Not Found", "https://x")
        self.assertIn("不存在", msg)

    def test_unknown_error_still_returns_something_readable(self):
        msg = _friendly("Some totally unexpected failure\nsecond line", "https://x")
        self.assertTrue(msg)
        # 只取第一行，不要把整个堆栈倒给用户
        self.assertNotIn("\n", msg)


class TestFriendlyIsUsed(unittest.TestCase):
    """确认异常路径真的走了 _friendly，而不是把原始报错漏出去。"""

    def test_extract_wraps_errors(self):
        from core.platforms.xiaohongshu import XiaohongshuPlatform
        from core.platforms.base import Unsupported

        with self.assertRaises(Unsupported) as ctx:
            # 这个 URL 不是笔记页，yt-dlp 会拒绝
            XiaohongshuPlatform._extract("https://www.xiaohongshu.com/user/profile/nobody")
        self.assertTrue(str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
