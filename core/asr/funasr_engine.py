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
    display = "FunASR（中文）"
    # 网上流传的"中文错字率只有 Whisper 一半"是它自己跑分集上的数字。
    # 实测真实视频上两者持平（14.2% vs 14.4%），速度却差约 4 倍，所以默认不选它。
    note = "只跑 CPU，实测比 mlx 慢约 4 倍；准确率与 mlx 基本持平"
    requires = ("funasr", "modelscope")

    def model_cached(self) -> bool | None:
        """三个模型（转写 / 断句 / 标点）都在本地才算就绪。

        ModelScope 的目录名很长且带版本，实际长这样：
            iic--speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch
            iic--speech_fsmn_vad_zh-cn-16k-common-pytorch
            iic--punc_ct-transformer_cn-en-common-vocab471067-large
        所以按关键词匹配而不是写死名字（注意用的是下划线，不是 fsmn-vad 那种连字符）。
        """
        import os
        import re
        from pathlib import Path

        cache = Path(
            os.environ.get("MODELSCOPE_CACHE", Path.home() / ".cache" / "modelscope")
        )
        models_dir = cache / "models"
        if not models_dir.is_dir():
            return False

        patterns = {
            "asr": re.compile(r"paraformer", re.I),
            "vad": re.compile(r"fsmn.*vad|vad.*fsmn", re.I),
            "punc": re.compile(r"punc", re.I),
        }

        for pattern in patterns.values():
            hit = False
            for d in models_dir.iterdir():
                if not (d.is_dir() and pattern.search(d.name)):
                    continue
                # 光有目录不算，得有实际权重文件（放权重的那层通常几十 MB 起）
                if any(
                    f.is_file() and f.stat().st_size > 1_000_000
                    for f in d.rglob("*")
                    if f.is_file()
                ):
                    hit = True
                    break
            if not hit:
                return False
        return True

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
