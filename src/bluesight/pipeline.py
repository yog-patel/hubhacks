"""run_video(): Upload video -> Enhance -> Detect & track -> Identify -> Count / Flag -> Report.

Expensive stages (decode + detect + track, and embeddings) are cached per video window under
outputs/cache/, so a re-run after a registry change only repeats identification, counting and
reporting (seconds, not minutes).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import heapq
import json
import os
import pickle
import platform
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
import pandas as pd

from . import count as C
from .config import load_config, path, resolve_device
from .db import DB, dumps, to_blob
from .detect import Frame, get_detector
from .enhance import visibility_score
from .identify import (FLAG_STATUSES, auto_reject, KNOWN, LOW_VIS, REJECTED, UNCERTAIN, UNFAMILIAR, Thresholds,
                       classify_track, crop_quality, mean_embedding, merge_flagged, top_matches)
from .io_video import VideoWriter, iter_sampled_frames, resize_width, video_info
from .logs import get_logger
from .registry import Registry

log = get_logger("pipeline")
Progress = Callable[[float, str], None]

COLORS = {KNOWN: (80, 200, 60), UNCERTAIN: (0, 200, 255), UNFAMILIAR: (0, 80, 255), LOW_VIS: (160, 160, 160), REJECTED: (90, 90, 90)}


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")


def site_from_name(name: str) -> str:
    m = re.search(r"T(\d)[-_ ]*STAT ?(\d)", name, re.I)
    return f"T{m.group(1)}-STAT{m.group(2)}" if m else "unknown"


def hardware_string(device: str) -> str:
    """Human-readable description of where this ran."""
    cpu = platform.processor() or platform.machine()
    try:
        import subprocess

        cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=2).stdout.strip() or cpu
    except Exception:
        pass
    return f"{cpu} ({platform.system()} {platform.machine()}), device={device}"


def _torch_version() -> str:
    try:
        import torch

        return torch.__version__
    except Exception:
        return "unavailable"


def analysis_window(duration_s: float, cfg: dict[str, Any], start_s: float | None, duration: float | None) -> tuple[float, float]:
    """Protocol window: discard the first minute, analyse 15 min (never the last minute)."""
    p = cfg["protocol"]
    start = float(p["trim_start_s"]) if start_s is None else float(start_s)
    length = float(p["analysis_duration_s"]) if duration is None else float(duration)
    end = min(start + length, duration_s - float(p["trim_end_s"]))
    if end <= start:
        raise ValueError(f"empty analysis window {start}-{end} for a {duration_s:.0f}s video")
    return start, end


# ---------------------------------------------------------------------------- stage A
def _detect_and_track(video: Path, start: float, end: float, cfg: dict[str, Any], cdir: Path, progress: Progress) -> None:
    """Decode sampled frames, score visibility, detect, track, keep the best crops per track."""
    from .track import Tracker

    fps = float(cfg["sampling"]["fps"])
    pw = int(cfg["sampling"]["process_width"])
    aw = int(cfg["sampling"]["annotated_width"])
    pad = float(cfg["sampling"]["crop_pad"])
    k = int(cfg["identify"]["best_crops"])
    detector = get_detector(cfg)
    tracker = Tracker(cfg["tracker"], fps)
    thumbs = cdir / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    frames_rows, det_rows = [], []
    best: dict[int, list] = {}  # track -> min-heap of (quality, counter, payload)
    counter = 0

    def gen():
        for idx, t, full in iter_sampled_frames(video, fps, start, end):
            small, s = resize_width(full, pw)
            yield Frame(idx, t, full, small, s, visibility_score(small, cfg["enhance"]))

    def keep_crop(fr: Frame, b: np.ndarray, tid: int) -> None:
        nonlocal counter
        th, tw = fr.full.shape[:2]
        fb = b[:4] / fr.scale  # full-res box
        w, h = fb[2] - fb[0], fb[3] - fb[1]
        x1, y1 = int(max(0, fb[0] - pad * w)), int(max(0, fb[1] - pad * h))
        x2, y2 = int(min(tw, fb[2] + pad * w)), int(min(th, fb[3] + pad * h))
        crop = fr.full[y1:y2, x1:x2]
        if crop.size == 0:
            return
        edge = fb[0] <= 2 or fb[1] <= 2 or fb[2] >= tw - 2 or fb[3] >= th - 2
        q = crop_quality(crop, edge)
        heap = best.setdefault(int(tid), [])
        payload = (cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes(), fr.t)
        counter += 1
        if len(heap) < k:
            heapq.heappush(heap, (q, counter, payload))
        elif q > heap[0][0]:
            heapq.heapreplace(heap, (q, counter, payload))

    prev: tuple[Frame, np.ndarray, int] | None = None  # (frame, boxes, first det_rows index)
    for fr, boxes in detector.detect_stream(gen()):
        ids, backfill = tracker.update(boxes)
        frames_rows.append((fr.idx, round(fr.t, 3), fr.visibility))
        if prev is not None:
            pfr, pboxes, p0 = prev
            for j, tid in backfill:
                row = list(det_rows[p0 + j])
                row[2] = int(tid)
                det_rows[p0 + j] = tuple(row)
                keep_crop(pfr, pboxes[j], tid)
        first = len(det_rows)
        for b, tid in zip(boxes, ids):
            det_rows.append((fr.idx, round(fr.t, 3), int(tid), *[float(v) for v in b[:4]], float(b[4])))
            if tid >= 0:
                keep_crop(fr, b, int(tid))
        prev = (fr, boxes, first)
        thumb, _ = resize_width(fr.full, aw)
        cv2.imwrite(str(thumbs / f"{fr.idx:07d}.jpg"), thumb, [cv2.IMWRITE_JPEG_QUALITY, 85])
        progress(min(0.99, (fr.t - start) / max(end - start, 1e-6)), f"detect+track t={fr.t:.0f}s ({len(boxes)} detections)")
    pd.DataFrame(frames_rows, columns=["frame_idx", "t_s", "visibility"]).to_csv(cdir / "frames.csv", index=False)
    pd.DataFrame(det_rows, columns=["frame_idx", "t_s", "track_id", "x1", "y1", "x2", "y2", "score"]).to_csv(cdir / "detections.csv", index=False)
    crops = {tid: [p for _, _, p in sorted(h, key=lambda x: -x[0])] for tid, h in best.items()}
    with open(cdir / "crops.pkl", "wb") as fh:
        pickle.dump(crops, fh)
    (cdir / "meta.json").write_text(json.dumps({"detector": detector.version, "scale": float(fr.scale) if frames_rows else 1.0,
                                                 "created": dt.datetime.now().isoformat(timespec="seconds")}))


# ---------------------------------------------------------------------------- stage B
def _embed_tracks(cdir: Path, embedder, progress: Progress, eligible: set[int] | None = None) -> dict[int, np.ndarray]:
    """Embed each eligible track's best crops and average them (cached per embedder).

    Tracks shorter than MIN_FRAMES are never identified (visibility gate), so they are not embedded:
    this saves most of the embedding energy on noisy footage.
    """
    f = cdir / f"emb_{slug(embedder.version)}.npz"
    if f.exists():
        z = np.load(f)
        have = {int(k): z[k] for k in z.files}
        if eligible is None or eligible <= set(have) | _no_crops(cdir, eligible):
            return have
    with open(cdir / "crops.pkl", "rb") as fh:
        crops = pickle.load(fh)
    keys, ims, owner = [], [], []
    for tid, lst in crops.items():
        if eligible is not None and tid not in eligible:
            continue
        for jpg, _ in lst:
            ims.append(cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR))
            owner.append(tid)
    progress(0.0, f"embedding {len(ims)} crops from {len(crops)} tracks")
    E = embedder.embed_images(ims) if ims else np.zeros((0, 1), np.float32)
    out: dict[int, list] = {}
    for tid, e in zip(owner, E):
        out.setdefault(tid, []).append(e)
    res = {tid: mean_embedding(np.stack(v)) for tid, v in out.items()}
    np.savez(f, **{str(k): v for k, v in res.items()})
    return res


def _no_crops(cdir: Path, ids: set[int]) -> set[int]:
    with open(cdir / "crops.pkl", "rb") as fh:
        crops = pickle.load(fh)
    return {i for i in ids if i not in crops}


# ---------------------------------------------------------------------------- main entry
def run_video(video_path: str | Path, cfg: dict[str, Any] | None = None, start_s: float | None = None,
              duration_s: float | None = None, progress: Progress | None = None, force: bool = False,
              make_evidence: bool = True) -> dict[str, Any]:
    """Analyse one video window (see ``_run_video``) under the network guard and the energy meter.

    Every outbound connection attempted during the run is counted (and blocked in ``runtime.network_guard: block``
    mode); the count and an energy/CO2 estimate are added to report.json and outputs/logs/energy.csv.
    """
    from .energy import EnergyMeter
    from .netguard import NetworkGuard

    cfg = cfg or load_config()
    mode = str(cfg.get("runtime", {}).get("network_guard", "block"))
    with NetworkGuard(mode) as guard, EnergyMeter(cfg) as meter:
        report = _run_video(video_path, cfg, start_s, duration_s, progress, force, make_evidence)
    report["network"] = guard.summary()
    report["energy"] = meter.result
    if guard.external_attempts:
        log.warning("network guard: %d external connection attempt(s) during %s: %s", guard.external_attempts,
                    report["run_id"], [a["host"] for a in report["network"]["attempts"]])
    run_dir = Path(report["annotated_video"]).parent
    (run_dir / "report.json").write_text(json.dumps(report, indent=2, default=float))
    ef = path(cfg, "logs_dir") / "energy.csv"
    new = not ef.exists()
    with open(ef, "a") as fh:
        if new:
            fh.write("generated_at,run_id,cached_detection,runtime_s,energy_wh,co2_g,external_connections\n")
        e = meter.result
        fh.write(f"{report['generated_at']},{report['run_id']},{int(report['cached_detection'])},{report['runtime_s']},"
                 f"{'' if e.get('energy_wh') is None else e['energy_wh']},{'' if e.get('co2_g') is None else e['co2_g']},"
                 f"{guard.external_attempts}\n")
    return report


def _run_video(video_path: str | Path, cfg: dict[str, Any] | None = None, start_s: float | None = None,
               duration_s: float | None = None, progress: Progress | None = None, force: bool = False,
               make_evidence: bool = True) -> dict[str, Any]:
    """Analyse one video window and write outputs/runs/<video>/<start>-<end>s/ (report, CSV, annotated video, flags).

    Args:
        video_path: video file.
        cfg: configuration (loaded from config.yaml if None).
        start_s / duration_s: analysis window override (default: protocol window).
        progress: callback(fraction, message).
        force: ignore caches.
        make_evidence: write evidence packages for flagged items.
    Returns:
        The report dictionary (also saved as report.json).
    """
    t_all = time.time()
    cfg = cfg or load_config()
    progress = progress or (lambda f, m: None)
    video = Path(video_path)
    info = video_info(video)
    start, end = analysis_window(info.duration_s, cfg, start_s, duration_s)
    device = resolve_device(cfg)
    db = DB(path(cfg, "db_path"))
    th = Thresholds.from_cfg(cfg)
    vname = video.stem
    run_id = f"{slug(vname)}__{int(start)}-{int(end)}s"
    run_dir = path(cfg, "runs_dir") / slug(vname) / f"{int(start)}-{int(end)}s"
    run_dir.mkdir(parents=True, exist_ok=True)
    det_key = hashlib.md5(json.dumps([cfg["detector"], cfg["tracker"], cfg["sampling"], cfg["enhance"],
                                      cfg["identify"]["best_crops"], info.n_frames]).encode()).hexdigest()[:10]
    cdir = path(cfg, "cache_dir") / slug(vname) / f"{int(start)}-{int(end)}s_{det_key}"
    timings: dict[str, float] = {}
    log.info("run %s: window %.1f-%.1f s on %s", run_id, start, end, device)

    # A. detect + track (cached)
    cached = (cdir / "crops.pkl").exists() and not force
    t0 = time.time()
    if not cached:
        if cdir.exists():
            shutil.rmtree(cdir)
        cdir.mkdir(parents=True)
        _detect_and_track(video, start, end, cfg, cdir, lambda f, m: progress(0.05 + 0.6 * f, m))
    timings["detect_track_s"] = time.time() - t0
    frames = pd.read_csv(cdir / "frames.csv")
    dets = pd.read_csv(cdir / "detections.csv")
    meta = json.loads((cdir / "meta.json").read_text())

    # B. embeddings (cached per embedder)
    t0 = time.time()
    registry = Registry(cfg, db)
    embedder = registry.embedder
    progress(0.67, "embedding track crops")
    nf = dets[dets.track_id >= 0].groupby("track_id").frame_idx.nunique()
    eligible = {int(t) for t, n in nf.items() if n >= int(cfg["identify"]["MIN_FRAMES"])}
    embs = _embed_tracks(cdir, embedder, lambda f, m: progress(0.67, m), eligible)
    timings["embed_s"] = time.time() - t0

    # C. identify each track
    t0 = time.time()
    names, protos = registry.prototypes()
    vis_by_frame = dict(zip(frames.frame_idx, frames.visibility))
    trk = dets[dets.track_id >= 0].copy()
    trk["area"] = (trk.x2 - trk.x1) * (trk.y2 - trk.y1)
    trk["vis"] = trk.frame_idx.map(vis_by_frame)
    reviewed = {r["flag_id"]: r for r in db.q("SELECT * FROM flags WHERE run_id=? AND review_decision IS NOT NULL", (run_id,))}
    human: dict[int, tuple[str, str | None]] = {}
    for r in reviewed.values():
        for tid in json.loads(r["track_ids"]):
            if r["review_decision"] == "reject":
                human[int(tid)] = (REJECTED, None)
            elif r["review_decision"] in ("new_species", "existing_species") and r["review_species"]:
                human[int(tid)] = (KNOWN, r["review_species"])
    # negatives taught by reviewers: embeddings of items rejected as "not a fish" (any video)
    from .db import from_blob

    negs = [from_blob(r["embedding"]) for r in db.q("SELECT embedding FROM flags WHERE review_decision='reject' AND embedding IS NOT NULL")]
    N = np.stack(negs) if negs else None
    rej_sim = float(cfg["identify"].get("reject_similarity", 1.01))
    track_rows = []
    n_auto_rejected = 0
    for tid, g in trk.groupby("track_id"):
        e = embs.get(int(tid))
        res = classify_track(e, float(g.vis.mean()), int(g.frame_idx.nunique()), float(g.area.mean()), names, protos, th)
        status, species, verified = res.status, res.species, False
        if auto_reject(status, e, res.best_similarity, N, rej_sim):
            status, species = REJECTED, None  # looks like something a reviewer already rejected
            n_auto_rejected += 1
        if int(tid) in human:
            status, species = human[int(tid)]
            verified = True
        track_rows.append({"track_id": int(tid), "start_s": float(g.t_s.min()), "end_s": float(g.t_s.max()),
                           "n_frames": int(g.frame_idx.nunique()), "visibility": float(g.vis.mean()),
                           "mean_area": float(g.area.mean()), "status": status, "species": species,
                           "best_similarity": res.best_similarity, "top3": res.top3, "verified": verified})
    tracks = pd.DataFrame(track_rows) if track_rows else pd.DataFrame(columns=["track_id", "status", "species"])
    timings["identify_s"] = time.time() - t0

    # D. flags: merge similar flagged tracks into review items, most unfamiliar first
    t0 = time.time()
    flagged = tracks[tracks.status.isin(FLAG_STATUSES)] if len(tracks) else tracks
    groups = []
    if len(flagged):
        keys = flagged.track_id.tolist()
        E = np.stack([embs[k] for k in keys])
        unfam = (1.0 - flagged.best_similarity.to_numpy())
        groups = merge_flagged(keys, E, float(cfg["identify"]["merge_similarity"]), unfam)
    # remove stale (unreviewed) flags of this run; remember them so unchanged evidence can be reused
    previous = {r["flag_id"]: r for r in db.q("SELECT flag_id, folder, track_ids FROM flags WHERE run_id=? AND review_decision IS NULL", (run_id,))}
    db.x("DELETE FROM flags WHERE run_id=? AND review_decision IS NULL", (run_id,))
    with open(cdir / "crops.pkl", "rb") as fh:
        crops_by_track = pickle.load(fh)
    scale = float(meta.get("scale", 1.0))
    items = []
    tindex = tracks.set_index("track_id") if len(tracks) else None
    for g in groups:
        sub = tindex.loc[g]
        e = mean_embedding(np.stack([embs[k] for k in g]))
        top3 = top_matches(e, names, protos, 3) if names else []
        best = top3[0]["similarity"] if top3 else 0.0
        status = UNFAMILIAR if (sub.status == UNFAMILIAR).any() and best < th.T_UNKNOWN else (UNCERTAIN if best >= th.T_UNKNOWN else UNFAMILIAR)
        items.append({"tracks": [int(x) for x in g], "emb": e, "top3": top3, "best": best, "status": status,
                      "start": float(sub.start_s.min()), "end": float(sub.end_s.max()),
                      "vis": float(sub.visibility.mean()), "frames": int(sub.n_frames.sum())})
    items.sort(key=lambda it: it["best"])  # most clearly unfamiliar first
    max_items = int(cfg["identify"]["max_review_items"])
    flag_ids = []
    for rank, it in enumerate(items):
        fid = f"{slug(vname)}_{int(start)}-{int(end)}s_t{min(it['tracks'])}"
        it["flag_id"] = fid
        for tid in it["tracks"]:
            tracks.loc[tracks.track_id == tid, "flag_id"] = fid
        if fid in reviewed or rank >= max_items:
            continue
        folder = path(cfg, "flags_dir") / fid
        tr_boxes = {}
        for tid in it["tracks"][:8]:
            gg = trk[trk.track_id == tid].sort_values("t_s")
            tr_boxes[tid] = [(float(r.t_s), [r.x1 / scale, r.y1 / scale, r.x2 / scale, r.y2 / scale]) for r in gg.itertuples()]
        crops = []
        for tid in it["tracks"]:
            for jpg, _ in crops_by_track.get(tid, []):
                crops.append(cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR))
        crops = sorted(crops, key=lambda c: -crop_quality(c))[:5]
        flag = {
            "flag_id": fid, "video_file": video.name, "site": site_from_name(vname), "date": cfg["survey"]["default_date"],
            "start_time_s": it["start"], "end_time_s": it["end"], "status": it["status"], "top3": it["top3"],
            "visibility": it["vis"], "track_frames": it["frames"], "track_ids": it["tracks"],
            "model_versions": {"detector": meta["detector"], "embedder": embedder.version},
            "thresholds": {"T_KNOWN": th.T_KNOWN, "T_UNKNOWN": th.T_UNKNOWN, "V_MIN": th.V_MIN},
            "review": {"decision": None, "species": None, "reviewer": None, "timestamp": None},
        }
        old = previous.pop(fid, None)
        reuse = (old is not None and json.loads(old["track_ids"]) == it["tracks"] and (folder / "clip.mp4").exists())
        if reuse:
            (folder / "flag.json").write_text(json.dumps(flag, indent=2, default=float))
        elif make_evidence:
            progress(0.75 + 0.15 * rank / max(1, min(len(items), max_items)), f"evidence package {rank + 1}")
            if folder.exists():
                shutil.rmtree(folder, ignore_errors=True)
            write_flag_package(folder, flag, crops, str(video), tr_boxes, cfg)
        db.x("INSERT OR REPLACE INTO flags(flag_id, run_id, video_file, status, track_ids, start_s, end_s, top3, best_similarity, "
             "visibility, track_frames, folder, embedding, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
             (fid, run_id, video.name, it["status"], json.dumps(it["tracks"]), it["start"], it["end"], dumps(it["top3"]),
              it["best"], it["vis"], it["frames"], str(folder), to_blob(it["emb"]), dt.datetime.now().isoformat(timespec="seconds")))
        flag_ids.append(fid)
    for r in previous.values():  # flags that no longer exist (e.g. now recognised as a known species)
        if r["folder"] and Path(r["folder"]).exists():
            shutil.rmtree(r["folder"], ignore_errors=True)
    timings["evidence_s"] = time.time() - t0

    # E. counts (protocol MeanCount over systematic subsamples + MaxN)
    t0 = time.time()
    lab_by_track = {int(r.track_id): C.count_label(r.status, r.species, r.n_frames >= th.MIN_FRAMES or bool(r.verified))
                    for r in tracks.itertuples()} if len(tracks) else {}
    dets["label"] = [lab_by_track.get(int(t)) if t >= 0 else None for t in dets.track_id]
    transient_per_frame = float(dets.label.isna().sum()) / max(1, len(frames))
    counts = C.per_frame_counts(frames.t_s.round(3).tolist(), dets.t_s.round(3), dets.label)
    pcfg = cfg["protocol"]
    points = C.subsample_points(start, end, float(pcfg["subsample_interval_s"]))
    pc = C.protocol_counts(counts, points, float(pcfg["count_window_s"]))
    ftimes = C.protocol_frame_times(counts, points, float(pcfg["count_window_s"]))
    invert = set(cfg.get("invertebrate_species") or [])
    fish_cols = [c for c in pc.columns if c not in invert]
    vis_t = frames.set_index(frames.t_s.round(3)).visibility
    sub_rows = []
    for p, ft in zip(points, ftimes):
        row = pc.loc[p].to_dict() if p in pc.index else {}
        near = vis_t.iloc[int(np.argmin(np.abs(vis_t.index.to_numpy() - p)))] if len(vis_t) else 0.0
        sub_rows.append({"subsample_t_s": p, "time": f"{int(p // 60)}:{int(p % 60):02d}", "frame_t_s": round(float(ft), 3),
                         "visibility": round(float(near), 3),
                         "total_fish_count": int(sum(row.get(c, 0) for c in fish_cols)),
                         "invertebrate_count": int(sum(row.get(c, 0) for c in invert)), **{k: int(v) for k, v in row.items()}})
    mc_proto = C.meancount(pc) if len(pc.columns) else {}
    mc_all = C.meancount(counts) if len(counts.columns) else {}
    mx = C.maxn(counts) if len(counts.columns) else {}
    species_rows = []
    for label in sorted(set(mx) | set(mc_proto)):
        if len(tracks):
            if label in names or (label not in (C.UNKNOWN_LABEL, C.UNFAMILIAR_LABEL) and not label.startswith("Unconfirmed")):
                ts = tracks[(tracks.status == KNOWN) & (tracks.species == label)]
            elif label.startswith("Unconfirmed"):
                ts = tracks[(tracks.status == UNCERTAIN) & (tracks.species == label.split("probably ")[1].rstrip("?"))]
            elif label == C.UNFAMILIAR_LABEL:
                ts = tracks[tracks.status == UNFAMILIAR]
            else:
                ts = tracks[tracks.status == LOW_VIS]
        else:
            ts = tracks
        conf = float(ts.best_similarity.mean()) if len(ts) and label != C.UNKNOWN_LABEL else None
        species_rows.append({"label": label, "MaxN": mx.get(label, 0), "MeanCount": round(mc_proto.get(label, 0.0), 3),
                             "MeanCount_all_sampled_frames": round(mc_all.get(label, 0.0), 3), "n_tracks": int(len(ts)),
                             "confidence": None if conf is None else round(conf, 3),
                             "verified_tracks": int(ts.verified.sum()) if len(ts) and "verified" in ts else 0})
    vs = C.visibility_summary(frames.visibility.tolist(), th.V_MIN)
    # the protocol's own 15-minute window (first minute discarded), where it overlaps this run
    p0 = float(pcfg["trim_start_s"])
    proto_pts = [p for p in points if p0 - 1e-6 <= p < p0 + float(pcfg["analysis_duration_s"]) - 1e-6]
    proto_window = None
    if proto_pts:
        sub = [r for r in sub_rows if r["subsample_t_s"] in proto_pts]
        proto_window = {"start_s": p0, "end_s": p0 + float(pcfg["analysis_duration_s"]), "n_subsamples": len(sub),
                        "complete": len(sub) == int(float(pcfg["analysis_duration_s"]) // float(pcfg["subsample_interval_s"])),
                        "MeanCount_total_fish": round(float(np.mean([r["total_fish_count"] for r in sub])), 3),
                        "MeanCount_by_label": {k: round(float(pc.loc[proto_pts, k].mean()), 3) for k in pc.columns}}
    timings["count_s"] = time.time() - t0

    # F. annotated video (sampled frames, real-time 2 fps playback)
    t0 = time.time()
    progress(0.92, "writing annotated video")
    ann_path = run_dir / "annotated.mp4"
    aw = int(cfg["sampling"]["annotated_width"])
    status_by_track = {int(r.track_id): (r.status, r.species) for r in tracks.itertuples()} if len(tracks) else {}
    writer = None
    by_frame = {k: g for k, g in dets.groupby("frame_idx")}
    for fr in frames.itertuples():
        img = cv2.imread(str(cdir / "thumbs" / f"{fr.frame_idx:07d}.jpg"))
        if img is None:
            continue
        f2 = img.shape[1] / (cfg["sampling"]["process_width"])
        for r in by_frame.get(fr.frame_idx, pd.DataFrame()).itertuples():
            st, sp = status_by_track.get(int(r.track_id), (LOW_VIS, None))
            col = COLORS.get(st, (200, 200, 200))
            x1, y1, x2, y2 = int(r.x1 * f2), int(r.y1 * f2), int(r.x2 * f2), int(r.y2 * f2)
            cv2.rectangle(img, (x1, y1), (x2, y2), col, 2)
            tag = sp if st == KNOWN else ("?" + (sp or "") if st == UNCERTAIN else ("NEW?" if st == UNFAMILIAR else ""))
            if tag:
                cv2.putText(img, f"{tag[:18]} #{r.track_id}", (x1, max(10, y1 - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.38, col, 1)
        bar = f"{vname}  t={fr.t_s:6.1f}s  visibility={fr.visibility:.2f}" + ("  LOW VISIBILITY" if fr.visibility < th.V_MIN else "")
        cv2.rectangle(img, (0, 0), (img.shape[1], 22), (0, 0, 0), -1)
        cv2.putText(img, bar, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        if writer is None:
            writer = VideoWriter(ann_path, float(cfg["sampling"]["fps"]), img.shape[1], img.shape[0])
        writer.write(img)
    if writer:
        writer.close()
    timings["annotate_s"] = time.time() - t0

    # G. persist + report
    runtime = time.time() - t_all
    detect_runtime = json.loads((cdir / "runtime.json").read_text())["detect_track_s"] if (cdir / "runtime.json").exists() else timings["detect_track_s"]
    if not cached:
        (cdir / "runtime.json").write_text(json.dumps({"detect_track_s": timings["detect_track_s"]}))
    win_min = (end - start) / 60.0
    report = {
        "video_file": video.name, "site": site_from_name(vname), "date": cfg["survey"]["default_date"], "run_id": run_id,
        "window": {"start_s": start, "end_s": end, "duration_min": round(win_min, 2)},
        "protocol": {"subsample_interval_s": pcfg["subsample_interval_s"], "n_subsamples": len(points),
                     "count_window_s": pcfg["count_window_s"], "source": "Coastal Action DRAFT FFH Video Analysis Protocol"},
        "ran_on": hardware_string(device), "torch_version": _torch_version(),
        "offline": os.environ.get("HF_HUB_OFFLINE") == "1" and os.environ.get("TRANSFORMERS_OFFLINE") == "1", "cached_detection": cached,
        "runtime_s": round(runtime, 1), "timings_s": {k: round(v, 1) for k, v in timings.items()},
        "full_processing_s_per_video_min": round((detect_runtime + timings["embed_s"] + timings["identify_s"]) / max(win_min, 1e-6), 1),
        "models": {"detector": meta["detector"], "embedder": embedder.version},
        "thresholds": th.as_dict(), "sample_fps": cfg["sampling"]["fps"],
        "visibility": vs, "n_sampled_frames": int(len(frames)), "n_detections": int(len(dets)),
        "n_tracks": int(len(tracks)),
        "transient_detections_per_frame_not_counted": round(transient_per_frame, 2),
        "auto_rejected_tracks": n_auto_rejected,
        "track_status_counts": tracks.status.value_counts().to_dict() if len(tracks) else {},
        "species": species_rows, "subsamples": sub_rows,
        "MeanCount_total_fish": round(float(np.mean([r["total_fish_count"] for r in sub_rows])), 3) if sub_rows else 0.0,
        "protocol_window": proto_window,
        "review_items": len(items), "review_items_packaged": len(flag_ids), "flags": flag_ids,
        "registry_species": names,
        "annotated_video": str(ann_path), "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "cache_dir": str(cdir), "process_width": int(cfg["sampling"]["process_width"]),
    }
    (run_dir / "report.json").write_text(json.dumps(report, indent=2, default=float))
    pd.DataFrame(sub_rows).to_csv(run_dir / "report.csv", index=False)
    try:  # protocol-layout Excel workbook (the app rebuilds it with survey details and checks on download)
        from .export import workbook_bytes

        (run_dir / "report.xlsx").write_bytes(workbook_bytes(report, cfg))
    except Exception:  # never lose a run over the spreadsheet
        log.exception("could not write report.xlsx")
    pd.DataFrame(species_rows).to_csv(run_dir / "species_summary.csv", index=False)
    with db.tx() as c:
        for tbl in ("frames", "detections", "tracks"):
            c.execute(f"DELETE FROM {tbl} WHERE run_id=?", (run_id,))
        c.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (run_id, video.name, report["site"], report["date"], start, end, report["generated_at"], runtime, device,
                   meta["detector"], embedder.version, len(frames), len(tracks), str(run_dir / "report.json"), int(cached)))
        c.executemany("INSERT INTO frames VALUES (?,?,?,?)", [(run_id, int(r.frame_idx), float(r.t_s), float(r.visibility)) for r in frames.itertuples()])
        c.executemany("INSERT INTO detections VALUES (?,?,?,?,?,?,?,?,?,?)",
                      [(run_id, int(r.frame_idx), float(r.t_s), int(r.track_id), r.x1, r.y1, r.x2, r.y2, r.score,
                        r.label if isinstance(r.label, str) else "transient (not counted)") for r in dets.itertuples()])
        c.executemany("INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      [(run_id, int(r.track_id), r.start_s, r.end_s, int(r.n_frames), r.visibility, r.mean_area, r.status, r.species,
                        r.best_similarity, dumps(r.top3), getattr(r, "flag_id", None) if isinstance(getattr(r, "flag_id", None), str) else None)
                       for r in tracks.itertuples()] if len(tracks) else [])
    log.info("run %s done in %.1fs (cached detection: %s): %d tracks, %d review items",
             run_id, runtime, cached, len(tracks), len(items))
    with open(path(cfg, "logs_dir") / "runtime.csv", "a") as fh:
        fh.write(f"{report['generated_at']},{video.name},{start},{end},{device},{runtime:.1f},{int(cached)}\n")
    progress(1.0, "done")
    db.close()
    return report


from .evidence import write_flag_package  # noqa: E402  (import at end avoids a cycle in type checkers)
