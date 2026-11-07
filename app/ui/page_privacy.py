"""Model & privacy: proof, from live data, that BlueSight runs on this computer and sends nothing out."""
from __future__ import annotations

import json
import os
import platform
from pathlib import Path

import pandas as pd
import streamlit as st

from . import common as C
from . import theme as T


def _streamlit_setting(key: str):
    try:
        from streamlit import config

        return config.get_option(key)
    except Exception:
        return None


def page() -> None:
    cfg = C.cfg()
    root = Path(cfg["_root"])
    T.header("Trust", "Model & privacy",
             "Everything BlueSight does happens on this computer. The AI models are files on this disk, the video is "
             "never uploaded, and the pipeline counts every attempt to reach the internet. This page shows the evidence.")

    runs = C.list_runs()
    last = C.load_report(runs[0]) if runs else None
    net = (last or {}).get("network") or {}
    en = (last or {}).get("energy") or {}

    # ------------------------------------------------------------------ headline indicator
    if last and "external_connection_attempts" in net:
        n = int(net["external_connection_attempts"])
        ok = n == 0
        icon, fg, bg, bd = ("✓", "#14522F", "#E6F4EC", "#9CCBB1") if ok else ("!", "#8C1D13", "#FDECEA", "#E8A39B")
        words = ("0 external network calls during the last run" if ok else
                 f"{n} external network call{'s' if n != 1 else ''} attempted during the last run (all blocked)")
        st.html(f'<div role="status" style="display:flex;gap:16px;align-items:center;padding:20px 24px;border-radius:12px;'
                f'background:{bg};border:1px solid {bd};color:{fg};margin-bottom:8px">'
                f'<span aria-hidden="true" style="font-size:30px;font-weight:800;width:52px;height:52px;border-radius:50%;'
                f'display:flex;align-items:center;justify-content:center;background:{fg};color:#fff;flex:none">{icon}</span>'
                f'<span><span style="font-size:24px;font-weight:700;display:block">{words}</span>'
                f'<span style="font-size:15px">Run <code>{T.esc(last["run_id"])}</code> · {T.esc(last["generated_at"].replace("T", " "))} · '
                f'network guard mode “{T.esc(net.get("mode", "?"))}”, local connections allowed: {net.get("local_connections", 0)}</span></span></div>')
    else:
        st.info("No run has recorded network data yet. Analyse a video and this indicator fills in from the pipeline's network guard.")

    # ------------------------------------------------------------------ live status cards
    dev = C.device_name()
    try:
        import torch

        torch_v = torch.__version__
    except Exception:
        torch_v = "not installed"
    usage = _streamlit_setting("browser.gatherUsageStats")
    addr = _streamlit_setting("server.address")
    T.cards([
        {"k": "Compute device", "v": {"mps": "Apple GPU", "cuda": "NVIDIA GPU", "cpu": "CPU"}.get(dev, dev), "tone": "info",
         "d": f"{T.esc(C.hardware())} · PyTorch {T.esc(torch_v)}"},
        {"k": "Offline mode", "v": "On" if C.offline_mode() else "Off", "tone": "ok" if C.offline_mode() else "attn",
         "d": f"HF_HUB_OFFLINE={T.esc(os.environ.get('HF_HUB_OFFLINE', 'unset'))} · "
              f"TRANSFORMERS_OFFLINE={T.esc(os.environ.get('TRANSFORMERS_OFFLINE', 'unset'))}"},
        {"k": "App telemetry", "v": "Off" if usage is False else "On", "tone": "ok" if usage is False else "attn",
         "d": f"Streamlit usage statistics {'off' if usage is False else 'ON'} · app reachable from {T.esc(addr)} only"},
        {"k": "Last run", "v": f"{last['runtime_s']:.0f}" if last else "—", "unit": "s" if last else "",
         "d": (f"{T.esc(last['run_id'])}<br>" +
               (f"≈ {en['energy_wh']:.2f} Wh · {en['co2_g']:.2f} g CO₂e (estimate)" if en.get("energy_wh") is not None
                else T.esc(en.get("note", "energy not measured")))) if last else "no runs yet"},
    ])

    # ------------------------------------------------------------------ models
    st.subheader("AI models on this computer", anchor=False)
    inv_f = root / "outputs" / "model_inventory.json"
    if inv_f.exists():
        inv = json.loads(inv_f.read_text())
        rows = "".join(
            f'<tr><td><b>{T.esc(m["role"])}</b><br><span class="bs-small">{T.esc(m["name"])}</span></td>'
            f'<td>{T.esc(m["version"])}</td><td>{T.esc(m["licence"])}</td><td>{T.esc(m["loaded_by"])}</td>'
            f'<td>{T.esc(m["size_mb"])} MB</td><td><code>{T.esc(m["local_path"])}</code><br>'
            f'<span class="bs-small">SHA-256 {T.esc(m["sha256"][:16])}…</span></td></tr>' for m in inv["models"])
        st.html('<table class="bs-table"><thead><tr><th scope="col">Model</th><th scope="col">Version</th><th scope="col">Licence</th>'
                '<th scope="col">Loaded by</th><th scope="col">Size</th><th scope="col">Where it lives</th></tr></thead>'
                f'<tbody>{rows}</tbody></table>')
        st.caption(f"Inventory generated {inv['generated_at'].replace('T', ' ')} by scripts/model_inventory.py. "
                   "Full hashes are in LOCAL_VERIFICATION.md.")
    else:
        st.info("Model inventory not generated yet. Run `python scripts/model_inventory.py`.")

    # ------------------------------------------------------------------ how it works
    st.subheader("How it stays local", anchor=False)
    st.html("""<ol style="margin:0;padding-left:22px;line-height:1.7">
<li>The video is read straight from this computer's disk with OpenCV. It is never uploaded.</li>
<li>The AI models (BioCLIP for species, the motion detector for fish) are files in <code>models/</code>, downloaded once.
    BlueSight switches Hugging Face to offline mode before any model library loads, so they can't check for updates.</li>
<li>All processing runs on this computer's GPU or CPU. Results go to <code>outputs/</code> and a local SQLite database.</li>
<li>During every analysis a <b>network guard</b> watches every outgoing connection. Connections to this computer are allowed;
    anything else is blocked and counted. The count is shown above.</li>
<li>This app only listens on <code>localhost</code> and sends no usage statistics.</li>
</ol>""")

    # ------------------------------------------------------------------ energy history
    rt = root / "outputs" / "logs" / "energy.csv"
    if rt.exists():
        st.subheader("Energy per run (estimates)", anchor=False)
        df = pd.read_csv(rt).tail(12).iloc[::-1]
        st.dataframe(df, hide_index=True, width="stretch")
        st.caption("Estimated with CodeCarbon's offline tracker from CPU/GPU power models and Nova Scotia's grid carbon "
                   "intensity. Treat these as estimates, not meter readings.")
    tests = root / "outputs" / "logs" / "offline_test.json"
    if tests.exists():
        t = json.loads(tests.read_text())
        st.subheader("Offline test", anchor=False)
        st.html(f'<p>{T.badge("known" if t.get("passed") else "unfamiliar", "Passed" if t.get("passed") else "Failed")} '
                f'<span class="bs-small">tests/test_offline.py · {T.esc(t.get("when", ""))} · all non-local connections blocked; '
                f'blocked attempts: {t.get("blocked_attempts", "?")} · pipeline runtime {t.get("runtime_s", "?")} s</span></p>')
    st.caption(f"Python {platform.python_version()} · {platform.platform()}")
