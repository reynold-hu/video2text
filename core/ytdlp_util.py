"""yt-dlp 的共用配置。

yt-dlp 默认会把报错直接打到 stderr。我们所有的失败路径都已经捕获异常、
转换成给用户看的中文提示了（见 audio.py 和 platforms/xiaohongshu.py 的 _friendly），
所以它再打一遍纯属噪音 —— 会污染服务端日志和测试输出。
"""


class QuietLogger:
    """吞掉 yt-dlp 的输出。真正的错误仍然通过异常抛出，不丢信息。"""

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


def base_opts() -> dict:
    """所有 yt-dlp 调用共用的基础配置。"""
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": QuietLogger(),
    }
