"""
timelapse_video.py
PURPOSE: Stitch timelapse JPEG frames into a video file.

WHY THIS EXISTS
---------------
The export used to go through imageio-ffmpeg, which ships and launches its own
87 MB ffmpeg.exe. A second unsigned executable inside the build is one of the
things that got a deployed one-folder build deleted by the lab's endpoint
security. OpenCV is already in the build for the camera and carries its own
FFmpeg as an in-process DLL, so the export uses cv2.VideoWriter instead.

H.264 is not available that way (OpenCV's FFmpeg needs Cisco's OpenH264 DLL
for it), so the formats offered are MPEG-4 Part 2 in .mp4 and Motion-JPEG in
.avi: the .avi files are larger but play everywhere.
"""

import logging
from typing import Callable, Optional, Sequence

import cv2

logger = logging.getLogger(__name__)

# Setting value -> (FourCC, file extension)
VIDEO_FORMATS = {
    "mp4": ("mp4v", ".mp4"),
    "avi": ("MJPG", ".avi"),
}


def write_timelapse(
    frame_files: Sequence[str],
    out_base: str,
    fps: int,
    fmt: str,
    progress: Optional[Callable[[int], None]] = None,
) -> str:
    """
    Write ``frame_files`` (in order) to ``out_base`` + the format's extension.

    Frames whose size differs from the first are resized to it. ``progress``
    is called with a percentage (ending at 100). Returns the output path.
    Raises ValueError for an unknown format or no frames, RuntimeError when the
    encoder cannot be opened or a frame cannot be read.
    """
    if fmt not in VIDEO_FORMATS:
        raise ValueError(f"Unknown video format {fmt!r}; expected one of {sorted(VIDEO_FORMATS)}")
    if not frame_files:
        raise ValueError("No timelapse frames to export.")

    fourcc, ext = VIDEO_FORMATS[fmt]
    out_path = out_base + ext

    first = cv2.imread(frame_files[0])
    if first is None:
        raise RuntimeError(f"Could not read frame {frame_files[0]}")
    height, width = first.shape[:2]

    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*fourcc),
                             max(1, int(fps)), (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"OpenCV could not open a {fmt} video writer for {out_path}")

    n = len(frame_files)
    try:
        for i, path in enumerate(frame_files):
            frame = first if i == 0 else cv2.imread(path)
            if frame is None:
                raise RuntimeError(f"Could not read frame {path}")
            if frame.shape[:2] != (height, width):
                frame = cv2.resize(frame, (width, height))
            writer.write(frame)
            if progress is not None and (i % 10 == 0 or i == n - 1):
                progress(int((i + 1) / n * 100))
    finally:
        writer.release()

    logger.info("Timelapse video written: %s (%d frames, %s)", out_path, n, fmt)
    return out_path
