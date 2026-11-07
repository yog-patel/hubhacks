"""Scan BlueSight's own code and requirements for anything that could reach the internet.

    python scripts/scan_network.py        # -> outputs/eval/network_scan.json and a summary on stdout

Looks for HTTP clients, raw sockets, hosted-AI SDKs, API keys, model-hub downloads and telemetry switches in
src/, app/, scripts/, tests/, config files and requirements. Every hit is listed with an explanation of why it
is safe (or what was done about it). Third-party libraries are covered at runtime by the network guard and the
offline test instead (tests/test_offline.py).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ["src", "app", "scripts", "tests", "config.yaml", "requirements.txt", "pyproject.toml", ".streamlit/config.toml"]
PATTERNS = {
    "http client": r"\b(import requests|from requests|import httpx|from httpx|urllib\.request|urlopen|aiohttp|http\.client)\b",
    "raw socket": r"\bsocket\.(socket|create_connection|getaddrinfo)\b",
    "hosted AI SDK": r"\b(openai|anthropic|google\.generativeai|vertexai|cohere|mistralai|replicate|roboflow|inference_sdk|InferenceClient)\b",
    "API key / token": r"(api[_-]?key|API_KEY|HF_TOKEN|hf_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|Bearer )",
    "model hub load": r"\b(from_pretrained|create_model_and_transforms|hf_hub_download|snapshot_download)\b",
    "URL": r"https?://[^\s\"')]+",
    "telemetry": r"(gatherUsageStats|telemetry|TELEMETRY|DO_NOT_TRACK|EmissionsTracker\b)",
}
EXPLAIN = {
    "src/bluesight/netguard.py": "the network guard itself (patches socket to count/block; makes no connections)",
    "tests/test_offline.py": "the offline test (blocks sockets; its only URL is a deliberate blocked probe)",
    "scripts/scan_network.py": "this scanner (pattern strings only)",
    "src/bluesight/embed.py": "loads BioCLIP/DINOv2 from models/ on disk; HF_HUB_OFFLINE=1 is set on import, so no download or update check",
    "src/bluesight/detect.py": "loads OWLv2 (optional detector) from models/ on disk; offline mode as above",
    "src/bluesight/__init__.py": "sets HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE / HF_HUB_DISABLE_TELEMETRY / DO_NOT_TRACK before anything loads",
    "src/bluesight/energy.py": "CodeCarbon OfflineEmissionsTracker: the offline variant, no API (verified under the guard)",
    "scripts/model_inventory.py": "URLs are printed as the model's source; nothing is fetched",
    "scripts/experiments.py": "loads OWLv2 base/large from models/; large was downloaded once with BLUESIGHT_ALLOW_DOWNLOADS=1",
    "scripts/screenshot_app.py": "Playwright drives a local headless browser at http://localhost:8501 only (dev tool)",
    ".streamlit/config.toml": "telemetry switched OFF (gatherUsageStats = false), app bound to localhost",
    "app/ui/page_privacy.py": "reads the gatherUsageStats setting to display it",
    "app/ui/common.py": "displays the offline status",
    "README.md": "documentation",
    "config.yaml": "settings only (offline switch, network-guard mode, offline energy estimator, model names)",
}


def main() -> int:
    hits = []
    for t in TARGETS:
        p = ROOT / t
        files = [p] if p.is_file() else sorted(p.rglob("*.py")) if p.exists() else []
        for f in files:
            rel = str(f.relative_to(ROOT))
            for n, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
                for kind, pat in PATTERNS.items():
                    if re.search(pat, line):
                        hits.append({"file": rel, "line": n, "kind": kind, "code": line.strip()[:160],
                                     "assessment": EXPLAIN.get(rel, "REVIEW")})
    unexplained = [h for h in hits if h["assessment"] == "REVIEW"]
    out = {"targets": TARGETS, "patterns": PATTERNS, "hits": hits, "unexplained": unexplained,
           "summary": {"hits": len(hits), "unexplained": len(unexplained),
                       "kinds": {k: sum(h["kind"] == k for h in hits) for k in PATTERNS}}}
    f = ROOT / "outputs" / "eval" / "network_scan.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, indent=1))
    print(json.dumps(out["summary"], indent=1))
    for h in unexplained:
        print("REVIEW:", h["file"], h["line"], h["kind"], h["code"])
    return 1 if unexplained else 0


if __name__ == "__main__":
    sys.exit(main())
