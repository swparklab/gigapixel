"""Generative outpainting: extend the canvas or fill a mosaic's empty borders.

Two situations fit a stitched heritage mosaic:

* ``fill_borders`` — a rotated/sheared mosaic leaves empty triangular corners in
  its bounding box. Outpainting fills them so the result is a clean rectangle.
* ``extend`` — grow the field of view by a margin on every side.

This is **generative** (AI-invented content), so it is OFF by default, written
as a clearly non-archival variant, and the generated pixels are recorded in an
``outpaint_mask`` so they are never mistaken for measured data.

Backends (``outpaint_backend``):

* ``comfyui``  — submit a ComfyUI workflow (e.g. the Flux Fill outpaint graph)
  to a configured ComfyUI server. Real HTTP integration; used for ``extend``.
* ``diffusers`` — a local Stable-Diffusion / Flux inpaint pipeline that fills
  the exact mask. Optional.
* ``classical`` — always available: mirror-extension for ``extend`` and
  Navier-Stokes inpainting for ``fill_borders``.
"""

from __future__ import annotations

import io
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..config import settings

LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    return


@dataclass(slots=True)
class OutpaintResult:
    image: np.ndarray            # BGR result
    generated_mask: np.ndarray   # uint8, 255 where pixels were synthesised
    backend: str
    mode: str


def _content_bbox(bgr: np.ndarray) -> tuple[int, int, int, int]:
    threshold = int(settings.stitch_quality_empty_threshold)
    content = bgr.max(axis=2) > threshold
    ys, xs = np.where(content)
    if not len(ys):
        return 0, 0, bgr.shape[1], bgr.shape[0]
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _plan(bgr: np.ndarray, mode: str, margin: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (canvas with empty fill region, generated-region mask)."""
    threshold = int(settings.stitch_quality_empty_threshold)
    if mode == "extend":
        m = max(8, int(margin))
        canvas = cv2.copyMakeBorder(bgr, m, m, m, m, cv2.BORDER_CONSTANT, value=(0, 0, 0))
        mask = np.full(canvas.shape[:2], 255, np.uint8)
        mask[m : m + bgr.shape[0], m : m + bgr.shape[1]] = 0
        return canvas, mask
    # fill_borders
    x0, y0, x1, y1 = _content_bbox(bgr)
    canvas = bgr[y0:y1, x0:x1].copy()
    mask = (canvas.max(axis=2) <= threshold).astype(np.uint8) * 255
    return canvas, mask


# --- classical -------------------------------------------------------------
def _classical_fill(canvas: np.ndarray, mask: np.ndarray, mode: str, margin: int) -> np.ndarray:
    if mode == "extend":
        m = max(8, int(margin))
        inner = canvas[m : canvas.shape[0] - m, m : canvas.shape[1] - m]
        # Mirror extension continues the surface texture plausibly and cleanly.
        return cv2.copyMakeBorder(inner, m, m, m, m, cv2.BORDER_REFLECT_101)
    if int(np.count_nonzero(mask)) == 0:
        return canvas
    radius = max(3, int(settings.stitch_repair_inpaint_radius))
    return cv2.inpaint(np.ascontiguousarray(canvas), mask, radius, cv2.INPAINT_NS)


# --- diffusers (optional) --------------------------------------------------
def _diffusers_fill(canvas: np.ndarray, mask: np.ndarray, log: LogFn) -> np.ndarray | None:
    try:
        import torch  # type: ignore
        from diffusers import AutoPipelineForInpainting  # type: ignore
        from PIL import Image
    except Exception:
        return None
    try:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        pipe = AutoPipelineForInpainting.from_pretrained(
            "runwayml/stable-diffusion-inpainting",
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        ).to(device)
        cap = int(settings.outpaint_max_dim)
        h, w = canvas.shape[:2]
        scale = min(1.0, cap / float(max(h, w)))
        proc_w, proc_h = (int(w * scale) // 8 * 8, int(h * scale) // 8 * 8)
        rgb = cv2.cvtColor(cv2.resize(canvas, (proc_w, proc_h)), cv2.COLOR_BGR2RGB)
        m = cv2.resize(mask, (proc_w, proc_h), interpolation=cv2.INTER_NEAREST)
        out = pipe(
            prompt="seamless continuation of the surface, same texture and lighting, photographic, no new objects",
            image=Image.fromarray(rgb),
            mask_image=Image.fromarray(m),
        ).images[0]
        filled = cv2.cvtColor(np.array(out), cv2.COLOR_RGB2BGR)
        filled = cv2.resize(filled, (w, h), interpolation=cv2.INTER_LANCZOS4)
        # Keep measured pixels exactly; only paste generated region.
        result = canvas.copy()
        active = mask > 0
        result[active] = filled[active]
        log("[outpaint] diffusers inpaint applied")
        return result
    except Exception as exc:
        log(f"[outpaint] diffusers failed: {exc}")
        return None


# --- ComfyUI (optional, real API) ------------------------------------------
def _comfyui_outpaint(content_bgr: np.ndarray, target_w: int, target_h: int, log: LogFn) -> np.ndarray | None:
    """Submit the configured ComfyUI workflow with the image injected."""
    url = str(settings.comfyui_url).rstrip("/")
    wf_path = str(settings.comfyui_workflow_path)
    if not url or not wf_path or not Path(wf_path).exists():
        return None
    try:
        import urllib.parse
        import urllib.request

        def _post(path, data, headers):
            req = urllib.request.Request(url + path, data=data, headers=headers, method="POST")
            return urllib.request.urlopen(req, timeout=30)

        # 1) upload the image to ComfyUI
        ok, buf = cv2.imencode(".png", content_bgr)
        boundary = "----hgaboundary"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"hga_input.png\"\r\n"
            "Content-Type: image/png\r\n\r\n"
        ).encode() + buf.tobytes() + f"\r\n--{boundary}--\r\n".encode()
        up = _post("/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        image_name = json.loads(up.read()).get("name", "hga_input.png")

        # 2) load + patch the workflow's first LoadImage node
        workflow = json.loads(Path(wf_path).read_text(encoding="utf-8"))
        nodes = workflow.get("prompt", workflow)
        for node in nodes.values():
            if isinstance(node, dict) and node.get("class_type") == "LoadImage":
                node.setdefault("inputs", {})["image"] = image_name
                break

        # 3) queue
        payload = json.dumps({"prompt": nodes}).encode()
        res = _post("/prompt", payload, {"Content-Type": "application/json"})
        prompt_id = json.loads(res.read())["prompt_id"]

        # 4) poll history
        for _ in range(600):
            with urllib.request.urlopen(f"{url}/history/{prompt_id}", timeout=15) as h:
                hist = json.loads(h.read())
            if prompt_id in hist:
                break
            time.sleep(1.0)
        else:
            log("[outpaint] ComfyUI timed out")
            return None

        outputs = hist[prompt_id].get("outputs", {})
        for node_out in outputs.values():
            for img in node_out.get("images", []):
                q = urllib.parse.urlencode(
                    {"filename": img["filename"], "subfolder": img.get("subfolder", ""), "type": img.get("type", "output")}
                )
                with urllib.request.urlopen(f"{url}/view?{q}", timeout=30) as v:
                    raw = np.frombuffer(v.read(), np.uint8)
                result = cv2.imdecode(raw, cv2.IMREAD_COLOR)
                if result is not None:
                    log("[outpaint] ComfyUI workflow produced an outpainted image")
                    return cv2.resize(result, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
        return None
    except Exception as exc:
        log(f"[outpaint] ComfyUI failed: {exc}")
        return None


def _resolve_backend(mode: str) -> str:
    requested = str(settings.outpaint_backend).lower()
    if requested in ("comfyui", "diffusers", "classical"):
        return requested
    # auto
    if mode == "extend" and str(settings.comfyui_url).strip() and str(settings.comfyui_workflow_path).strip():
        return "comfyui"
    return "diffusers_or_classical"


def outpaint_image(bgr: np.ndarray, mode: str | None = None, margin: int | None = None, log: LogFn = _noop) -> OutpaintResult:
    mode = (mode or settings.outpaint_default_mode).lower()
    if mode not in ("fill_borders", "extend"):
        mode = "fill_borders"
    margin = int(margin if margin is not None else settings.outpaint_margin_px)

    canvas, mask = _plan(bgr, mode, margin)
    backend = _resolve_backend(mode)

    if backend == "comfyui" and mode == "extend":
        out = _comfyui_outpaint(bgr, canvas.shape[1], canvas.shape[0], log)
        if out is not None:
            # Preserve measured pixels in the centre; mark the ring as generated.
            result = out.copy()
            result[mask == 0] = canvas[mask == 0]
            return OutpaintResult(result, mask, "comfyui", mode)
        backend = "diffusers_or_classical"

    if backend in ("diffusers", "diffusers_or_classical"):
        out = _diffusers_fill(canvas, mask, log)
        if out is not None:
            return OutpaintResult(out, mask, "diffusers", mode)

    filled = _classical_fill(canvas, mask, mode, margin)
    log(f"[outpaint] classical {mode} fill applied")
    return OutpaintResult(filled, mask, "classical", mode)
