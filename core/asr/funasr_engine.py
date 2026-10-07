"""FunASR Paraformer 引擎 —— 中文准确率更高，但慢。

多份独立评测都指向同一个结论：中文 CER（字错率）Paraformer 约 10%，
Whisper large-v3 约 20% —— 差一倍。所以中文内容值得忍受它的慢。

代价：FunASR 的 torch 栈在 macOS 上用不了 Metal/MPS，只能跑 CPU。
另外它是中文/英文专用模型，其它语种别选它。
"""

from pathlib import Path

from ..schemas import Segment
from .base import ASRError, Engine, ProgressFn

# paraformer-zh 主力转写，fsmn-vad 切句，ct-punc 加标点
MODEL = "paraformer-zh"
VAD_MODEL = "fsmn-vad"
PUNC_MODEL = "ct-punc"


class FunASREngine(Engine):
    name = "funasr"
    display = "FunASR（中文准）"
    note = "中文错字率约为 Whisper 的一半，但只能跑 CPU，慢一些"
    requires = ("funasr", "modelscope")

    def __init__(self):
        self._model = None

    def _load(self, log):
        if self._model is not None:
            return self._model

        try:
            from funasr import AutoModel
        except ImportError as e:
            raise ASRError(
                "FunASR 没装上。装一下：uv pip install funasr modelscope"
            ) from e

        log("正在加载 FunASR 模型…（首次运行要下载模型，之后有缓存）")
        try:
            self._model = AutoModel(
                model=MODEL,
                vad_model=VAD_MODEL,
                punc_model=PUNC_MODEL,
                disable_update=True,
            )
        except Exception as e:
            raise ASRError(f"FunASR 模型加载失败：{str(e)[:200]}") from e
        return self._model

    def transcribe(
        self, wav: Path, language: str | None = None, on_progress: ProgressFn = None
    ) -> list[Segment]:
        log = on_progress or (lambda _: None)

        if language and not language.startswith(("zh", "en")):
            raise ASRError(
                f"FunASR 只支持中文和英文，这段音频识别为「{language}」。"
                "请改用 mlx-whisper 引擎。"
            )

        model = self._load(log)
        log("正在转写…")

        try:
            result = model.generate(
                input=str(wav),
                batch_size_s=300,
                sentence_timestamp=True,
            )
        except Exception as e:
            raise ASRError(f"FunASR 转写失败：{str(e)[:200]}") from e

        if not result:
            return []

        item = result[0]
        # sentence_timestamp=True 时给出逐句时间戳（毫秒）
        sentences = item.get("sentence_info")
        if sentences:
            return [
                Segment(
                    start=float(s.get("start", 0)) / 1000.0,
                    end=float(s.get("end", 0)) / 1000.0,
                    text=(s.get("text") or "").strip(),
                )
                for s in sentences
                if (s.get("text") or "").strip()
            ]

        # 没有逐句时间戳就退化成一段
        text = (item.get("text") or "").strip()
        return [Segment(start=0.0, end=0.0, text=text)] if text else []
