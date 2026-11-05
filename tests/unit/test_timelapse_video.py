"""Timelapse export goes through OpenCV's in-process encoder, in MP4 or AVI.

The old export shelled out to the ffmpeg.exe bundled by imageio-ffmpeg; a
second unsigned executable in the build is what endpoint security deletes.
These tests write real files and read them back, so a format that silently
produces an empty or unreadable video fails here.
"""

import cv2
import numpy as np
import pytest

from t8_daq_system.data.timelapse_video import VIDEO_FORMATS, write_timelapse


def _frames(folder, n=5, size=(320, 240)):
    paths = []
    for i in range(n):
        img = np.full((size[1], size[0], 3), i * 40, np.uint8)
        path = folder / f"frame_{i:05d}.jpg"
        cv2.imwrite(str(path), img)
        paths.append(str(path))
    return paths


@pytest.mark.parametrize("fmt, ext", [("mp4", ".mp4"), ("avi", ".avi")])
def test_both_formats_write_a_readable_video_with_every_frame(tmp_path, fmt, ext):
    frames = _frames(tmp_path, n=5)
    out = write_timelapse(frames, str(tmp_path / "timelapse_x"), fps=10, fmt=fmt)

    assert out.endswith(ext)
    cap = cv2.VideoCapture(out)
    assert cap.isOpened()
    count = 0
    while True:
        ok, _ = cap.read()
        if not ok:
            break
        count += 1
    cap.release()
    assert count == 5


def test_offered_formats_are_mp4_and_avi():
    assert set(VIDEO_FORMATS) == {"mp4", "avi"}


def test_frames_of_a_different_size_are_resized_not_dropped(tmp_path):
    frames = _frames(tmp_path, n=2, size=(320, 240))
    odd = tmp_path / "frame_00009.jpg"
    cv2.imwrite(str(odd), np.zeros((100, 100, 3), np.uint8))
    out = write_timelapse(frames + [str(odd)], str(tmp_path / "t"), fps=10, fmt="avi")

    cap = cv2.VideoCapture(out)
    count = 0
    while cap.read()[0]:
        count += 1
    cap.release()
    assert count == 3


def test_progress_is_reported_up_to_100(tmp_path):
    seen = []
    write_timelapse(_frames(tmp_path, n=3), str(tmp_path / "t"), fps=10, fmt="mp4",
                    progress=seen.append)
    assert seen[-1] == 100


def test_unknown_format_is_refused(tmp_path):
    with pytest.raises(ValueError, match="format"):
        write_timelapse(_frames(tmp_path, n=1), str(tmp_path / "t"), fps=10, fmt="mkv")


def test_no_frames_is_refused(tmp_path):
    with pytest.raises(ValueError, match="frames"):
        write_timelapse([], str(tmp_path / "t"), fps=10, fmt="mp4")


def test_settings_dialog_offers_exactly_the_exportable_formats():
    from t8_daq_system.gui.settings_dialog import VIDEO_FORMAT_CHOICES
    assert set(VIDEO_FORMAT_CHOICES) == set(VIDEO_FORMATS)
