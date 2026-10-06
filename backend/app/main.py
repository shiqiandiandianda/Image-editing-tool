from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .geometry import GeometryError, build_crop_plan
from .models import AspectRatio, Rect

app = FastAPI(title="Image Editing Tool", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
            target,
            ratio,
            image_width,
            image_height,
            expand_context,
            expansion_pixels,
        )
    except GeometryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"target": plan.target.model_dump(), "context": plan.context.model_dump()}
