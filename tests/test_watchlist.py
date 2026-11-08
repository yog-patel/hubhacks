"""Unit tests for the invasive-species watch list (bluesight.watchlist)."""
from bluesight import watchlist as W
from bluesight.db import DB

CFG = {"watch_list": {"species": [{"key": "european_green_crab", "common": "European green crab",
                                   "scientific": "Carcinus maenas", "aliases": ["green crab"]}]}}


def test_match_ignores_case_spaces_underscores_and_hyphens():
    for n in ("european_green_crab", "European Green Crab", "european-green  crab", "Carcinus maenas", "GREEN CRAB"):
        assert W.match(CFG, n)["key"] == "european_green_crab"
    assert W.match(CFG, "small_schooling_fish") is None and W.match(CFG, None) is None
    assert W.match({}, "european_green_crab") is None


def test_hits_only_known_tracks(tmp_path):
    db = DB(tmp_path / "t.db")
    rows = [("r", 1, 10.0, 20.0, 5, 0.6, 900.0, "known", "european_green_crab", 0.9, "[]", None),
            ("r", 2, 30.0, 45.0, 5, 0.6, 900.0, "known", "european_green_crab", 0.9, "[]", None),
            ("r", 3, 50.0, 55.0, 5, 0.6, 900.0, "uncertain", "european_green_crab", 0.7, "[]", None),
            ("r", 4, 1.0, 5.0, 5, 0.6, 900.0, "known", "small_schooling_fish", 0.9, "[]", None)]
    with db.tx() as c:
        c.executemany("INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    h = W.hits(CFG, db, "r")
    assert len(h) == 1 and h[0]["tracks"] == 2 and h[0]["first_s"] == 10.0 and h[0]["last_s"] == 45.0
