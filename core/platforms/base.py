"""平台适配器的统一接口。

每个平台只需要回答一个问题：这个链接能不能直接抓到现成字幕？
能就返回 Transcript，不能就抛 NoSubtitle —— 由 pipeline 决定要不要落回 ASR。
"""

from abc import ABC, abstractmethod
from typing import Callable

from ..schemas import Transcript

ProgressFn = Callable[[str], None] | None


class NoSubtitle(Exception):
    """该视频确实没有字幕轨，可以落回 ASR 转写。

    很多用户会以为是工具坏了，所以 reason 要说清楚原因。
    meta 用来把已经拿到的元信息（标题/作者/正文）带给 ASR 分支，
    避免为了拿标题再解析一遍页面。
    """

    def __init__(self, reason: str, meta: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.meta = meta or {}


class Unsupported(Exception):
    """这个链接本身就没法处理，别浪费时间走 ASR。

    比如小红书的图文笔记 —— 没有音轨，转写也从无到有。
    """


class Platform(ABC):
    name: str = ""
    display: str = ""

    @abstractmethod
    def fetch(self, url: str, on_progress: ProgressFn = None) -> Transcript:
        """抓现成字幕。拿不到就抛 NoSubtitle。"""
        raise NotImplementedError
