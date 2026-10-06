from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from .models import AspectRatio, Rect


class GeometryError(ValueError):
    """Raised when a repair rectangle cannot be safely applied."""


@dataclass(frozen=True)
class CropPlan:
    target: Rect
    context: Rect


def validate_target(rect: Rect, ratio: AspectRatio, image_width: int, image_height: int) -> None:
    if rect.right() > image_width or rect.bottom() > image_height:
        raise GeometryError("target rectangle exceeds the source image")
    if not rect.aspect_matches(ratio):
        raise GeometryError(f"target rectangle must match ratio {ratio.value}")


def build_crop_plan(
    target: Rect,
    ratio: AspectRatio,
    image_width: int,
    image_height: int,
    expand_context: bool = False,
    expansion_pixels: int = 0,
) -> CropPlan:
    validate_target(target, ratio, image_width, image_height)
    context = (
        target.expand(expansion_pixels, image_width, image_height)
        if expand_context
        else target
    )
    return CropPlan(target=target, context=context)


def crop_context(image: Image.Image, plan: CropPlan) -> Image.Image:
    box = (plan.context.x, plan.context.y, plan.context.right(), plan.context.bottom())
    return image.crop(box)


def composite_target(
    base: Image.Image,
    generated_context: Image.Image,
    plan: CropPlan,
) -> Image.Image:
    expected_size = (plan.context.width, plan.context.height)
    if generated_context.size != expected_size:
        raise GeometryError("generated image dimensions do not match context crop")
    target_box = (
        plan.target.x - plan.context.x,
        plan.target.y - plan.context.y,
        plan.target.right() - plan.context.x,
        plan.target.bottom() - plan.context.y,
    )
    patch = generated_context.crop(target_box)
    result = base.copy()
    result.paste(patch, (plan.target.x, plan.target.y))
    return result
