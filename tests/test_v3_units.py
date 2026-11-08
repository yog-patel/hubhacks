"""v3 units: count check maths, survey/watch-list alerts, clarity words and the Excel export."""
import io

import pytest

from bluesight import countcheck as CC
from bluesight import survey as SV
from bluesight.count import UNKNOWN_LABEL, per_frame_counts, protocol_frame_times
from bluesight.db import DB
from bluesight.export import workbook_bytes


def cfg():
    return {"identify": {"V_MIN": 0.4}, "invertebrate_species": ["european_green_crab"],
            "species_candidates": [{"name": "mummichog", "common": "mummichog", "scientific": "Fundulus heteroclitus"},
                                   {"name": "european_green_crab", "common": "European green crab", "scientific": "Carcinus maenas"}],
            "expected_extra": ["small_schooling_fish"],
            "watch_list": [{"name": "european_green_crab", "common": "European green crab", "scientific": "Carcinus maenas",
                            "group": "invertebrate", "reason": "Invasive.", "temp_range_c": [5, 20]}]}


def report(species=("small_schooling_fish",)):
    subs = [{"subsample_t_s": 60.0 * i, "time": f"{i}:00", "frame_t_s": 60.0 * i, "visibility": 0.6,
             "total_fish_count": 10 + i, "invertebrate_count": 0, "small_schooling_fish": 10 + i} for i in range(3)]
    return {"run_id": "r1", "video_file": "v.mp4", "site": "T1-STAT2", "date": "2025-09-10",
            "window": {"start_s": 0, "end_s": 180, "duration_min": 3.0}, "protocol": {"subsample_interval_s": 60},
            "thresholds": {"V_MIN": 0.4}, "subsamples": subs, "MeanCount_total_fish": 11.0,
            "species": [{"label": s, "MaxN": 12, "MeanCount": 11.0, "MeanCount_all_sampled_frames": 9.0, "n_tracks": 5,
                         "confidence": 0.8, "verified_tracks": 0} for s in species],
            "registry_species": list(species), "visibility": {"mean": 0.6, "fraction_below_v_min": 0.0},
            "models": {"detector": "motion", "embedder": "bioclip"}}


def test_pct_difference_and_agreement():
    assert CC.pct_difference(0, 0) == 0
    assert CC.pct_difference(36, 34) == pytest.approx(2 / 35 * 100)
    assert CC.agreement([(10, 10), (5, 5)]) == 100
    assert CC.agreement([(8, 10), (10, 10)]) == pytest.approx(90.0)
    assert CC.agreement([]) is None


def test_protocol_frame_times_pick_busiest_frame():
    c = per_frame_counts([59.5, 60.0, 60.5], [59.5, 60.5, 60.5], ["a", "a", "a"])
    assert protocol_frame_times(c, [60.0], 1.0) == [60.5]


def test_checked_meancount_uses_human_counts(tmp_path):
    db = DB(tmp_path / "t.db")
    CC.ensure(db)
    rep = report()
    CC.save_check(db, "r1", 0.0, 0.0, "assisted", "A", 10, 0, [1, 2], 0, 8, 0)
    CC.save_check(db, "r1", 60.0, 60.0, "blind", "B", 11, 0, [], 0, 11, 0)
    s = CC.summary(rep, CC.checks(db, "r1"))
    assert s["n_checked"] == 2
    assert s["MeanCount_ai"] == pytest.approx(11.0)
    assert s["MeanCount_checked"] == pytest.approx((8 + 11 + 12) / 3)
    assert s["blind_agreement_pct"] == 100 and s["blind_frames_within_6pct"] == 1
    assert s["marks_removed"] == 2


def test_watch_and_range_and_new_arrival_alerts(tmp_path):
    db = DB(tmp_path / "t.db")
    c = cfg()
    rep = report(("small_schooling_fish", "european_green_crab", "black_drum"))
    al = SV.alerts(rep, db, c, {"water_temp_c": 22.0})
    levels = {(a["level"], a["species"]) for a in al}
    assert ("watch", "european_green_crab") in levels
    assert ("range", "european_green_crab") in levels          # 22 °C is above the 5-20 °C range
    assert ("new", "black_drum") in levels                     # not on the expected list
    assert not any(a["species"] == "small_schooling_fish" for a in al)
    assert not any(a["level"] == "range" for a in SV.alerts(rep, db, c, {"water_temp_c": 12.0}))


def test_watch_list_edits_override_seed(tmp_path):
    db = DB(tmp_path / "t.db")
    c = cfg()
    SV.save_watch(db, "european_green_crab", "European green crab", "Carcinus maenas", "invertebrate", "x", None, None,
                  False, "me")
    assert SV.watch_list(db, c) == []
    assert len(SV.watch_list(db, c, include_inactive=True)) == 1


def test_clarity_word_is_not_a_distance():
    c = cfg()
    assert SV.clarity_word(0.2, c) == "too murky to identify"
    assert SV.clarity_word(0.45, c) == "fair"
    assert SV.clarity_word(0.9, c) == "good"


def test_excel_export_has_protocol_columns(tmp_path):
    from openpyxl import load_workbook

    c = cfg()
    rep = report()
    rep["subsamples"][0][UNKNOWN_LABEL] = 2
    db = DB(tmp_path / "t.db")
    CC.save_check(db, "r1", 0.0, 0.0, "assisted", "A", 10, 0, [], 3, 13, 1)
    rows = CC.checks(db, "r1")
    wb = load_workbook(io.BytesIO(workbook_bytes(rep, c, {"water_temp_c": 14.5}, rows, CC.summary(rep, rows), [])))
    ws = wb["Subsamples"]
    head = [x.value for x in ws[1]]
    for col in ("Total Fish Count", "Invertebrate count", "Total species observed", UNKNOWN_LABEL, "Notes"):
        assert col in head
    assert ws.cell(2, head.index("Total Fish Count") + 1).value == 13      # the checked count replaces the AI's
    summary = {r[0].value: r[1].value for r in wb["Summary"].iter_rows()}
    assert summary["Water temperature (°C)"] == 14.5


def test_density_dot_map_and_motion_channels():
    import numpy as np

    from bluesight.density import PATCH, dot_map, motion_channels

    pts = np.array([[5, 5], [20, 5], [20, 6], [10_000, 5]], np.float32)  # last one is off the grid
    m = dot_map(pts, (4, 4))
    assert m.sum() == 3 and m[0, 0] == 1 and m[0, 1] == 2
    assert dot_map(pts, (4, 4), scale=2.0)[0, 2] == 2          # (40, 10) at 2x falls in patch column 2 (28-41 px)
    mc = motion_channels(None, (3, 5))
    assert mc.shape == (4, 3, 5) and mc.sum() == 0             # no video: zeros, "available" flag off
    z = np.zeros((3 * PATCH, 5 * PATCH), np.float16)
    z[:PATCH, :PATCH] = 10
    mc = motion_channels(z, (3, 5))
    assert mc[3].min() == 1 and mc[2, 0, 0] == 1 and mc[2, 2, 4] == 0
