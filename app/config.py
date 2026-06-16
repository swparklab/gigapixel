from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    app_name: str = "Hyper Gigapixel Agent"
    api_prefix: str = "/api"
    data_root: Path = PROJECT_ROOT / "data"
    database_path: Path = PROJECT_ROOT / "data" / "gigapixel.db"
    allow_origins: list[str] = Field(default_factory=lambda: ["*"])
    max_upload_files: int = 1000
    max_source_pixels: int = 10_000_000_000
    tile_size: int = 256
    tile_overlap: int = 1
    optimized_jpeg_quality: int = 85
    agent_poll_interval_seconds: float = 1.0
    # Run the processing agent worker inside the API server process so a single
    # `uvicorn app.main:app` launch starts both the API and the queue worker.
    # Set to false to run a dedicated worker (`python -m app.agent`) instead.
    embedded_agent: bool = True
    log_level: str = "INFO"
    log_format: str = "json"
    raw_stitched_format: str = "bigtiff"
    raw_bigtiff_compression: str = "none"
    stitch_registration_megapix: float = 2.0
    stitch_seam_megapix: float = 0.8
    stitch_compositing_megapix: float = -1.0
    stitch_confidence_threshold: float = 0.65
    stitch_feature_detector: str = "sift"
    stitch_planar_enabled: bool = True
    stitch_planar_preview_max_dim: int = 3200
    stitch_planar_max_features: int = 8000
    stitch_planar_max_match_samples: int = 800
    stitch_planar_min_inliers: int = 30
    stitch_planar_match_ratio: float = 0.72
    stitch_planar_ransac_threshold: float = 4.0
    stitch_planar_blend_width: int = 96
    stitch_planar_exhaustive_limit: int = 80
    stitch_planar_neighbor_window: int = 12
    stitch_planar_transform_model: str = "affine"
    stitch_planar_global_optimize: bool = True
    # Equalise per-image sharpness before feature detection so keypoints are
    # consistent across captures with slightly different focus.
    stitch_focus_normalize: bool = True
    # Optical-flow elastic alignment of overlaps before blending. Removes the
    # residual ghosting/"breaking" that rigid global alignment cannot fix when
    # focus or detected points differ slightly between images.
    stitch_planar_local_align: bool = True
    stitch_local_align_max_disp: int = 24       # px clamp on local correction
    stitch_local_align_backend: str = "auto"    # auto | raft | classical
    stitch_planar_exposure_compensation: bool = True
    stitch_planar_seam_finding: bool = True
    stitch_planar_multiband_bands: int = 5
    stitch_planar_multiband_max_pixels: int = 120_000_000

    # --- AI / learned feature matching ---------------------------------------
    # Matcher backend: "auto" prefers a learned matcher when torch+kornia are
    # installed and falls back to the classical detector otherwise.
    #   auto | roma | loftr | xfeat | disk_lightglue | sift_lightglue
    #   | aliked_lightglue | classic (force SIFT/ORB)
    # roma   — SOTA dense matching (2024), best recall on low-texture surfaces
    # xfeat  — ultra-fast, CPU-friendly (pip install accelerated-features)
    # loftr  — reliable dense matching via kornia
    stitch_matcher: str = "auto"
    # Compute device for learned matchers: "auto" | "cuda" | "cpu".
    stitch_matcher_device: str = "auto"
    # Long-edge size (px) the learned matcher runs at. Higher = more accurate
    # correspondences at higher cost. Heritage captures benefit from large values.
    stitch_matcher_input_dim: int = 1600
    # Optional tiled inference for very high-resolution overlaps (LoFTR only).
    stitch_matcher_tiles: int = 1
    # Confidence cutoff for learned dense matches before RANSAC.
    stitch_matcher_min_confidence: float = 0.2
    # Max learned correspondences kept per image pair (top-confidence).
    stitch_matcher_max_matches: int = 4000

    # --- Robust global bundle adjustment -------------------------------------
    # Iteratively reweighted least squares (Huber) on top of the linear solve.
    stitch_planar_robust_refine: bool = True
    stitch_planar_robust_iterations: int = 8
    # Huber transition (in pixels of reprojection residual).
    stitch_planar_huber_delta: float = 3.0

    # --- Gigapixel blending ---------------------------------------------------
    # Use a tiled multi-band blender so gigapixel canvases keep multi-band
    # quality instead of degrading to the streaming feather fallback.
    stitch_planar_tiled_multiband: bool = True
    stitch_planar_tile_pixels: int = 96_000_000
    stitch_planar_tile_overlap: int = 512

    # --- Lens distortion correction ------------------------------------------
    # Undistort source images before registration and compositing. Disabled by
    # default because a wrong model hurts more than it helps. Provide radial
    # (k1, k2) and tangential (p1, p2) coefficients for your lens, or enable
    # `stitch_lens_auto` to look them up from EXIF via lensfunpy when installed.
    stitch_lens_correction: bool = False
    stitch_lens_auto: bool = False
    stitch_lens_k1: float = 0.0
    stitch_lens_k2: float = 0.0
    stitch_lens_p1: float = 0.0
    stitch_lens_p2: float = 0.0
    # Focal length as a fraction of the image long edge, used to build the
    # intrinsic matrix when only distortion coefficients are supplied.
    stitch_lens_focal_ratio: float = 1.0

    # --- Raw BigTIFF output --------------------------------------------------
    # Write a tiled BigTIFF so gigapixel outputs support efficient partial reads
    # (pyvips DZI generation, OpenSeadragon, GIS tools).
    raw_bigtiff_tiled: bool = True
    raw_bigtiff_tile_size: int = 512

    # --- Stitch quality assessment (QC) --------------------------------------
    # Inspect the final mosaic for defects (interior holes, low coverage, blur,
    # seam/ghost discontinuities) and emit a quality_report.json sidecar.
    stitch_quality_check: bool = True
    # Long edge (px) the analysis runs at; defects are located here then mapped
    # back to full resolution for repair.
    stitch_quality_max_dim: int = 6000
    # A pixel whose max channel value is <= this is treated as unfilled/empty.
    stitch_quality_empty_threshold: int = 6
    # Coverage (filled fraction of the content bbox) below this is a warning.
    stitch_quality_min_coverage: float = 0.985
    # Interior-hole area (fraction of content) thresholds for warn/fail.
    stitch_quality_hole_area_warn: float = 0.0005
    stitch_quality_hole_area_fail: float = 0.02
    # Laplacian-variance sharpness below this flags a blurred/ghosted result.
    stitch_quality_min_sharpness: float = 4.0
    # Registration RMS (px) thresholds for warn/fail when available.
    stitch_quality_rms_warn: float = 3.0
    stitch_quality_rms_fail: float = 8.0

    # --- Automatic repair of broken regions ----------------------------------
    stitch_auto_repair: bool = True
    # Inpainting backend: auto | classical | lama | none.
    # "auto" uses a deep model (LaMa) when available, else classical inpainting.
    stitch_repair_backend: str = "auto"
    # Refuse to inpaint when interior holes exceed this fraction of content
    # (too large to reconstruct credibly).
    stitch_repair_max_hole_fraction: float = 0.25
    # Dilation (px) applied to hole masks before inpainting.
    stitch_repair_dilate: int = 6
    # Classical inpainting radius (px).
    stitch_repair_inpaint_radius: int = 6

    # --- Deep retrieval overlap graph ----------------------------------------
    # How candidate image pairs are chosen before expensive matching.
    #   auto | exhaustive | neighbor | retrieval
    # "auto" picks exhaustive for small sets, deep retrieval for large/unordered
    # sets, and the neighbor window otherwise.
    stitch_pair_selection: str = "auto"
    # Deep global-descriptor backend for overlap retrieval:
    #   auto | siglip | dinov2 | classical
    # siglip  — best for heritage repetitive patterns (Google 2024, ~1.5 GB)
    # dinov2  — lightweight SOTA (Facebook, ~85 MB small variant)
    # classical — thumbnail color+gradient, no GPU needed
    stitch_retrieval_model: str = "auto"
    # HuggingFace model ID for SigLIP (only used when stitch_retrieval_model=siglip).
    stitch_retrieval_siglip_model: str = "google/siglip-so400m-patch14-384"
    # Top-K most-similar neighbours retrieved per image.
    stitch_retrieval_top_k: int = 8
    # In "auto", use retrieval once the set has at least this many images.
    stitch_retrieval_min_images: int = 12

    # --- Learned no-reference image quality (QC) -----------------------------
    stitch_quality_iqa: bool = True
    # auto | qalign | topiq | pyiqa | classical
    # qalign  — LLM-based IQA, highest human correlation (requires GPU ~7 GB)
    # topiq   — SOTA transformer IQA via pyiqa (better than CLIP-IQA)
    # pyiqa   — CLIP-IQA via pyiqa package
    # classical — heuristic sharpness/contrast/colourfulness
    stitch_quality_iqa_backend: str = "auto"
    # HuggingFace model for Q-Align (qalign backend).
    qalign_model: str = "q-future/one-align"
    # Perceptual score (0..1, higher is better) below this adds a warning.
    stitch_quality_iqa_warn: float = 0.30

    # --- SAM smart annotation ------------------------------------------------
    sam_enabled: bool = True
    # auto | sam2 | efficient_sam | sam | classical
    # sam2          — best accuracy (Meta 2024); pip install sam2
    # efficient_sam — 20x faster than SAM, near-quality (Microsoft 2024)
    # sam           — original SAM v1
    # classical     — GrabCut, no model weights required
    sam_backend: str = "auto"
    sam_model_type: str = "vit_h"
    sam_checkpoint: str = ""  # SAM v1 checkpoint path
    # SAM2 settings (auto-downloaded from HuggingFace when no checkpoint set).
    sam2_checkpoint: str = ""
    sam2_config: str = "sam2_hiera_large.yaml"
    sam2_hf_model: str = "facebook/sam2-hiera-small"
    # EfficientSAM settings.
    efficient_sam_checkpoint: str = ""
    # Max crop (px) sent to the segmenter around the requested region.
    sam_max_region: int = 2048

    # --- AI output enhancement (super-resolution / denoise) ------------------
    # Generative; OFF by default. Produces a non-archival "enhanced" variant.
    stitch_enhance: bool = False
    # auto | realesrgan | classical. "classical" = Lanczos upscale + denoise.
    stitch_enhance_backend: str = "auto"
    stitch_enhance_scale: int = 2
    stitch_enhance_denoise: bool = True
    # Skip enhancement when the output already exceeds this many pixels.
    stitch_enhance_max_pixels: int = 600_000_000

    # --- Color / radiometric calibration (archival accuracy) -----------------
    # Detect a ColorChecker-style target, white-balance, and report CIE dE2000
    # against reference patches. Writes a color_report.json sidecar.
    color_management: bool = True
    color_target_auto: bool = True        # auto-detect the colour target
    color_working_space: str = "sRGB"
    # Informational conformance profile for the QC report: fadgi | metamorfoze.
    color_conformance_target: str = "fadgi"

    # --- Dimensional scale calibration ---------------------------------------
    # Recover real-world units from a fiducial marker (ArUco) or a known
    # reference length so outputs carry mm/px and DPI.
    scale_calibration: bool = True
    scale_marker_dict: str = "DICT_4X4_50"
    scale_marker_length_mm: float = 0.0   # physical marker side length (mm)

    # --- Focus stacking (all-in-focus fusion) --------------------------------
    focus_stack_align: bool = True
    focus_stack_method: str = "laplacian"  # laplacian | wavelet

    # --- Provenance / uncertainty layers -------------------------------------
    # Emit ancillary masks separating measured vs reconstructed pixels and a
    # local uncertainty proxy, so synthetic pixels are never mistaken for data.
    provenance_maps: bool = True

    # --- Processing manifest, fixity, descriptive metadata -------------------
    processing_manifest: bool = True       # machine-readable provenance + SHA-256
    embed_metadata: bool = True            # Dublin Core / XMP sidecar

    # --- IIIF interoperability -----------------------------------------------
    # Emit an IIIF Image API info.json and a Presentation manifest alongside DZI,
    # and serve a live IIIF Image API 3.0 endpoint (region/size/rotation/quality).
    iiif_enabled: bool = True
    iiif_base_url: str = ""                # external base URL, else relative
    iiif_max_size: int = 4096             # max long edge a single IIIF request returns

    # --- AI condition analysis (cracks + discolouration) ---------------------
    condition_backend: str = "auto"       # auto | deep | classical
    condition_max_dim: int = 4000         # analysis resolution
    condition_crack_sensitivity: float = 0.5   # 0..1
    condition_discolor_sensitivity: float = 0.5

    # --- AI restoration ------------------------------------------------------
    restore_backend: str = "auto"         # auto | deep | classical
    restore_decolor: bool = True          # correct discolouration / yellowing
    restore_decrack: bool = True          # inpaint detected cracks
    restore_denoise: bool = True
    restore_max_dim: int = 0              # 0 = full resolution

    # --- Image-to-3D (Gaussian Splatting / point cloud) ----------------------
    # Depth estimation backend (priority: depth_pro > marigold > unidepth > depth_anything > midas > relief):
    #   auto | depth_pro | marigold | unidepth | depth_anything | depth_anything_v2 | midas | relief
    # depth_pro   — Apple 2024, metric depth, sharpest boundaries (pip install depth-pro)
    # marigold    — ETH Zurich 2024, diffusion depth, best heritage detail (pip install diffusers)
    # unidepth    — ETH Zurich 2024, universal metric depth (pip install unidepth)
    # depth_anything — fast, good quality; Large model used when GPU available
    splat_depth_backend: str = "auto"
    splat_max_points: int = 1_500_000     # cap on emitted 3D primitives
    splat_depth_strength: float = 0.35    # relief depth amplitude (0..1)
    splat_format: str = "both"            # pointcloud | gaussian | both
    # Optical flow backend for local alignment:
    #   auto (default) | dis | searaft | raft | farneback
    # auto/dis — DISOpticalFlow (OpenCV, default, proven behavior)
    # searaft  — SEA-RAFT 2024 (pip install sea-raft), faster than RAFT
    # raft     — RAFT via torchvision (pip install torchvision), SOTA accuracy
    # Note: 'auto' keeps the existing DIS behavior. Set 'searaft' or 'raft'
    # to opt-in to learned flow after validating on your capture set.
    local_align_flow_backend: str = "auto"
    # SEA-RAFT checkpoint path (optional; auto-uses pretrained weights when empty).
    searaft_checkpoint: str = ""

    # --- Image-to-3D representations (3DGS, mesh, depth, normals) -------------
    # Default artefact built by the /to3d endpoint and the 3D explorer.
    #   splat | pointcloud | gaussian | mesh | depth | normals | all
    to3d_default_representation: str = "splat"
    to3d_mesh_max_dim: int = 1400         # grid resolution cap for the relief mesh
    # Deep single-image-to-3D object generator when available.
    #   auto | trellis | hunyuan3d | depth (depth = relief surface, always works)
    to3d_backend: str = "depth"

    # --- Multi-view 3D reconstruction backends --------------------------------
    # auto | noposplat | mvsplat | colmap_gsplat | multiview_depth
    # noposplat    — ICLR 2025 Oral, no poses, feed-forward, MIT license
    # mvsplat      — ECCV 2024 Oral, efficient 12M-param feed-forward, MIT license
    # colmap_gsplat— COLMAP SfM + gsplat training (external tools, GPU required)
    # multiview_depth — always available, no GPU
    recon_backend: str = "auto"
    # NoPoSplat HuggingFace model or checkpoint path.
    noposplat_checkpoint: str = ""        # empty = auto-download cvg/noposplat-re10k
    # MVSplat checkpoint path.
    mvsplat_checkpoint: str = ""

    # --- HAT (Hybrid Attention Transformer) super-resolution checkpoints ------
    hat_checkpoint_x2: str = ""          # path to Real_HAT_GAN_SRx2.pth
    hat_checkpoint_x4: str = ""          # path to Real_HAT_GAN_SRx4.pth

    # --- SUPIR generative upscaling -------------------------------------------
    supir_checkpoint: str = ""           # path to SUPIR-v0Q.ckpt
    supir_sdxl_checkpoint: str = ""      # optional SDXL base checkpoint

    # --- Rights protection / authentication (KOCCA pillar) -------------------
    # Invisible DCT watermark that embeds a per-recipient identifier, plus a
    # perceptual-hash + SHA-256 tamper-authentication record.
    watermark_strength: float = 9.0       # QIM quantisation step (higher = more robust/visible)
    watermark_bits: int = 64
    # Persistent identifier (ARK) Name Assigning Authority Number.
    pid_naan: str = "99999"
    # Encrypted archive key derivation rounds (PBKDF2-HMAC-SHA256).
    archive_encrypt_iterations: int = 200_000
    # Robust watermark backend: auto | trustmark | classical.
    watermark_backend: str = "auto"
    # Block-pHash tamper-localisation grid (NxN blocks).
    watermark_tamper_grid: int = 16

    # --- Licensing / access control -----------------------------------------
    # HMAC secret for signed licence tokens (empty = dev mode, unsigned).
    license_secret: str = ""
    # Access tiers, most→least privileged. Token tier gates download variants.
    license_tiers: list[str] = Field(default_factory=lambda: ["owner", "researcher", "viewer"])

    # --- Offline experience export (hologram / XR) --------------------------
    hologram_layers: int = 6          # depth slices for hologram printing presets

    # --- Job queue robustness ------------------------------------------------
    job_lease_seconds: int = 600          # a claimed job is "stale" past this
    job_heartbeat_seconds: int = 15       # worker heartbeat cadence
    job_max_attempts: int = 3             # retry budget per job
    job_stale_recovery: bool = True       # requeue stale jobs automatically

    # --- Multi-view 3D reconstruction ----------------------------------------
    recon_backend: str = "auto"           # auto | colmap_gsplat | multiview_depth
    recon_max_images: int = 200

    # --- Corpus semantic search / auto-tagging -------------------------------
    semantic_backend: str = "auto"        # auto | clip | classical
    semantic_tag_threshold: float = 0.22

    # --- Acquisition coverage QA ---------------------------------------------
    coverage_min_overlap_inliers: int = 30

    # --- Optional API authentication -----------------------------------------
    # When non-empty, /api requests must carry  X-API-Key: <api_key>.
    api_key: str = ""

    # --- Streaming gigapixel compositor --------------------------------------
    streaming_compositor: bool = True
    streaming_threshold_pixels: int = 800_000_000
    streaming_tile: int = 2048

    # --- Generative outpainting (canvas extension / border fill) -------------
    # Generative; produces a NON-archival variant with generated pixels flagged
    # in an outpaint mask. auto: ComfyUI when configured -> diffusers -> classical.
    outpaint_backend: str = "auto"        # auto | comfyui | diffusers | classical
    outpaint_default_mode: str = "fill_borders"  # fill_borders | extend
    outpaint_margin_px: int = 256         # margin per side for "extend" mode
    outpaint_max_dim: int = 2048          # processing cap for the deep backends
    # Optional auto border-fill at the end of the pipeline (OFF by default).
    stitch_outpaint_fill: bool = False
    # ComfyUI integration (e.g. the Flux Fill outpaint workflow). When both are
    # set, the workflow JSON is submitted to the ComfyUI server with the mosaic
    # injected into its LoadImage node.
    comfyui_url: str = ""                 # e.g. http://127.0.0.1:8188
    comfyui_workflow_path: str = ""       # path to the ComfyUI workflow .json

    # --- Interactive final-result upscaling ----------------------------------
    # Pick a factor on the finished mosaic and run a high-quality upscale locally.
    # auto: ComfyUI (Flux) -> diffusers (SD/Flux img2img) -> Real-ESRGAN -> Lanczos.
    upscale_backend: str = "auto"
    upscale_tile: int = 1024              # tile size for tiled diffusion upscaling
    upscale_tile_overlap: int = 96
    upscale_max_factor: int = 8
    upscale_max_output_pixels: int = 2_000_000_000
    # Optional dedicated ComfyUI upscale workflow (else the outpaint workflow path).
    comfyui_upscale_workflow_path: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path.as_posix()}"


settings = Settings()
settings.data_root.mkdir(parents=True, exist_ok=True)
settings.database_path.parent.mkdir(parents=True, exist_ok=True)
