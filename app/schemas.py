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


class AnnotationCreate(BaseModel):
    x: float
    y: float
    text: str = Field(min_length=1, max_length=2000)


class AnnotationRead(BaseModel):
    id: int
    session_id: str
    x: float
    y: float
    text: str
    created_at: dt.datetime


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
