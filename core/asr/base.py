"""ASR 引擎的统一接口。

两个引擎（mlx-whisper / FunASR）的加载方式、调用签名、时间戳格式都不一样，
但对外只暴露 transcribe() 一个方法，pipeline 不需要知道用的是谁。

模型加载很贵（几百 MB 到 1.6 GB），所以引擎实例缓存起来复用。
"""

import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

from ..schemas import Segment

ProgressFn = Callable[[str], None] | None


class ASRError(RuntimeError):
    pass


class Engine(ABC):
    name: str = ""
    display: str = ""
    note: str = ""
    # 底层依赖的包名。真正 import 是懒加载在 transcribe() 里的（避免用 A 却被迫加载 B 的
    # 整个 torch 栈），所以可用性检测得单独查这个。
    requires: tuple[str, ...] = ()

    def model_cached(self) -> bool | None:
        """模型权重是否已在本地。

        包装上 ≠ 能用：首次使用还要下几百 MB 到 1.6 GB 的权重，网络不好时这一步
        很可能失败。返回 None 表示无法判断。
        """
        return None

    @abstractmethod
    def transcribe(
        self, wav: Path, language: str | None = None, on_progress: ProgressFn = None
    ) -> list[Segment]:
        """把 wav 转成带时间戳的句子列表。"""
        raise NotImplementedError


_instances: dict[str, Engine] = {}
_lock = threading.Lock()

_cc = None


def to_simplified(segments: list[Segment]) -> list[Segment]:
    """繁体转简体。

    Whisper 对中文默认倾向输出繁体（训练数据里繁体占比高）。不用提示词去压是因为
    那会破坏分段粒度（实测 12 秒的语音会被解码成一整段，SRT 就没法用了），
    所以改成转写完成后再转换。

    opencc 的 t2s 表对已经是简体的文本是空操作，重复调用无害。
    """
    global _cc
    if _cc is None:
        try:
            from opencc import OpenCC

            _cc = OpenCC("t2s")
        except ImportError:
            _cc = False  # 没装就跳过转换，不影响主流程

    if not _cc:
        return segments

    for seg in segments:
        seg.text = _cc.convert(seg.text)
    return segments


def get_engine(name: str) -> Engine:
    """按名字取引擎实例（单例，模型加载一次后常驻）。"""
    from .funasr_engine import FunASREngine
    from .mlx_engine import MLXWhisperEngine

    registry = {
        MLXWhisperEngine.name: MLXWhisperEngine,
        FunASREngine.name: FunASREngine,
    }
    if name not in registry:
        raise ASRError(f"未知的转写引擎：{name}")

    with _lock:
        if name not in _instances:
            _instances[name] = registry[name]()
        return _instances[name]


def available() -> list[dict]:
    """列出可用引擎，供前端下拉用。装不上的会被标出来而不是直接崩。"""
    import importlib.util

    from .funasr_engine import FunASREngine
    from .mlx_engine import MLXWhisperEngine

    out = []
    for cls in (MLXWhisperEngine, FunASREngine):
        missing = [p for p in cls.requires if importlib.util.find_spec(p) is None]
        entry = {
            "name": cls.name,
            "display": cls.display,
            "note": cls.note,
            "ready": not missing,
        }
        if missing:
            entry["error"] = "缺少依赖：" + "、".join(missing)
            entry["model_cached"] = None
        else:
            try:
                entry["model_cached"] = cls().model_cached()
            except Exception:
                entry["model_cached"] = None
        out.append(entry)
    return out
