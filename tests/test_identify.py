"""identify: decision rule, visibility gate, top-3, merging (synthetic embeddings)."""
import numpy as np
import pytest

from bluesight.identify import (KNOWN, auto_reject, LOW_VIS, UNCERTAIN, UNFAMILIAR, Thresholds, classify_track,
                                decide_status, merge_flagged, select_best, top_matches)

TH = Thresholds(T_KNOWN=0.8, T_UNKNOWN=0.6, V_MIN=0.3, MIN_FRAMES=3, MIN_AREA=100)


def unit(v):
    v = np.asarray(v, np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture
def registry():
    names = ["cod", "flounder", "herring", "crab"]
    protos = np.eye(4, 8, dtype=np.float32)
    return names, protos


def test_known_uncertain_unfamiliar(registry):
    names, P = registry
    assert classify_track(unit([1, 0.1, 0, 0, 0, 0, 0, 0]), 0.9, 10, 500, names, P, TH).status == KNOWN
    r = classify_track(unit([1, 0.9, 0, 0, 0.3, 0, 0, 0]), 0.9, 10, 500, names, P, TH)
    assert r.status == UNCERTAIN and r.species == "cod"
    r = classify_track(unit([0, 0, 0, 0, 1, 1, 0, 0]), 0.9, 10, 500, names, P, TH)
    assert r.status == UNFAMILIAR and r.species is None


def test_visibility_gate_never_flags_murky_blobs(registry):
    names, P = registry
    novel = unit([0, 0, 0, 0, 0, 0, 1, 0])  # would be "unfamiliar" in clear water
    assert classify_track(novel, 0.9, 10, 500, names, P, TH).status == UNFAMILIAR
    assert classify_track(novel, 0.1, 10, 500, names, P, TH).status == LOW_VIS   # murky
    assert classify_track(novel, 0.9, 2, 500, names, P, TH).status == LOW_VIS    # too short
    assert classify_track(novel, 0.9, 10, 50, names, P, TH).status == LOW_VIS    # too small
    assert classify_track(None, 0.9, 10, 500, names, P, TH).status == LOW_VIS    # no crops


def test_threshold_edges():
    assert decide_status(0.8, 0.9, 5, 200, TH) == KNOWN
    assert decide_status(0.7999, 0.9, 5, 200, TH) == UNCERTAIN
    assert decide_status(0.6, 0.9, 5, 200, TH) == UNCERTAIN
    assert decide_status(0.5999, 0.9, 5, 200, TH) == UNFAMILIAR
    assert decide_status(0.99, 0.2999, 5, 200, TH) == LOW_VIS


def test_top3_sorted(registry):
    names, P = registry
    t = top_matches(unit([0.2, 0.9, 0.5, 0.1, 0, 0, 0, 0]), names, P, 3)
    assert [m["species"] for m in t] == ["flounder", "herring", "cod"]
    assert t[0]["similarity"] >= t[1]["similarity"] >= t[2]["similarity"]


def test_empty_registry_flags_as_unfamiliar():
    r = classify_track(unit([1, 0, 0]), 0.9, 10, 500, [], np.zeros((0, 3), np.float32), TH)
    assert r.status == UNFAMILIAR and r.top3 == []


def test_merge_similar_flags():
    rng = np.random.default_rng(0)
    a, b = unit(rng.normal(size=16)), unit(rng.normal(size=16))
    embs = np.stack([unit(a + 0.01 * rng.normal(size=16)), unit(b), unit(a + 0.01 * rng.normal(size=16))])
    groups = merge_flagged(["t1", "t2", "t3"], embs, 0.9)
    assert sorted(map(sorted, groups)) == [["t1", "t3"], ["t2"]]


def test_select_best_crops():
    assert select_best([(1, "a"), (5, "b"), (3, "c")], 2) == ["b", "c"]


def test_auto_reject_only_suppresses_flagged_items_like_rejected_ones():
    pole = unit([0, 0, 0, 0, 0, 0, 0, 1])
    rejected = np.stack([pole])
    near_pole = unit([0, 0, 0, 0, 0, 0, 0.1, 1])
    assert auto_reject(UNFAMILIAR, near_pole, 0.3, rejected, 0.9)
    assert not auto_reject(KNOWN, near_pole, 0.95, rejected, 0.9)          # known species never touched
    assert not auto_reject(UNCERTAIN, unit([1, 0, 0, 0, 0, 0, 0, 0]), 0.7, rejected, 0.9)
    assert not auto_reject(UNFAMILIAR, near_pole, 0.3, None, 0.9)          # nothing rejected yet
