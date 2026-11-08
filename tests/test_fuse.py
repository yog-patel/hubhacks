"""Unit tests for fusing motion and FishSpotter boxes (detect.fuse_boxes) and heatmap peak finding."""
import numpy as np

from bluesight.detect import fuse_boxes
from bluesight.spotter import peaks

CFG = {"large_area": 4000}


def box(cx, cy, w=40, h=24, s=0.9):
    return [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, s]


def test_empty_inputs_pass_through():
    m = np.array([box(100, 100)], np.float32)
    assert len(fuse_boxes(m, np.zeros((0, 5), np.float32), CFG)) == 1
    assert len(fuse_boxes(np.zeros((0, 5), np.float32), m, CFG)) == 1


def test_merged_school_blob_is_split_by_spotter():
    blob = np.array([[0, 0, 60, 50, 0.8]], np.float32)  # small motion box (3000 px) holding 3 fish
    spot = np.array([box(10, 10), box(30, 25), box(50, 40)], np.float32)
    out = fuse_boxes(blob, spot, CFG)
    assert len(out) == 3  # blob replaced by the 3 spotter fish


def test_large_organism_kept_whole():
    crab = np.array([[0, 0, 200, 80, 0.9]], np.float32)  # 16000 px: a crab
    spot = np.array([box(50, 40), box(150, 40)], np.float32)  # spotter fires on parts of it
    out = fuse_boxes(crab, spot, CFG)
    assert len(out) == 1 and out[0][2] == 200


def test_motion_only_and_spotter_only_fish_both_kept():
    m = np.array([box(100, 100)], np.float32)
    s = np.array([box(500, 500)], np.float32)
    assert len(fuse_boxes(m, s, CFG)) == 2


def test_peaks_finds_local_maxima_above_threshold():
    h = np.zeros((20, 20), np.float32)
    h[5, 5], h[5, 6], h[15, 12] = 0.9, 0.5, 0.4
    pk = peaks(h, 0.3)
    got = {(int(x), int(y)) for x, y, _ in pk}
    assert got == {(5, 5), (12, 15)}
