# Image-editing-tool

## Goal

Provide a safe local workflow for repairing a selected region of a comic image and producing a reviewable output.

## Implemented

- Backend foundation for rectangle geometry and exact target-ratio validation
- Optional context expansion, disabled by default
- Target-only preview compositing with outside-pixel preservation
- Replaceable image-edit adapter boundary
- FastAPI health and geometry validation endpoints

## Deploy

Install the project and development extras, then run:

    python -m pip install -e '.[dev]'
    uvicorn backend.app.main:app --reload

## References

- OpenAI Codex image-generation interfaces, used as an adapter boundary only
- Pillow for deterministic image operations
- FastAPI and Pydantic for the local service foundation

The native Codex image-edit path and production persistence are not included in this foundation release.
