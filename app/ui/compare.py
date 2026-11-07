"""Original-vs-enhanced comparison slider. Self-contained HTML/JS (no external scripts, nothing fetched)."""
from __future__ import annotations

import base64

import cv2
import numpy as np
import streamlit as st


def _b64(img_bgr: np.ndarray) -> str:
    ok, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buf.tobytes()).decode()


def before_after(original_bgr: np.ndarray, enhanced_bgr: np.ndarray, left_label: str = "Original",
                 right_label: str = "Enhanced", height: int | None = None) -> None:
    """Drag (or use the arrow keys on) the handle to compare the two images."""
    h, w = original_bgr.shape[:2]
    a, b = _b64(original_bgr), _b64(enhanced_bgr)
    st.iframe(f"""<!doctype html><html><body style="margin:0">
<div id="c" style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;max-width:720px">
  <div id="wrap" style="position:relative;width:100%;aspect-ratio:{w}/{h};overflow:hidden;border-radius:12px;border:1px solid #C9D6DF;touch-action:none;cursor:ew-resize">
    <img src="data:image/jpeg;base64,{b}" alt="{right_label} frame" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover">
    <div id="clip" style="position:absolute;inset:0;width:50%;overflow:hidden">
      <img src="data:image/jpeg;base64,{a}" alt="{left_label} frame" style="position:absolute;top:0;left:0;height:100%;width:auto;max-width:none" id="aimg">
    </div>
    <div id="bar" style="position:absolute;top:0;bottom:0;left:50%;width:3px;margin-left:-1px;background:#fff;box-shadow:0 0 0 1px #0F2230"></div>
    <span style="position:absolute;left:10px;top:10px;background:#0F2230;color:#fff;font-size:14px;font-weight:600;padding:3px 9px;border-radius:6px">{left_label}</span>
    <span style="position:absolute;right:10px;top:10px;background:#0B5C7A;color:#fff;font-size:14px;font-weight:600;padding:3px 9px;border-radius:6px">{right_label}</span>
  </div>
  <label for="r" style="display:block;font-size:14px;color:#3E5466;margin-top:8px">Drag the image, or move this slider (arrow keys work), to compare</label>
  <input id="r" type="range" min="0" max="100" value="50" style="width:100%;accent-color:#0B5C7A" aria-label="Comparison position: percent of the original image shown">
</div>
<script>
const wrap=document.getElementById('wrap'),clip=document.getElementById('clip'),bar=document.getElementById('bar'),r=document.getElementById('r'),aimg=document.getElementById('aimg');
function size(){{aimg.style.width=wrap.clientWidth+'px';}}
function set(p){{p=Math.max(0,Math.min(100,p));clip.style.width=p+'%';bar.style.left=p+'%';r.value=p;}}
r.addEventListener('input',e=>set(+e.target.value));
let drag=false;
function pos(e){{const b=wrap.getBoundingClientRect();set((e.clientX-b.left)/b.width*100);}}
wrap.addEventListener('pointerdown',e=>{{drag=true;wrap.setPointerCapture(e.pointerId);pos(e);}});
wrap.addEventListener('pointermove',e=>{{if(drag)pos(e);}});
wrap.addEventListener('pointerup',()=>drag=false);
window.addEventListener('resize',size);size();
</script></body></html>""", height=height or "content")
