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
    T.header("", "Privacy", "Your video never leaves this computer. Here's the proof.")

    runs = C.list_runs()
    last = C.load_report(runs[0]) if runs else None
    net = (last or {}).get("network") or {}
    en = (last or {}).get("energy") or {}
    n_ext = int(net.get("external_connection_attempts", 0)) if last and "external_connection_attempts" in net else None
    dev = {"mps": "Apple GPU", "cuda": "NVIDIA GPU", "cpu": "CPU"}.get(C.device_name(), C.device_name())
    usage = _streamlit_setting("browser.gatherUsageStats")
    full_wh = None
    ef = root / "outputs" / "logs" / "energy.csv"
    if ef.exists():
        e = pd.read_csv(ef)
        e = e[(e.cached_detection == 0) & e.energy_wh.notna()]
        full_wh = float(e.energy_wh.iloc[-1]) if len(e) else None
    checks = [
        ("0 internet connections" if n_ext == 0 else (f"{n_ext} connections blocked" if n_ext else "Not run yet"),
         "during the last analysis", n_ext == 0),
        ("Works with Wi-Fi off", "models are stored on this computer", C.offline_mode()),
        ("No tracking", "no usage statistics are sent", usage is False),
        (f"Runs on this {dev}", "nothing is processed in the cloud", True),
        ("Open-source models", "BioCLIP (MIT), DINOv2 (Apache-2.0)", True),
        (f"{full_wh:.1f} Wh per analysis" if full_wh else "Low energy",
         "last full analysis; re-runs reuse saved work", True),
    ]
    st.html('<div class="bs-checks">' + "".join(
        f'<div class="bs-check"><span class="ico" aria-hidden="true">{"✓" if ok else "!"}</span>'
        f'<div><b>{T.esc(a)}</b><span>{T.esc(b)}</span></div></div>' for a, b, ok in checks) + '</div>')

    with st.expander("Technical details", icon=":material/terminal:"):
        try:
            import torch

            torch_v = torch.__version__
        except Exception:
            torch_v = "not installed"
        st.markdown(f"- Device: {C.hardware()} · PyTorch {torch_v}\n"
                    f"- Offline flags: HF_HUB_OFFLINE={os.environ.get('HF_HUB_OFFLINE', 'unset')}, "
                    f"TRANSFORMERS_OFFLINE={os.environ.get('TRANSFORMERS_OFFLINE', 'unset')}\n"
                    f"- App address: {_streamlit_setting('server.address')} only\n"
                    + (f"- Last run: `{last['run_id']}`, {last['runtime_s']:.0f} s, network guard mode “{net.get('mode', '?')}”"
                       if last else ""))
        inv_f = root / "outputs" / "model_inventory.json"
        if inv_f.exists():
            inv = json.loads(inv_f.read_text())
            rows = "".join(
                f'<tr><td><b>{T.esc(m["role"])}</b><br><span class="bs-small">{T.esc(m["name"])}</span></td>'
                f'<td>{T.esc(m["licence"])}</td><td>{T.esc(m["size_mb"])} MB</td><td><code>{T.esc(m["local_path"])}</code><br>'
                f'<span class="bs-small">SHA-256 {T.esc(m["sha256"][:16])}…</span></td></tr>' for m in inv["models"])
            st.html('<table class="bs-table"><thead><tr><th scope="col">Model</th><th scope="col">Licence</th>'
                    '<th scope="col">Size</th><th scope="col">Where it lives</th></tr></thead>'
                    f'<tbody>{rows}</tbody></table>')
        st.html("""<ol class="bs-how">
<li>The video is read from this computer's disk. It is never uploaded.</li>
<li>Models are files in <code>models/</code>, downloaded once. Offline mode is switched on before they load.</li>
<li>During every analysis a network guard blocks and counts any connection that leaves this computer.</li>
<li>The app only listens on <code>localhost</code> and sends no usage statistics.</li>
</ol>""")
        rt = root / "outputs" / "logs" / "energy.csv"
        if rt.exists():
            df = pd.read_csv(rt).tail(12).iloc[::-1]
            df = pd.DataFrame({"When": df.generated_at.str.replace("T", " "), "Analysis": df.run_id.str.replace("__", " · "),
                               "Saved work reused": df.cached_detection.map({1: "yes", 0: "no"}),
                               "Time (s)": df.runtime_s, "Energy (Wh)": df.energy_wh, "CO₂e (g)": df.co2_g,
                               "Internet connections": df.external_connections})
            st.dataframe(df, hide_index=True, width="stretch")
            st.caption("Energy is an estimate (CPU and memory; the Apple GPU isn't measured).")
        st.caption(f"Python {platform.python_version()} · {platform.platform()}")
