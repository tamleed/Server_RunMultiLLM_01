from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionsRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    async_mode: bool | None = Field(default=None, alias="async")
    max_tokens: int | None = None
    temperature: float | None = None
    stream: bool | None = False
    metadata: dict[str, Any] | None = None


class JobCreateRequest(BaseModel):
    model: str
    payload: dict[str, Any]


class JobCreateResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    requested_model: str
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: float | None = None
    error: str | None = None


class JobResultResponse(BaseModel):
    job_id: str
    status: JobStatus
    result: dict[str, Any] | None = None


class SwitchRequest(BaseModel):
    model: str


class QueueStatusResponse(BaseModel):
    queue_length: int
    current_job_id: str | None
    active_model: str | None
    switching: bool
