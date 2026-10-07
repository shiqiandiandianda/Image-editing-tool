from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

try:
    from PIL import Image
except ImportError:  # pragma: no cover - exercised only in dependency-free checkouts
    Image = None  # type: ignore[assignment,misc]

from frame_repair.adapters import CodexCliImageEditAdapter
from frame_repair.raster import Raster


@unittest.skipIf(Image is None, "Pillow is required by the CLI image adapter")
class CodexCliAdapterTests(unittest.TestCase):
    """The CLI boundary is exercised with a subprocess.run-compatible fake.

    These tests deliberately never execute a real Codex binary.  The fake writes
    declared PNGs in the task directory and returns JSONL exactly as the adapter
    receives it from ``codex exec --json``.
    """

    def raster(self) -> Raster:
        return Raster.from_rows(
            [
                [(255, 0, 0), (0, 255, 0)],
                [(0, 0, 255), (255, 255, 0)],
            ]
        )

    def write_png(self, path: Path, raster: Raster | None = None) -> None:
        image = raster or self.raster()
        mode = "RGBA" if image.channels == 4 else "RGB"
        with Image.new(mode, (image.width, image.height)) as output:
            output.putdata(list(image.pixels))
            output.save(path, format="PNG")

    def command_value(self, command: list[str], flag: str) -> Path:
        index = command.index(flag)
        return Path(command[index + 1])

    def adapter(self, root: Path, runner: Any, timeout: float = 7.5) -> CodexCliImageEditAdapter:
        return CodexCliImageEditAdapter(
            executable="codex-test-double",
            work_root=root,
            timeout_seconds=timeout,
            runner=runner,
        )

    class Runner:
        def __init__(
            self, callback=None, *, returncode: int = 0, stdout: str = "", stderr: str = ""
        ):
            self.callback = callback
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr
            self.command: list[str] | None = None
            self.kwargs: dict[str, Any] = {}

        def __call__(self, command, **kwargs):
            self.command = list(command)
            self.kwargs = kwargs
            if self.callback is not None:
                self.callback(self.command, kwargs, self)
            return subprocess.CompletedProcess(
                self.command,
                self.returncode,
                stdout=self.stdout,
                stderr=self.stderr,
            )

    def test_success_decodes_official_image_generation_result_event(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def produce(command, kwargs, runner):
                task = Path(kwargs["cwd"])
                output = task / "result.png"
                self.write_png(output)
                encoded = base64.b64encode(output.read_bytes()).decode("ascii")
                runner.stdout = json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "image_generation_call",
                            "status": "generating",
                            "result": encoded,
                            "call_id": "op-42",
                        },
                    }
                )

            runner = self.Runner(produce)
            result = self.adapter(root, runner).edit(
                self.raster(), "repair the selected frame", job_id="job-42"
            )

            self.assertEqual(result.origin, "codex_cli")
            self.assertEqual(result.provider_operation_id, "op-42")
            self.assertEqual(result.raster, self.raster())
            self.assertIsNotNone(runner.command)
            command = runner.command or []
            self.assertIn("exec", command)
            self.assertIn("--json", command)
            self.assertIn("--image", command)
            self.assertIn("--output-last-message", command)
            self.assertIn("--skip-git-repo-check", command)
            self.assertIn("-C", command)
            self.assertTrue(any("repair the selected frame" in value for value in command))
            self.assertLess(command.index(next(value for value in command if "repair the selected frame" in value)), command.index("--image"))
            self.assertEqual(runner.kwargs["timeout"], 7.5)
            self.assertEqual(runner.kwargs["encoding"], "utf-8")
            self.assertEqual(runner.kwargs["errors"], "replace")
            task_dir = Path(runner.kwargs["cwd"])
            self.assertEqual(task_dir.parent, root)
            self.assertTrue(task_dir.name.startswith("job-42-"))

    def test_nonzero_cli_exit_is_reported_without_accepting_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner = self.Runner(returncode=23, stderr="permission denied")
            adapter = self.adapter(Path(temporary), runner)

            with self.assertRaises(Exception) as raised:
                adapter.edit(self.raster(), "repair", job_id="failed")

            self.assertEqual(getattr(raised.exception, "code", None), "CODEX_CLI_FAILED")

    def test_missing_cli_executable_is_reported_as_not_found(self):
        with tempfile.TemporaryDirectory() as temporary:
            def missing(command, kwargs, runner):
                raise FileNotFoundError(command[0])

            runner = self.Runner(missing)
            with self.assertRaises(Exception) as raised:
                self.adapter(Path(temporary), runner).edit(
                    self.raster(), "repair", job_id="missing-cli"
                )

            self.assertEqual(getattr(raised.exception, "code", None), "CODEX_CLI_NOT_FOUND")

    def test_tls_failure_is_reported_as_unreachable(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner = self.Runner(returncode=1, stderr="TLS certificate verify failed")
            with self.assertRaises(Exception) as raised:
                self.adapter(Path(temporary), runner).edit(
                    self.raster(), "repair", job_id="unreachable"
                )

            self.assertEqual(getattr(raised.exception, "code", None), "CODEX_UNREACHABLE")

    def test_timeout_is_reported_as_a_stable_cli_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            def timeout(command, kwargs, runner):
                raise subprocess.TimeoutExpired(command, kwargs.get("timeout"))

            runner = self.Runner(timeout)
            with self.assertRaises(Exception) as raised:
                self.adapter(Path(temporary), runner, timeout=0.01).edit(
                    self.raster(), "repair", job_id="timed-out"
                )

            self.assertEqual(getattr(raised.exception, "code", None), "CODEX_CLI_TIMEOUT")

    def test_jsonl_without_declared_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner = self.Runner(stdout=json.dumps({"type": "message", "text": "done"}))
            with self.assertRaises(Exception) as raised:
                self.adapter(Path(temporary), runner).edit(
                    self.raster(), "repair", job_id="missing-artifact"
                )

            self.assertEqual(getattr(raised.exception, "code", None), "CODEX_ARTIFACT_MISSING")

    def test_unreferenced_png_is_not_guessed_as_the_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            def produce(command, kwargs, runner):
                self.write_png(Path(kwargs["cwd"]) / "unreferenced.png")
                runner.stdout = json.dumps({"type": "message", "text": "done"})

            runner = self.Runner(produce)
            with self.assertRaises(Exception) as raised:
                self.adapter(Path(temporary), runner).edit(
                    self.raster(), "repair", job_id="unreferenced"
                )

            self.assertEqual(getattr(raised.exception, "code", None), "CODEX_ARTIFACT_MISSING")

    def test_multiple_declared_artifacts_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            def produce(command, kwargs, runner):
                task = Path(kwargs["cwd"])
                self.write_png(task / "first.png")
                self.write_png(task / "second.png")
                runner.stdout = "\n".join(
                    json.dumps({"type": "artifact", "artifact_path": name})
                    for name in ("first.png", "second.png")
                )

            runner = self.Runner(produce)
            with self.assertRaises(Exception) as raised:
                self.adapter(Path(temporary), runner).edit(
                    self.raster(), "repair", job_id="ambiguous"
                )

            self.assertEqual(getattr(raised.exception, "code", None), "CODEX_ARTIFACT_AMBIGUOUS")

    def test_artifact_outside_task_workspace_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def produce(command, kwargs, runner):
                output = root / "outside.png"
                self.write_png(output)
                runner.stdout = json.dumps({"type": "artifact", "artifact_path": str(output)})

            runner = self.Runner(produce)
            with self.assertRaises(Exception) as raised:
                self.adapter(root, runner).edit(self.raster(), "repair", job_id="outside")

            self.assertEqual(getattr(raised.exception, "code", None), "CODEX_ARTIFACT_INVALID")

    def test_input_artifact_is_rejected_even_when_declared_in_jsonl(self):
        with tempfile.TemporaryDirectory() as temporary:
            def produce(command, kwargs, runner):
                input_path = self.command_value(command, "--image")
                runner.stdout = json.dumps(
                    {"type": "artifact", "artifact_path": str(input_path)}
                )

            runner = self.Runner(produce)
            with self.assertRaises(Exception) as raised:
                self.adapter(Path(temporary), runner).edit(
                    self.raster(), "repair", job_id="input-as-output"
                )

            self.assertEqual(getattr(raised.exception, "code", None), "CODEX_ARTIFACT_INVALID")


if __name__ == "__main__":
    unittest.main()
