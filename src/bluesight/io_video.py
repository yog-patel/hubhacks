"""Video I/O: metadata, sampling frames at the configured fps, writing H.264 clips."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np

from .logs import get_logger

log = get_logger("io_video")

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}


@dataclass
class VideoInfo:
    """Basic metadata for a video file."""

    path: str
    fps: float
    n_frames: int
    width: int
    height: int

    @property
    def duration_s(self) -> float:
        return self.n_frames / self.fps if self.fps else 0.0


def video_info(path: str | Path) -> VideoInfo:
    """Read fps, frame count and resolution. Raises IOError if the file can't be opened."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise IOError(f"Cannot open video: {path}")
    info = VideoInfo(
        path=str(path),
        fps=float(cap.get(cv2.CAP_PROP_FPS)) or 30.0,
        n_frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    )
    cap.release()
    return info


def iter_sampled_frames(
    path: str | Path, sample_fps: float, start_s: float = 0.0, end_s: float | None = None
) -> Iterator[tuple[int, float, np.ndarray]]:
    """Yield (frame_index, time_s, full-res BGR frame) at ``sample_fps`` between start_s and end_s.

    Decodes sequentially (grab without retrieve for skipped frames), which is much
    cheaper than seeking for every sample in long-GOP HEVC footage.
    """
    info = video_info(path)
    end_s = info.duration_s if end_s is None else min(end_s, info.duration_s)
    cap = cv2.VideoCapture(str(path))
    start_idx = int(round(start_s * info.fps))
    if start_idx > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_idx)
    step = info.fps / sample_fps
    next_t = start_idx
    idx = start_idx
    end_idx = int(end_s * info.fps)
    while idx < end_idx:
        if idx >= int(round(next_t)):
            ok, frame = cap.read()
            if not ok:
                log.warning("Read failed at frame %d of %s", idx, path)
                break
            yield idx, idx / info.fps, frame
            next_t += step
        else:
            if not cap.grab():
                break
        idx += 1
    cap.release()


def read_frame_at(path: str | Path, t_s: float) -> np.ndarray | None:
    """Read a single frame at time t_s (seconds)."""
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_MSEC, t_s * 1000.0)
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None


def resize_width(img: np.ndarray, width: int) -> tuple[np.ndarray, float]:
    """Resize to a target width, returning (image, scale) where scale = new/old."""
    h, w = img.shape[:2]
    if w == width:
        return img, 1.0
    s = width / w
    return cv2.resize(img, (width, int(round(h * s))), interpolation=cv2.INTER_AREA), s


class VideoWriter:
    """Browser-playable H.264 writer.

    Uses Apple's hardware encoder (h264_videotoolbox) through PyAV when available,
    then libx264 (GPL, via PyAV's bundled FFmpeg), and finally OpenCV's mp4v as a
    last resort (mp4v may not play inside a web browser).
    """

    def __init__(self, path: str | Path, fps: float, width: int, height: int) -> None:
        self.path = str(path)
        self.width, self.height = width - width % 2, height - height % 2
        self._av = None
        self._cv = None
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        try:
            import av  # imported lazily: PyAV and OpenCV each bundle FFmpeg

            for codec in ("h264_videotoolbox", "libx264", "h264"):
                try:
                    cont = av.open(self.path, mode="w")
                    stream = cont.add_stream(codec, rate=int(round(fps)) or 1)
                    stream.width, stream.height = self.width, self.height
                    stream.pix_fmt = "yuv420p"
                    if codec == "h264_videotoolbox":
                        stream.bit_rate = 4_000_000
                    stream.codec_context.open()
                    self._av = (cont, stream)
                    self.codec = codec
                    break
                except Exception as exc:  # try the next encoder
                    log.info("encoder %s unavailable: %s", codec, exc)
                    try:
                        cont.close()
                    except Exception:
                        pass
        except ImportError:
            log.warning("PyAV not installed; falling back to OpenCV mp4v")
        if self._av is None:
            self.codec = "mp4v"
            self._cv = cv2.VideoWriter(self.path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (self.width, self.height))

    def write(self, frame_bgr: np.ndarray) -> None:
        """Append one BGR frame (resized to the writer size if needed)."""
        if frame_bgr.shape[1] != self.width or frame_bgr.shape[0] != self.height:
            frame_bgr = cv2.resize(frame_bgr, (self.width, self.height))
        if self._av:
            import av

            cont, stream = self._av
            vf = av.VideoFrame.from_ndarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB), format="rgb24")
            for pkt in stream.encode(vf):
                cont.mux(pkt)
        else:
            self._cv.write(frame_bgr)

    def close(self) -> None:
        """Flush and close the file."""
        if self._av:
            cont, stream = self._av
            for pkt in stream.encode():
                cont.mux(pkt)
            cont.close()
            self._av = None
        if self._cv is not None:
            self._cv.release()
            self._cv = None

    def __enter__(self) -> "VideoWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
