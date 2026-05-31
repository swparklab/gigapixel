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
