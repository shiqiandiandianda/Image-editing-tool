from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .api_models import RepairJobResponse, RepairSubmissionPayload, ReviewDecision
from .geometry import GeometryError, build_crop_plan
from .models import AspectRatio, Rect
from .service import RepairService, ServiceError

app = FastAPI(title="Image Editing Tool", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["content-type", "idempotency-key", "x-filename"],
)
service = RepairService()


def _service_error(exc: ServiceError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "adapter": "codex_cli" if service._codex_mode else "deterministic_adapter",
        "codexVerified": "false",
        "upload": "ready",
    }


def _raw_upload_parts(body: bytes, content_type: str, filename: str) -> tuple[bytes, str]:
    """Accept raw image bytes and the browser's multipart form without a
    python-multipart dependency.  The frontend sends raw bytes; the small
    multipart parser keeps curl/Postman compatibility for local testing."""
    if content_type.lower().startswith("multipart/form-data"):
        marker = "boundary="
        boundary = content_type.split(marker, 1)[1].strip().strip('"') if marker in content_type else ""
        if boundary:
            token = ("--" + boundary).encode()
            for part in body.split(token):
                if b"filename=" not in part or b"\r\n\r\n" not in part:
                    continue
                header, payload = part.split(b"\r\n\r\n", 1)
                if b"filename=" in header:
                    raw_name = header.split(b"filename=", 1)[1].split(b"\r\n", 1)[0].strip().strip(b'"')
                    if raw_name:
                        filename = raw_name.decode("utf-8", "replace")
                return payload.rstrip(b"\r\n-"), filename
    return body, filename


@app.post("/api/repair/assets", status_code=201)
async def upload_asset(request: Request) -> dict[str, object]:
    """Register an immutable normalized image snapshot for repair jobs."""
    try:
        body = await request.body()
        data, name = _raw_upload_parts(
            body,
            request.headers.get("content-type", "application/octet-stream"),
            request.headers.get("x-filename", "image.png"),
        )
        return service.register_image(data, name=name)
    except ServiceError as exc:
        raise _service_error(exc) from exc


@app.get("/api/repair/pages/{page_id}/image")
def read_page_image(page_id: str) -> Response:
    try:
        return Response(service.page_image(page_id), media_type="image/png")
    except ServiceError as exc:
        raise _service_error(exc) from exc


@app.get("/api/repair/assets/{asset_id}")
def read_asset(asset_id: str) -> Response:
    try:
        return Response(service.asset_bytes(asset_id), media_type="image/png")
    except ServiceError as exc:
        raise _service_error(exc) from exc


@app.get("/api/repair/assets/{asset_id}/current")
def read_current_asset(asset_id: str) -> Response:
    try:
        return Response(service.current_asset_bytes(asset_id), media_type="image/png")
    except ServiceError as exc:
        raise _service_error(exc) from exc


@app.post("/geometry/validate")
def validate_geometry(
    target: Rect,
    ratio: AspectRatio,
    image_width: int,
    image_height: int,
    expand_context: bool = False,
    expansion_pixels: int = 0,
) -> dict[str, object]:
    try:
        plan = build_crop_plan(
            target, ratio, image_width, image_height, expand_context, expansion_pixels
        )
    except GeometryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"target": plan.target.model_dump(), "context": plan.context.model_dump()}


@app.get("/api/repair/jobs", response_model=list[RepairJobResponse])
def list_jobs(include_rejected: bool = Query(default=False)) -> list[RepairJobResponse]:
    return service.list(include_rejected=include_rejected)


@app.post("/api/repair/jobs", response_model=RepairJobResponse, status_code=201)
def create_job(
    payload: RepairSubmissionPayload,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RepairJobResponse:
    try:
        return service.submit(payload, header_idempotency_key=idempotency_key)
    except ServiceError as exc:
        raise _service_error(exc) from exc


@app.get("/api/repair/jobs/{job_id}", response_model=RepairJobResponse)
def read_job(job_id: str) -> RepairJobResponse:
    try:
        return service.get(job_id)
    except ServiceError as exc:
        raise _service_error(exc) from exc


@app.get("/api/repair/jobs/{job_id}/preview")
def read_preview(job_id: str) -> Response:
    try:
        return Response(service.preview_bytes(job_id), media_type="image/png")
    except ServiceError as exc:
        raise _service_error(exc) from exc


@app.get("/api/repair/previews/{job_id}", include_in_schema=False)
def read_preview_alias(job_id: str) -> Response:
    return read_preview(job_id)


@app.post("/api/repair/jobs/{job_id}/accept", response_model=RepairJobResponse)
def accept_job(job_id: str) -> RepairJobResponse:
    try:
        return service.accept(job_id)
    except ServiceError as exc:
        raise _service_error(exc) from exc


@app.post("/api/repair/jobs/{job_id}/reject", response_model=RepairJobResponse)
def reject_job(job_id: str) -> RepairJobResponse:
    try:
        return service.reject(job_id)
    except ServiceError as exc:
        raise _service_error(exc) from exc


@app.post("/api/repair/jobs/{job_id}/cancel", response_model=RepairJobResponse)
def cancel_job(job_id: str) -> RepairJobResponse:
    try:
        return service.cancel(job_id)
    except ServiceError as exc:
        raise _service_error(exc) from exc


# Canonical aliases from the technical plan. The browser MVP uses the plural
# `/api/repair/jobs` routes above; aliases make the boundary easy to evolve.
@app.post(
    "/api/repair-jobs",
    response_model=RepairJobResponse,
    status_code=201,
    include_in_schema=False,
)
def create_job_alias(
    payload: RepairSubmissionPayload,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RepairJobResponse:
    return create_job(payload, idempotency_key)


@app.get("/api/repair-jobs/{job_id}", response_model=RepairJobResponse, include_in_schema=False)
def read_job_alias(job_id: str) -> RepairJobResponse:
    return read_job(job_id)


@app.post(
    "/api/repair-jobs/{job_id}/review",
    response_model=RepairJobResponse,
    include_in_schema=False,
)
def review_job_alias(job_id: str, decision: ReviewDecision) -> RepairJobResponse:
    try:
        return service.accept(job_id) if decision.decision == "accept" else service.reject(job_id)
    except ServiceError as exc:
        raise _service_error(exc) from exc
