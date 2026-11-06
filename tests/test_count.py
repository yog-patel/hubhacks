"""count: MaxN, MeanCount, protocol subsampling, visibility summary."""
import pandas as pd
import pytest

from bluesight.count import (UNKNOWN_LABEL, count_label, maxn, meancount, per_frame_counts, protocol_counts,
                             subsample_points, visibility_summary)


def make_counts():
    times = [0.0, 0.5, 1.0, 1.5, 2.0]
    det_t = [0.0, 0.0, 0.5, 1.0, 1.0, 1.0, 2.0]
    det_l = ["cod", "cod", "cod", "cod", "cod", "crab", "crab"]
    return per_frame_counts(times, det_t, det_l)


def test_per_frame_counts_include_empty_frames():
    c = make_counts()
    assert list(c.index) == [0.0, 0.5, 1.0, 1.5, 2.0]
    assert c.loc[1.5].sum() == 0


def test_maxn_and_meancount():
    c = make_counts()
    assert maxn(c) == {"cod": 2, "crab": 1}
    assert meancount(c)["cod"] == pytest.approx((2 + 1 + 2 + 0 + 0) / 5)
    assert meancount(c)["crab"] == pytest.approx(2 / 5)


def test_protocol_subsamples_15_points_for_15_minutes():
    pts = subsample_points(60, 960, 60)
    assert len(pts) == 15 and pts[0] == 60 and pts[-1] == 900


def test_protocol_counts_take_best_frame_within_half_second():
    c = make_counts()
    pc = protocol_counts(c, [0.5, 1.5], window_s=1.0)
    # at 0.5 the window covers 0.0..1.0 -> frame 1.0 has 3 animals
    assert pc.loc[0.5].sum() == 3
    # at 1.5 the window covers 1.0..2.0 -> frame 1.0 again
    assert pc.loc[1.5].sum() == 3


def test_poor_visibility_is_reported_not_hidden():
    v = visibility_summary([0.1, 0.2, 0.8, 0.9], v_min=0.3)
    assert v["fraction_below_v_min"] == 0.5


def test_count_labels():
    assert count_label("known", "cod") == "cod"
    assert count_label("uncertain", "cod").startswith("Unconfirmed")
    assert count_label("unidentified_low_visibility", None) == UNKNOWN_LABEL
    assert count_label("unfamiliar", None, persistent=False) is None   # transient blobs are not counted
    assert count_label("rejected", None) is None
