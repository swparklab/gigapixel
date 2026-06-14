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
    stitch_planar_exposure_compensation: bool = True
    stitch_planar_seam_finding: bool = True
    stitch_planar_multiband_bands: int = 5
    stitch_planar_multiband_max_pixels: int = 120_000_000

    # --- AI / learned feature matching ---------------------------------------
    # Matcher backend: "auto" prefers a learned matcher when torch+kornia are
    # installed and falls back to the classical detector otherwise.
    #   auto | loftr | disk_lightglue | sift_lightglue | aliked_lightglue
    #   | classic (force SIFT/ORB)
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
    # Deep global-descriptor backend used for retrieval: auto | dinov2 | classical.
    # "classical" (thumbnail color+gradient embedding) always works; "dinov2"
    # upgrades to learned embeddings when torch is available.
    stitch_retrieval_model: str = "auto"
    # Top-K most-similar neighbours retrieved per image.
    stitch_retrieval_top_k: int = 8
    # In "auto", use retrieval once the set has at least this many images.
    stitch_retrieval_min_images: int = 12

    # --- Learned no-reference image quality (QC) -----------------------------
    stitch_quality_iqa: bool = True
    # auto | pyiqa | classical. "auto" uses pyiqa (CLIP-IQA) when installed.
    stitch_quality_iqa_backend: str = "auto"
    # Perceptual score (0..1, higher is better) below this adds a warning.
    stitch_quality_iqa_warn: float = 0.30

    # --- SAM smart annotation ------------------------------------------------
    sam_enabled: bool = True
    # auto | sam | classical. "classical" uses GrabCut so click-segmentation
    # works without model weights; "sam" uses Segment Anything when available.
    sam_backend: str = "auto"
    sam_model_type: str = "vit_h"
    sam_checkpoint: str = ""  # filesystem path to the SAM checkpoint
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
    splat_depth_backend: str = "auto"     # auto | depth_anything | midas | relief
    splat_max_points: int = 1_500_000     # cap on emitted 3D primitives
    splat_depth_strength: float = 0.35    # relief depth amplitude (0..1)
    splat_format: str = "both"            # pointcloud | gaussian | both

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
