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

    def model_cached(self) -> bool | None:
        """权重是否已在本地缓存。只用本地文件判断，不会触发下载。

        注意不能只看 snapshot_download 是否成功 —— 那只看 snapshot 目录在不在，
        而下载中断时 config.json 这种小文件已经落地了，目录是存在的，权重却还是
        .incomplete。所以必须确实找到权重文件才算数。
        """
        from pathlib import Path

        try:
            from huggingface_hub import snapshot_download

            path = Path(snapshot_download(MODEL, local_files_only=True))
        except Exception:
            return False

        for f in path.rglob("*"):
            if f.is_file() and f.suffix in (".npz", ".safetensors", ".bin"):
                try:
                    if f.stat().st_size > 1_000_000:
                        return True
                except OSError:
                    continue
        return False

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
            raise ASRError(_friendly(e, MODEL)) from e

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


def _friendly(err: Exception, model: str) -> str:
    """首次使用要下模型，网络不好时最容易卡在这一步，报错要说清楚。"""
    text = str(err)
    low = text.lower()

    if "localentrynotfound" in low or "connection" in low or "timed out" in low:
        return (
            f"下载模型失败（{model}）。首次使用需要联网下载权重，"
            "网络不稳时会中断。可以重试，或者换国内镜像后重试：\n"
            "    HF_ENDPOINT=https://hf-mirror.com python app.py"
        )
    if "not found" in low and "repo" in low:
        return f"找不到模型 {model}。检查 V2T_MLX_MODEL 是否写对了。"
    return f"mlx-whisper 转写失败：{text[:200]}"
