"""Energy and CO2 estimate per pipeline run, with CodeCarbon's OfflineEmissionsTracker (no internet needed).

The tracker never contacts a server (verified under the network guard; see LOCAL_VERIFICATION.md). Limits, stated
in every report: on Apple Silicon without root, CodeCarbon estimates CPU power from CPU load ("cpu_load" mode),
RAM from a power model, and does NOT see the Apple GPU (MPS). So the figure is an estimate, and for GPU-heavy
stages it is a lower bound. If codecarbon isn't installed the run still works; the report then says so.
"""
from __future__ import annotations

import logging
import time
from typing import Any


class EnergyMeter:
    """Context manager: ``with EnergyMeter(cfg) as m: ...``; then ``m.result`` holds the estimate."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        e = cfg.get("energy", {}) or {}
        self.enabled = bool(e.get("enabled", True))
        self.country = e.get("country_iso_code", "CAN")
        self.region = e.get("region", "nova scotia")
        self.result: dict[str, Any] = {"energy_wh": None, "co2_g": None, "note": "energy not measured"}
        self._t = None

    def __enter__(self) -> "EnergyMeter":
        self._t0 = time.time()
        if not self.enabled:
            self.result["note"] = "energy tracking disabled in config.yaml"
            return self
        try:
            import warnings

            from codecarbon import OfflineEmissionsTracker

            logging.getLogger("codecarbon").setLevel(logging.ERROR)
            warnings.filterwarnings("ignore", message=".*save_to_.*", category=DeprecationWarning)
            self._t = OfflineEmissionsTracker(country_iso_code=self.country, region=self.region, save_to_file=False,
                                              log_level="error", measure_power_secs=5, tracking_mode="machine",
                                              allow_multiple_runs=True)
            self._t.start()
        except Exception as exc:  # never fail a survey run because of the energy estimate
            self._t = None
            self.result["note"] = f"codecarbon unavailable: {exc}"[:200]
        return self

    def __exit__(self, *exc) -> None:
        if self._t is None:
            return
        try:
            kg = self._t.stop()
            d = self._t.final_emissions_data
            self.result = {
                "energy_wh": round(float(d.energy_consumed) * 1000.0, 4),
                "co2_g": round(float(kg or 0.0) * 1000.0, 4),
                "cpu_energy_wh": round(float(d.cpu_energy) * 1000.0, 4),
                "ram_energy_wh": round(float(d.ram_energy) * 1000.0, 4),
                "gpu_energy_wh": round(float(d.gpu_energy) * 1000.0, 4),
                "cpu_power_w": round(float(d.cpu_power), 2), "cpu_model": d.cpu_model,
                "grid": f"{d.region}, {d.country_name}", "duration_s": round(time.time() - self._t0, 1),
                "method": "CodeCarbon OfflineEmissionsTracker (CPU load model + RAM model; Apple GPU not measured)",
                "note": "estimate, not a meter reading; GPU (MPS) energy is not included",
            }
        except Exception as exc:
            self.result["note"] = f"codecarbon failed: {exc}"[:200]
