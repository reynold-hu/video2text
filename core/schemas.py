"""三平台字幕与本地转写结果的统一数据模型。

B站/YouTube 的现成字幕轨、小红书的本地 ASR 转写，最终都归一到这里，
下游的 writer 只认这一种结构，不需要知道数据是哪来的。
"""

from dataclasses import dataclass, field, asdict


@dataclass
class Segment:
    """一句字幕或转写结果，时间单位为秒。"""

    start: float
    end: float
    text: str


@dataclass
class Transcript:
    platform: str  # 'bilibili' | 'youtube' | 'xiaohongshu'
    title: str
    url: str
    author: str = ""
    created: str = ""
    segments: list[Segment] = field(default_factory=list)
    # 'subtitle' = 抓的现成字幕轨（秒出）；'asr' = 本地语音转写（慢）
    # 前端要把这个显著标出来，用户才知道这份文字可不可信
    source: str = "subtitle"
    extra: str = ""  # 小红书笔记正文等附注
    engine: str = ""  # 走 asr 时记录用的哪个引擎

    def plain_text(self) -> str:
        return "\n".join(s.text.strip() for s in self.segments if s.text.strip())

    def to_dict(self) -> dict:
        d = asdict(self)
        d["text"] = self.plain_text()
        d["duration"] = self.segments[-1].end if self.segments else 0.0
        return d
