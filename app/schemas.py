import datetime as dt

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    name: str = Field(default="Untitled Session", max_length=255)


class SessionRead(BaseModel):
    id: str
    name: str
    status: str
    image_count: int
    width: int | None = None
    height: int | None = None
    created_at: dt.datetime
    updated_at: dt.datetime
    error_message: str | None = None
    share_url: str
    tags: str | None = None
    pixels_per_mm: float | None = None
    pid: str | None = None


class SessionSummary(BaseModel):
    id: str
    name: str
    status: str
    width: int | None = None
    height: int | None = None
    tags: str | None = None
    quality_verdict: str | None = None
    created_at: dt.datetime
    thumbnail_url: str | None = None


class MetadataUpdate(BaseModel):
    # Dublin Core / cataloguing fields (all optional, free text).
    title: str | None = None
    creator: str | None = None
    date: str | None = None
    material: str | None = None
    dimensions: str | None = None
    repository: str | None = None
    accession_number: str | None = None
    description: str | None = None
    rights: str | None = None
    subject: str | None = None


class ScaleSetRequest(BaseModel):
    pixels_per_mm: float = Field(gt=0)


class AnnotationCreate(BaseModel):
    x: float
    y: float
    text: str = Field(min_length=1, max_length=2000)
    shape: str = Field(default="point", pattern="^(point|rect|polygon)$")
    w: float | None = None
    h: float | None = None
    points: list[list[float]] | None = None
    tags: str | None = Field(default=None, max_length=500)


class AnnotationRead(BaseModel):
    id: int
    session_id: str
    x: float
    y: float
    text: str
    shape: str = "point"
    w: float | None = None
    h: float | None = None
    points: list[list[float]] | None = None
    tags: str | None = None
    created_at: dt.datetime


class SegmentRequest(BaseModel):
    # All coordinates are in full-resolution mosaic pixels.
    point_x: float | None = None
    point_y: float | None = None
    box_x: float | None = None
    box_y: float | None = None
    box_w: float | None = None
    box_h: float | None = None


class SegmentResponse(BaseModel):
    backend: str
    polygon: list[list[float]]


class DamageRegion(BaseModel):
    x: int
    y: int
    w: int
    h: int
    length: int


class DamageResponse(BaseModel):
    backend: str
    regions: list[DamageRegion]


class ScaleRequest(BaseModel):
    # Either provide a reference (two points + mm) or rely on a fiducial marker.
    point_a_x: float | None = None
    point_a_y: float | None = None
    point_b_x: float | None = None
    point_b_y: float | None = None
    length_mm: float | None = None
    marker_length_mm: float | None = None


class ScaleResponse(BaseModel):
    calibrated: bool
    method: str
    pixels_per_mm: float | None = None
    dpi: float | None = None
    marker_id: int | None = None
    note: str = ""


class ChangeDetectRequest(BaseModel):
    other_session_id: str
    sensitivity: float = Field(default=0.12, ge=0.02, le=0.9)


class ChangeRegion(BaseModel):
    x: int
    y: int
    w: int
    h: int
    area: int


class ChangeDetectResponse(BaseModel):
    aligned: bool
    change_fraction: float
    regions: list[ChangeRegion]
    note: str = ""


class FocusStackResponse(BaseModel):
    ok: bool
    output: str
    frames: int


class PhotometricRequest(BaseModel):
    # One [x, y, z] light direction per source image, in capture order.
    light_dirs: list[list[float]]


class PhotometricResponse(BaseModel):
    ok: bool
    normal_map: str
    albedo: str


class ConditionResponse(BaseModel):
    backend: str
    crack_density: float
    discolour_fraction: float
    cracks: list[dict]
    discolouration: list[dict]
    overlay_url: str


class RestoreResponse(BaseModel):
    ok: bool
    backend: str
    actions: list[str]
    before_url: str
    after_url: str
    compare_url: str


class SplatResponse(BaseModel):
    ok: bool
    num_points: int
    depth_backend: str
    pointcloud_url: str | None = None
    gaussian_url: str | None = None
    explorer_url: str


class ReconResponse(BaseModel):
    ok: bool
    backend: str
    num_points: int
    pointcloud_url: str | None = None
    gaussian_url: str | None = None
    mesh_url: str | None = None
    mesh_backend: str = ""
    num_faces: int = 0
    explorer_url: str
    note: str = ""


class TagsResponse(BaseModel):
    backend: str
    tags: list[dict]


class SearchResult(BaseModel):
    session_id: str
    score: float


class SearchResponse(BaseModel):
    backend: str
    query: str
    results: list[SearchResult]


class CoverageResponse(BaseModel):
    image_count: int
    pair_count: int
    connected: bool
    components: int
    verdict: str
    weak_images: list[dict]
    isolated_images: list[str]
    recommendations: list[str]


class OutpaintRequest(BaseModel):
    mode: str = Field(default="fill_borders", pattern="^(fill_borders|extend)$")
    margin: int = Field(default=256, ge=8, le=4096)


class OutpaintResponse(BaseModel):
    ok: bool
    backend: str
    mode: str
    width: int
    height: int
    generated_fraction: float
    image_url: str
    mask_url: str


class UpscaleRequest(BaseModel):
    factor: float = Field(default=2.0, ge=1.1, le=8.0)
    backend: str | None = Field(default=None, pattern="^(auto|comfyui|diffusers|realesrgan|classical)$")


class UpscaleResponse(BaseModel):
    ok: bool
    backend: str
    factor: float
    width: int
    height: int
    image_url: str


class To3DRequest(BaseModel):
    representation: str = Field(
        default="splat", pattern="^(splat|pointcloud|gaussian|mesh|object|depth|normals|material|all)$"
    )


class To3DResponse(BaseModel):
    ok: bool
    representation: str
    depth_backend: str
    num_points: int
    artifacts: dict[str, str]


class WatermarkRequest(BaseModel):
    recipient: str = Field(min_length=1, max_length=200)
    identifier: str | None = Field(default=None, max_length=200)


class WatermarkResponse(BaseModel):
    ok: bool
    payload: str
    token: str
    phash: str
    download_url: str


class VerifyResponse(BaseModel):
    watermark_found: bool
    recipient: str | None = None
    payload: str | None = None
    match_fraction: float
    tampered: bool
    phash_distance: int
    tampered_fraction: float = 0.0
    tamper_mask_url: str | None = None
    backend: str | None = None


class LicenseRequest(BaseModel):
    recipient: str = Field(min_length=1, max_length=200)
    tier: str = Field(default="viewer", max_length=40)
    days: int = Field(default=365, ge=1, le=36500)


class LicenseResponse(BaseModel):
    token: str
    recipient: str
    tier: str
    exp: int
    signed: bool


class TimelineRequest(BaseModel):
    others: list[str] = Field(min_length=1)
    sensitivity: float = Field(default=0.12, ge=0.02, le=0.9)


class ExportPresetRequest(BaseModel):
    preset: str = Field(default="web", pattern="^(hologram|xr|web)$")


class ProcessRequest(BaseModel):
    mode: str = Field(default="scans", pattern="^(scans|panorama)$")


class ProcessResponse(BaseModel):
    message: str
    session_id: str
    status: str


class AcquisitionPlanRequest(BaseModel):
    camera_width: int = Field(default=6000, gt=0, le=200000)
    camera_height: int = Field(default=4000, gt=0, le=200000)
    target_width: int = Field(default=30000, gt=0, le=1000000)
    target_height: int = Field(default=30000, gt=0, le=1000000)
    overlap_percent: float = Field(default=80.0, ge=0.0, lt=100.0)
    focus_stack_shots: int = Field(default=6, ge=1, le=100)
    safe_shots_per_battery: int = Field(default=250, ge=1, le=100000)


class AcquisitionScenarioRead(BaseModel):
    overlap_percent: float
    columns: int
    rows: int
    positions: int
    captures: int
    coverage_width: int
    coverage_height: int
    step_x: float
    step_y: float
    batteries: int


class AcquisitionPlanRead(BaseModel):
    camera_width: int
    camera_height: int
    target_width: int
    target_height: int
    focus_stack_shots: int
    safe_shots_per_battery: int
    selected: AcquisitionScenarioRead
    scenarios: list[AcquisitionScenarioRead]
    recommendation: str
