"""Run one explicit Codex CLI image-edit probe.

This is a diagnostic entry point. It does not create a formal page version or
claim that the HTTP MVP is connected to Codex.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from frame_repair.adapters import CodexCliImageEditAdapter  # noqa: E402
from frame_repair.errors import BackendError  # noqa: E402
from frame_repair.raster import Raster  # noqa: E402


def read_raster(path: Path) -> Raster:
    from PIL import Image

    with Image.open(path) as image:
        image.load()
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        pixels = list(image.getdata())
        rows = [
            [tuple(pixel) for pixel in pixels[y * image.width : (y + 1) * image.width]
            ]
            for y in range(image.height)
        ]
        return Raster.from_rows(rows)


def write_raster(raster: Raster, path: Path) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "RGBA" if raster.channels == 4 else "RGB"
    with Image.new(mode, (raster.width, raster.height)) as image:
        image.putdata(list(raster.pixels))
        image.save(path, format="PNG")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--instruction", required=True)
    parser.add_argument("--job-id", default="cli-probe")
    parser.add_argument("--codex", default="codex", help="Codex executable or absolute path")
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args()
    try:
        result = CodexCliImageEditAdapter(
            executable=args.codex,
            work_root=args.work_root,
            timeout_seconds=args.timeout,
            keep_workdirs=True,
        ).edit(read_raster(args.input), args.instruction, job_id=args.job_id)
        write_raster(result.raster, args.output)
    except (BackendError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "code": getattr(exc, "code", "ERROR"), "error": str(exc)}))
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "origin": result.origin,
                "provider_operation_id": result.provider_operation_id,
                "output": str(args.output.resolve()),
                "width": result.raster.width,
                "height": result.raster.height,
                "sha256": result.raster.sha256,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
