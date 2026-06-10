from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    app_name: str = "Gigapixel Heritage Viewer"
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
