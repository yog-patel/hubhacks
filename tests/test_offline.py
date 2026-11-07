"""Offline test: block every non-localhost connection, then run the FULL pipeline on a short clip.

The block here is independent of bluesight.netguard (it patches socket itself), so it also checks the guard.
Nothing is cached: a fresh database, registry and cache directory are used, so the detector runs, BioCLIP is loaded
from models/ and embeds the reference images and the clip's tracks, and evidence clips are written.

    python -m pytest tests/test_offline.py -s        (takes about 1-2 minutes on an Apple M5)
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import socket
import time
from pathlib import Path

import pytest

import bluesight  # noqa: F401  (sets offline env first)
from bluesight.config import ROOT, load_config
from bluesight.netguard import is_local

VIDEO = ROOT / "data" / "videos" / "T1-STAT2 411.MP4"
CLIP_START, CLIP_LEN = 1290.0, 12.0       # 21:30, the green crab next to the pole (demo half; nothing is tuned here)


@pytest.fixture
def no_network(monkeypatch):
    """Any connection or DNS lookup to a non-local host raises. Records every attempt."""
    attempts: list[str] = []
    real_connect, real_connect_ex, real_gai = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def host_of(addr):
        return addr[0] if isinstance(addr, tuple) else None

    def connect(self, addr):
        if self.family != getattr(socket, "AF_UNIX", -1) and not is_local(host_of(addr)):
            attempts.append(f"connect {addr}")
            raise OSError(f"test_offline: outbound connection to {addr} blocked")
        return real_connect(self, addr)

    def connect_ex(self, addr):
        if self.family != getattr(socket, "AF_UNIX", -1) and not is_local(host_of(addr)):
            attempts.append(f"connect_ex {addr}")
            raise OSError(f"test_offline: outbound connection to {addr} blocked")
        return real_connect_ex(self, addr)

    def gai(host, *a, **k):
        if not is_local(host):
            attempts.append(f"dns {host}")
            raise socket.gaierror(f"test_offline: DNS lookup of {host} blocked")
        return real_gai(host, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", gai)
    return attempts


def test_block_really_blocks(no_network):
    """Sanity check of the fixture itself: an internet request must fail."""
    import urllib.request

    with pytest.raises(Exception):
        urllib.request.urlopen("https://huggingface.co", timeout=3)
    assert no_network, "the fixture did not see the attempt"


@pytest.mark.skipif(not VIDEO.exists(), reason="survey video not present (data/videos/)")
def test_full_pipeline_offline(no_network, tmp_path):
    import bluesight.embed as embed_mod
    from bluesight.db import DB
    from bluesight.pipeline import run_video
    from bluesight.registry import Registry

    embed_mod._EMBEDDER = None  # force a fresh model load from disk inside the blocked section
    cfg = copy.deepcopy(load_config())
    for k in ("db_path", "runs_dir", "flags_dir", "registry_dir", "cache_dir", "logs_dir"):  # absolute paths win in path()
        cfg["paths"][k] = str((tmp_path / k).resolve())
    cfg["paths"]["db_path"] = str((tmp_path / "bluesight.db").resolve())
    (tmp_path / "logs_dir").mkdir()
    t0 = time.time()
    built = Registry(cfg, DB(cfg["paths"]["db_path"])).build_from_folders()
    assert built, "registry could not be built offline"
    rep = run_video(VIDEO, cfg, CLIP_START, CLIP_LEN, force=True)
    secs = time.time() - t0

    assert not rep["cached_detection"], "the test must run detection, not reuse a cache"
    assert rep["n_sampled_frames"] > 0 and rep["n_tracks"] > 0
    assert rep["offline"] is True
    assert rep["network"]["external_connection_attempts"] == 0, rep["network"]
    assert no_network == [], f"outbound attempts during the pipeline: {no_network}"
    assert Path(rep["annotated_video"]).exists()
    out = ROOT / "outputs" / "logs" / "offline_test.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"passed": True, "when": dt.datetime.now().isoformat(timespec="seconds"),
                               "blocked_attempts": len(no_network), "runtime_s": round(secs, 1),
                               "clip": f"{VIDEO.name} {CLIP_START:.0f}-{CLIP_START + CLIP_LEN:.0f} s",
                               "tracks": rep["n_tracks"], "frames": rep["n_sampled_frames"],
                               "guard": rep["network"], "energy": rep["energy"]}, indent=1, default=float))
