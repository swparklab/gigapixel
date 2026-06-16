"""Interactive high-quality upscaling of the final mosaic, run locally.

The operator picks a factor (2x / 4x / ...) on the finished result and runs a
local upscale. Backends (``upscale_backend``):

* ``comfyui``   — submit a ComfyUI upscale workflow (e.g. a Flux refiner /
  ultimate-SD-upscale graph) to a configured local ComfyUI server.
* ``diffusers`` — a local Stable-Diffusion x4 upscaler, applied tile-by-tile so
  large mosaics fit in VRAM.
* ``realesrgan``— Real-ESRGAN super-resolution.
* ``classical`` — Lanczos upscaling + edge-aware denoise + unsharp (always on).

The output is written as a non-archival ``stitched_upscaled.jpg`` variant.
"""

from __future__ import annotations

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
class UpscaleResult:
    image: np.ndarray
    backend: str
    factor: float


def _classical(bgr: np.ndarray, factor: float, log: LogFn) -> np.ndarray:
    denoised = cv2.fastNlMeansDenoisingColored(bgr, None, 3, 3, 7, 21)
    up = cv2.resize(denoised, None, fx=factor, fy=factor, interpolation=cv2.INTER_LANCZOS4)
    blur = cv2.GaussianBlur(up, (0, 0), 1.1)
    sharp = cv2.addWeighted(up, 1.45, blur, -0.45, 0)
    log(f"[upscale] classical Lanczos x{factor:g}")
    return np.clip(sharp, 0, 255).astype(np.uint8)


def _hat(bgr: np.ndarray, factor: float, log: LogFn) -> np.ndarray | None:
    """HAT (Hybrid Attention Transformer, 2023/2024) super-resolution.

    Outperforms Real-ESRGAN on PSNR/SSIM benchmarks for photographic content.
    Supports x2/x4 scale. Requires ``basicsr`` and HAT checkpoint from HuggingFace
    (XPixelGroup/HAT-L_SRx4_ImageNet-pretrain or Real_HAT_GAN_SRx4).
    pip install basicsr
    """
    try:
        import torch  # type: ignore
        from basicsr.archs.hat_arch import HAT as HATModel  # type: ignore
        from basicsr.utils import img2tensor, tensor2img  # type: ignore
        import yaml  # type: ignore
        from pathlib import Path as _Path
    except Exception:
        return None
    try:
        scale = int(round(factor))
        if scale not in (2, 4):
            return None
        checkpoint_path = str(getattr(settings, f"hat_checkpoint_x{scale}", "") or "").strip()
        if not checkpoint_path or not _Path(checkpoint_path).exists():
            # Try HuggingFace hub download if huggingface_hub is available.
            try:
                from huggingface_hub import hf_hub_download  # type: ignore
                repo = "XPixelGroup/HAT"
                filename = f"Real_HAT_GAN_SRx{scale}.pth"
                checkpoint_path = hf_hub_download(repo_id=repo, filename=f"experiments/pretrained_models/{filename}")
            except Exception:
                return None

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = HATModel(
            upscale=scale,
            in_chans=3,
            img_size=64,
            window_size=16,
            compress_ratio=3,
            squeeze_factor=30,
            conv_scale=0.01,
            overlap_ratio=0.5,
            img_range=1.0,
            depths=[6, 6, 6, 6, 6, 6],
            embed_dim=180,
            num_heads=[6, 6, 6, 6, 6, 6],
            mlp_ratio=2,
            upsampler="pixelshuffle",
            resi_connection="1conv",
        ).to(device).eval()
        state = torch.load(checkpoint_path, map_location=device, weights_only=True)
        model.load_state_dict(state.get("params_ema", state.get("params", state)), strict=False)

        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        tensor = torch.from_numpy(rgb.transpose(2, 0, 1))[None].to(device)
        with torch.inference_mode():
            out = model(tensor).squeeze(0).clamp(0, 1).cpu().numpy()
        result = cv2.cvtColor((out.transpose(1, 2, 0) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
        log(f"[upscale] HAT x{scale}")
        return result
    except Exception as exc:
        log(f"[upscale] HAT failed: {exc}")
        return None


def _supir(bgr: np.ndarray, factor: float, log: LogFn) -> np.ndarray | None:
    """SUPIR (2024): generative upscaling with SDXL + SUPIR-v0Q checkpoint.

    Produces photorealistic detail restoration at 4x–8x, best quality for
    heritage digitization. Requires ~24 GB VRAM for full quality; F model
    (~12 GB) available as a lighter option.
    pip install SUPIR  (or clone from github.com/Fanghua-Yu/SUPIR)
    """
    try:
        from SUPIR.util import create_SUPIR_model, PIL2Tensor, Tensor2PIL  # type: ignore
        from PIL import Image as _PIL  # type: ignore
        import torch  # type: ignore
    except Exception:
        return None
    try:
        ckpt = str(getattr(settings, "supir_checkpoint", "") or "").strip()
        sdxl_ckpt = str(getattr(settings, "supir_sdxl_checkpoint", "") or "").strip()
        if not ckpt:
            return None
        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cpu":
            log("[upscale] SUPIR requires CUDA; skipping")
            return None
        model = create_SUPIR_model("options/SUPIR_v0.yaml", SUPIR_sign="Q").to(device)
        model.load_state_dict(torch.load(ckpt, map_location=device, weights_only=True), strict=False)
        model.eval()
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        lq = PIL2Tensor(_PIL.fromarray(rgb)).unsqueeze(0).to(device)
        with torch.inference_mode():
            results = model.batchify_sample(lq, a_prompt="high resolution, detailed", n_a_prompt="", edm_steps=50, s_stage1=-1, s_cfg=7.5, seed=42)
        out = Tensor2PIL(results[0].squeeze(0).clamp(-1, 1))
        result = cv2.cvtColor(np.array(out), cv2.COLOR_RGB2BGR)
        if factor != 4.0:
            h, w = bgr.shape[:2]
            result = cv2.resize(result, (int(w * factor), int(h * factor)), interpolation=cv2.INTER_LANCZOS4)
        log("[upscale] SUPIR generative upscale")
        return result
    except Exception as exc:
        log(f"[upscale] SUPIR failed: {exc}")
        return None


def _realesrgan(bgr: np.ndarray, factor: float, log: LogFn) -> np.ndarray | None:
    try:
        from .enhance import _RealEsrgan

        out = _RealEsrgan.enhance(bgr, int(round(factor)))
        if out is not None:
            log(f"[upscale] Real-ESRGAN x{factor:g}")
            return out
    except Exception:
        pass
    return None


def _diffusers_tiled(bgr: np.ndarray, factor: float, log: LogFn) -> np.ndarray | None:
    try:
        import torch  # type: ignore
        from diffusers import StableDiffusionUpscalePipeline  # type: ignore
        from PIL import Image
    except Exception:
        return None
    try:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        pipe = StableDiffusionUpscalePipeline.from_pretrained(
            "stabilityai/stable-diffusion-x4-upscaler",
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        ).to(device)
        # SD upscaler is fixed x4; tile the input, upscale each, then resize to factor.
        tile = max(128, int(settings.upscale_tile) // 4)
        ov = max(8, int(settings.upscale_tile_overlap) // 4)
        h, w = bgr.shape[:2]
        out4 = np.zeros((h * 4, w * 4, 3), np.uint8)
        for y in range(0, h, tile - ov):
            for x in range(0, w, tile - ov):
                y1, x1 = min(h, y + tile), min(w, x + tile)
                patch = cv2.cvtColor(bgr[y:y1, x:x1], cv2.COLOR_BGR2RGB)
                up = pipe(prompt="high quality, sharp, detailed", image=Image.fromarray(patch)).images[0]
                up_bgr = cv2.cvtColor(np.array(up), cv2.COLOR_RGB2BGR)
                out4[y * 4 : y1 * 4, x * 4 : x1 * 4] = up_bgr[: (y1 - y) * 4, : (x1 - x) * 4]
        result = cv2.resize(out4, (int(w * factor), int(h * factor)), interpolation=cv2.INTER_LANCZOS4)
        log(f"[upscale] diffusers SD-x4 tiled -> x{factor:g}")
        return result
    except Exception as exc:
        log(f"[upscale] diffusers failed: {exc}")
        return None


def _comfyui(bgr: np.ndarray, factor: float, target_w: int, target_h: int, log: LogFn) -> np.ndarray | None:
    url = str(settings.comfyui_url).rstrip("/")
    wf_path = str(settings.comfyui_upscale_workflow_path or settings.comfyui_workflow_path)
    if not url or not wf_path or not Path(wf_path).exists():
        return None
    try:
        import urllib.parse
        import urllib.request

        def _post(path, data, headers):
            return urllib.request.urlopen(urllib.request.Request(url + path, data=data, headers=headers, method="POST"), timeout=30)

        ok, buf = cv2.imencode(".png", bgr)
        boundary = "----hgaboundary"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"hga_up.png\"\r\n"
            "Content-Type: image/png\r\n\r\n"
        ).encode() + buf.tobytes() + f"\r\n--{boundary}--\r\n".encode()
        up = _post("/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        image_name = json.loads(up.read()).get("name", "hga_up.png")

        workflow = json.loads(Path(wf_path).read_text(encoding="utf-8"))
        nodes = workflow.get("prompt", workflow)
        for node in nodes.values():
            if isinstance(node, dict) and node.get("class_type") == "LoadImage":
                node.setdefault("inputs", {})["image"] = image_name
                break
        res = _post("/prompt", json.dumps({"prompt": nodes}).encode(), {"Content-Type": "application/json"})
        prompt_id = json.loads(res.read())["prompt_id"]
        for _ in range(900):
            with urllib.request.urlopen(f"{url}/history/{prompt_id}", timeout=15) as h:
                hist = json.loads(h.read())
            if prompt_id in hist:
                break
            time.sleep(1.0)
        else:
            return None
        for node_out in hist[prompt_id].get("outputs", {}).values():
            for img in node_out.get("images", []):
                q = urllib.parse.urlencode({"filename": img["filename"], "subfolder": img.get("subfolder", ""), "type": img.get("type", "output")})
                with urllib.request.urlopen(f"{url}/view?{q}", timeout=60) as v:
                    raw = np.frombuffer(v.read(), np.uint8)
                result = cv2.imdecode(raw, cv2.IMREAD_COLOR)
                if result is not None:
                    log("[upscale] ComfyUI workflow upscaled the image")
                    return cv2.resize(result, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
        return None
    except Exception as exc:
        log(f"[upscale] ComfyUI failed: {exc}")
        return None


def upscale_image(bgr: np.ndarray, factor: float, log: LogFn = _noop) -> UpscaleResult:
    factor = float(max(1.1, min(factor, int(settings.upscale_max_factor))))
    h, w = bgr.shape[:2]
    target_w, target_h = int(round(w * factor)), int(round(h * factor))

    requested = str(settings.upscale_backend).lower()
    # auto priority: ComfyUI (user workflow) > SUPIR (generative SOTA) >
    #   HAT (transformer SR, best PSNR) > diffusers > Real-ESRGAN > classical
    order = {
        "comfyui": ["comfyui"],
        "supir": ["supir"],
        "hat": ["hat"],
        "diffusers": ["diffusers"],
        "realesrgan": ["realesrgan"],
        "classical": ["classical"],
    }.get(requested, ["comfyui", "supir", "hat", "diffusers", "realesrgan", "classical"])

    for backend in order:
        out = None
        if backend == "comfyui":
            out = _comfyui(bgr, factor, target_w, target_h, log)
        elif backend == "supir":
            out = _supir(bgr, factor, log)
        elif backend == "hat":
            out = _hat(bgr, factor, log)
        elif backend == "diffusers":
            out = _diffusers_tiled(bgr, factor, log)
        elif backend == "realesrgan":
            out = _realesrgan(bgr, factor, log)
        else:
            out = _classical(bgr, factor, log)
        if out is not None:
            if (out.shape[1], out.shape[0]) != (target_w, target_h):
                out = cv2.resize(out, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
            return UpscaleResult(out, backend, factor)

    return UpscaleResult(_classical(bgr, factor, log), "classical", factor)
