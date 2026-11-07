"""Shared app state: config, database, registry, run lookup and the sidebar."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import numpy as np
import streamlit as st

from bluesight.config import load_config, path, resolve_device
from bluesight.db import DB
from bluesight.registry import Registry

from . import theme

PAGES: dict = {}  # url slug -> st.Page, filled in by app/streamlit_app.py
MOCK_PATHS = {"db_path": "outputs/mock/bluesight.db", "runs_dir": "outputs/mock/runs",
              "flags_dir": "outputs/mock/flags", "registry_dir": "outputs/mock/registry"}


@st.cache_resource
def base_config() -> dict:
    return load_config()


@st.cache_resource
def device_name() -> str:
    return resolve_device(base_config())


@st.cache_resource
def hardware() -> str:
    from bluesight.pipeline import hardware_string

    return hardware_string(device_name())


def source() -> str:
    return st.session_state.get("data_source", "Survey results")


def cfg() -> dict:
    """Real outputs, or the mock outputs from scripts/make_mock_data.py (for UI work without models)."""
    c = copy.deepcopy(base_config())
    if source() == "Mock data":
        for k, v in MOCK_PATHS.items():
            c["paths"][k] = v
    return c


def db() -> DB:
    if "_db" not in st.session_state or st.session_state.get("_db_src") != source():
        st.session_state["_db"] = DB(path(cfg(), "db_path"))
        st.session_state["_db_src"] = source()
    return st.session_state["_db"]


@st.cache_resource
def embedder_resource():
    from bluesight.embed import get_embedder

    return get_embedder(base_config())


class MockEmbedder:
    """Mean-colour embedder so mock approvals never load a model."""

    name, version = "mock", "mock"

    def embed_images(self, ims):
        v = np.array([[*im.reshape(-1, 3).mean(0), 1.0, 0, 0, 0, 0] for im in ims], np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)


def registry(read_only: bool = False) -> Registry:
    emb = MockEmbedder() if (source() == "Mock data" or read_only) else embedder_resource()
    return Registry(cfg(), db(), emb)


def reviewer() -> str:
    return st.session_state.get("reviewer", "").strip()


def list_runs() -> list[dict]:
    rows = db().q("SELECT * FROM runs ORDER BY started_at DESC")
    return [r for r in rows if r["report_path"] and Path(r["report_path"]).exists()]


def load_report(run: dict) -> dict:
    return json.loads(Path(run["report_path"]).read_text())


def fmt_t(s: float) -> str:
    """Seconds -> m:ss (video time, as a biologist reads it off the player)."""
    s = max(0.0, float(s))
    return f"{int(s // 60)}:{int(s % 60):02d}"


def run_label(r: dict) -> str:
    return f"{r['video_file']} · {fmt_t(r['start_s'])}–{fmt_t(r['end_s'])} · analysed {r['started_at'].replace('T', ' ')[:16]}"


def pending_count() -> int:
    return db().q("SELECT COUNT(*) n FROM flags WHERE review_decision IS NULL")[0]["n"]


def offline_mode() -> bool:
    return os.environ.get("HF_HUB_OFFLINE") == "1" and os.environ.get("TRANSFORMERS_OFFLINE") == "1"


def local_badge(compact: bool = False) -> str:
    """'Running locally on <device>' badge; amber if offline mode is somehow off."""
    dev = {"mps": "Apple GPU (MPS)", "cuda": "NVIDIA GPU (CUDA)", "cpu": "CPU"}.get(device_name(), device_name())
    if offline_mode():
        body = f"<span><b>Running locally on {theme.esc(dev)}</b>" + ("" if compact else
               "<br>Offline mode on · no cloud AI · video stays on this computer") + "</span>"
        return f'<div class="bs-local" role="status"><span class="dot" aria-hidden="true"></span>{body}</div>'
    return (f'<div class="bs-local warn" role="status"><span class="dot" aria-hidden="true"></span><span><b>Running on '
            f'{theme.esc(dev)}</b><br>Offline mode is off: models could contact Hugging Face. See Model &amp; privacy.</span></div>')


def sidebar() -> None:
    """Brand, reviewer name, data source and the local-device badge."""
    qp = st.query_params
    if "reviewer" not in st.session_state:
        st.session_state["reviewer"] = qp.get("reviewer", "")
    with st.sidebar:
        st.html(local_badge(compact=True))
        st.text_input("Your name (recorded with each review)", key="reviewer", placeholder="e.g. A. Biologist")
        n = pending_count()
        st.html(f'<p class="bs-small" style="margin:4px 0 0">{n} item{"s" if n != 1 else ""} waiting for review</p>')
        st.radio("Data", ["Survey results", "Mock data"], key="data_source", horizontal=True,
                 help="Mock data is a small fake dataset for trying the app without running the models "
                      "(create it with scripts/make_mock_data.py).")
