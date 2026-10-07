from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]


class RectPayload(BaseModel):
    """Pixel rectangle using the frontend's x/y/w/h vocabulary.

    ``width``/``height`` are accepted as input aliases so this boundary can
    also consume the frame_repair core vocabulary without changing the UI.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    x: NonNegativeInt
    y: NonNegativeInt
    w: PositiveInt = Field(validation_alias=AliasChoices("w", "width"), serialization_alias="w")
    h: PositiveInt = Field(validation_alias=AliasChoices("h", "height"), serialization_alias="h")

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def as_list(self) -> list[int]:
        return [self.x, self.y, self.w, self.h]


class RepairSubmissionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    page_id: str = Field(alias="pageId", min_length=1, max_length=256)
    image_id: str | None = Field(alias="imageId", default=None, min_length=1, max_length=256)
    base_version_id: str = Field(alias="baseVersionId", min_length=1, max_length=256)
    target_ratio: Literal["1:1", "16:9", "9:16"] = Field(alias="targetRatio")
    target_rect: RectPayload = Field(alias="targetRect")
    context_expansion_enabled: bool = Field(alias="contextExpansionEnabled", default=False)
    context_margin_px: NonNegativeInt = Field(alias="contextMarginPx", default=0)
    context_rect: RectPayload = Field(alias="contextRect")
    issue_text: str = Field(alias="issueText", min_length=1, max_length=4000)
    instruction: str = Field(min_length=1, max_length=4000)
    preserve_text: str = Field(alias="preserveText", default="", max_length=4000)
    idempotency_key: str | None = Field(
        alias="idempotencyKey", default=None, min_length=1, max_length=256
    )


class PreviewInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    state: Literal["ready"] = "ready"
    available: bool = True
    # The adapter is deliberately reported as data from the backend.  The
    # first MVP only used the deterministic adapter, while uploaded pages can
    # now be executed by the Codex CLI adapter as well.
    origin: str = "deterministic_adapter"
    provider: str = "local-deterministic"
    codex_verified: bool = Field(False, alias="codexVerified")
    applied: bool = False
    message: str = "Synthetic deterministic preview; no Codex image edit was executed."
    target_size: tuple[int, int] = Field(alias="targetSize")
    context_size: tuple[int, int] = Field(alias="contextSize")
    preview_url: str | None = Field(default=None, alias="previewUrl")


class RepairJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    annotation_id: str = Field(alias="annotationId")
    status: Literal[
        "queued",
        "running",
        "review",
        "accepted",
        "failed",
        "rejected",
        "cancelled",
        "version_conflict",
    ]
    execution_status: Literal[
        "queued",
        "running",
        "preview_ready",
        "failed",
        "cancelled",
        "interrupted",
        "version_conflict",
    ] = Field(alias="executionStatus")
    review_status: Literal["pending", "accepted", "rejected"] = Field(alias="reviewStatus")
    ratio: Literal["1:1", "16:9", "9:16"]
    target_rect: RectPayload = Field(alias="targetRect")
    context_rect: RectPayload = Field(alias="contextRect")
    created_at: datetime = Field(alias="createdAt")
    issue_text: str = Field(alias="issueText")
    page_id: str = Field(alias="pageId")
    base_version_id: str = Field(alias="baseVersionId")
    adapter: str
    preview: PreviewInfo | None = None
    accepted_at: datetime | None = Field(default=None, alias="acceptedAt")
    rejected_at: datetime | None = Field(default=None, alias="rejectedAt")
    error_code: str | None = Field(default=None, alias="errorCode")
    error_message: str | None = Field(default=None, alias="errorMessage")
    idempotency_key: str = Field(alias="idempotencyKey")
    accepted_version_id: str | None = Field(default=None, alias="acceptedVersionId")
    preview_url: str | None = Field(default=None, alias="previewUrl")


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accept", "reject"]
