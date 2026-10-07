"""mlx-whisper 引擎 —— Apple Silicon 上的默认选择。

对比过三家在 M 系列上的表现：mlx-whisper > whisper.cpp( Metal ) >> faster-whisper。
faster-whisper 的 CTranslate2 后端在 macOS 上用不了 Metal，会掉回 CPU，
实测同一段音频 mlx 的 large 模型比 faster-whisper 的 small 模型还快。

large-v3-turbo 是速度和准确率的平衡点：比 large-v3 快数倍，准确率损失很小。
"""

import os
from pathlib import Path

from ..schemas import Segment
from .base import ASRError, Engine, ProgressFn

# 模型可以换。中文内容建议保持 large-v3-turbo（准确率明显好于下面几个小模型），
# 想快速试跑或者省磁盘可以用 small / base / tiny。
# 换法：V2T_MLX_MODEL=mlx-community/whisper-small-mlx python app.py
MODEL = os.environ.get("V2T_MLX_MODEL", "mlx-community/whisper-large-v3-turbo")


class MLXWhisperEngine(Engine):
    name = "mlx"
    display = "mlx-whisper（快）"
    note = "Apple 芯片专用，速度最快"
    requires = ("mlx_whisper",)

    def transcribe(
        self, wav: Path, language: str | None = None, on_progress: ProgressFn = None
    ) -> list[Segment]:
        log = on_progress or (lambda _: None)

        try:
            import mlx_whisper
        except ImportError as e:
            raise ASRError(
                "mlx-whisper 没装上。装一下：uv pip install mlx-whisper"
            ) from e

        log(f"正在加载模型…（{MODEL.split('/')[-1]}，首次运行需下载，之后有缓存）")

        # 故意不用 initial_prompt 去压繁体：实测它会让 whisper 把整段解码成
        # 一个 segment（12 秒的话只剩 1 段，SRT 就没法用了）。繁简转换放到
        # 转写之后单独做，见 asr/base.py 的 to_simplified()。
        try:
            result = mlx_whisper.transcribe(
                str(wav),
                path_or_hf_repo=MODEL,
                language=language,
                verbose=None,
            )
        except Exception as e:
            raise ASRError(f"mlx-whisper 转写失败：{str(e)[:200]}") from e

        log("正在整理文本…")
        return [
            Segment(
                start=float(s.get("start", 0)),
                end=float(s.get("end", 0)),
                text=(s.get("text") or "").strip(),
            )
            for s in result.get("segments") or []
            if (s.get("text") or "").strip()
        ]
