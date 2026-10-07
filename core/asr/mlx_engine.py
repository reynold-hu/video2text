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
DEFAULT_REPO = "mlx-community/whisper-large-v3-turbo"

# 备用位置：直接用 curl 之类把权重拉到这个普通目录（不走 HuggingFace 的缓存结构）。
# 网络不稳时 huggingface_hub 的整体快照下载很容易整个失败，而单文件断点续传能磨下来。
LOCAL_DIR = Path.home() / ".cache" / "video2text" / "models" / "whisper-large-v3-turbo"

_WEIGHT_SUFFIXES = (".npz", ".safetensors", ".bin")


# 最小的 whisper MLX 模型（tiny）也有 75 MB。用 50 MB 当门槛，
# 既能排除只下了个开头的残file，也不会误伤任何真实模型。
_MIN_WEIGHT_BYTES = 50 * 1024 * 1024


def _has_weights(path: Path) -> bool:
    """目录里有没有真正下完的权重文件。

    光看目录存在不够 —— 下载中断时会留下只有小配置文件的目录，看起来"有"其实用不了。
    所以要求：文件名不带 .incomplete / .part 这类未完成标记，且体积过得了最低门槛。
    """
    if not path.is_dir():
        return False
    for f in path.rglob("*"):
        if not f.is_file() or f.suffix not in _WEIGHT_SUFFIXES:
            continue
        if f.name.endswith((".incomplete", ".part")):
            continue
        try:
            if f.stat().st_size >= _MIN_WEIGHT_BYTES:
                return True
        except OSError:
            continue
    return False


def resolve_model() -> str:
    """决定用哪个模型：环境变量 > 手动下载的本地目录 > HuggingFace 仓库。

    每次调用时判定，而不是在导入时定死 —— 模型是可以在运行期间下好的。
    """
    env = os.environ.get("V2T_MLX_MODEL")
    if env:
        return env
    if _has_weights(LOCAL_DIR):
        return str(LOCAL_DIR)
    return DEFAULT_REPO


class MLXWhisperEngine(Engine):
    name = "mlx"
    display = "mlx-whisper（快）"
    note = "Apple 芯片专用，速度最快"
    requires = ("mlx_whisper",)

    def model_cached(self) -> bool | None:
        """权重是否已在本地。只用本地文件判断，不会触发下载。

        注意不能只看 snapshot_download 是否成功 —— 那只看 snapshot 目录在不在，
        而下载中断时 config.json 这种小文件已经落地了，目录是存在的，权重却还是
        .incomplete。所以必须确实找到权重文件才算数。
        """
        model = resolve_model()

        # 手动下载到普通目录的情况
        local = Path(model)
        if local.exists():
            return _has_weights(local)

        try:
            from huggingface_hub import snapshot_download

            path = Path(snapshot_download(model, local_files_only=True))
        except Exception:
            return False
        return _has_weights(path)

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

        model = resolve_model()
        log(f"正在加载模型…（{Path(model).name}，首次运行需下载，之后有缓存）")

        # 故意不用 initial_prompt 去压繁体：实测它会让 whisper 把整段解码成
        # 一个 segment（12 秒的话只剩 1 段，SRT 就没法用了）。繁简转换放到
        # 转写之后单独做，见 asr/base.py 的 to_simplified()。
        try:
            result = mlx_whisper.transcribe(
                str(wav),
                path_or_hf_repo=model,
                language=language,
                verbose=None,
            )
        except Exception as e:
            raise ASRError(_friendly(e, model)) from e

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
