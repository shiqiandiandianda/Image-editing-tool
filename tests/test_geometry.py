import pytest
from PIL import Image

from backend.app.geometry import GeometryError, build_crop_plan, composite_target, crop_context
from backend.app.models import AspectRatio, Rect


def test_exact_ratio_is_required() -> None:
    target = Rect(x=0, y=0, width=160, height=90)
    plan = build_crop_plan(target, AspectRatio.LANDSCAPE, 320, 180)
    assert plan.context == target


def test_ratio_mismatch_is_rejected() -> None:
    with pytest.raises(GeometryError):
        build_crop_plan(Rect(x=0, y=0, width=100, height=90), AspectRatio.SQUARE, 200, 200)


def test_expansion_is_optional_and_clipped() -> None:
    target = Rect(x=10, y=10, width=160, height=90)
    plan = build_crop_plan(target, AspectRatio.LANDSCAPE, 200, 150, True, 20)
    assert plan.context == Rect(x=0, y=0, width=190, height=120)


def test_composite_preserves_outside_pixels() -> None:
    base = Image.new("RGB", (20, 20), "black")
    target = Rect(x=5, y=5, width=10, height=10)
    plan = build_crop_plan(target, AspectRatio.SQUARE, 20, 20)
    context = Image.new("RGB", (10, 10), "white")
    result = composite_target(base, context, plan)
    assert result.getpixel((0, 0)) == (0, 0, 0)
    assert result.getpixel((10, 10)) == (255, 255, 255)
    assert crop_context(result, plan).size == (10, 10)
