"""Run a short Pose2Sim pose-estimation acceptance test on a copied sample."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Iterable

import tomlkit

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.media.importer import ANALYSIS_VIDEO_SUFFIXES


def prepare_sample(sample_root: Path, destination_root: Path, *, frames: int) -> Path:
    """Copy a Pose2Sim sample and constrain the copy to a short headless run."""

    source = Path(sample_root).resolve()
    if frames <= 0:
        raise ValueError("frames must be greater than zero")
    config_path = source / "Config.toml"
    if not config_path.is_file():
        raise ValueError(f"Pose2Sim sample is missing Config.toml: {source}")
    videos = source / "videos"
    if not videos.is_dir() or not any(
        path.is_file() and path.suffix.casefold() in ANALYSIS_VIDEO_SUFFIXES
        for path in videos.iterdir()
    ):
        raise ValueError(f"Pose2Sim sample has no supported videos: {videos}")

    destination_parent = Path(destination_root).resolve()
    destination_parent.mkdir(parents=True, exist_ok=True)
    destination = destination_parent / source.name
    if destination.exists():
        raise ValueError(f"sample destination already exists: {destination}")
    shutil.copytree(source, destination)

    copied_config = destination / "Config.toml"
    document = tomlkit.parse(copied_config.read_text(encoding="utf-8"))
    project = document.get("project")
    pose = document.get("pose")
    if project is None or not hasattr(project, "__setitem__"):
        raise ValueError("Pose2Sim Config.toml is missing the [project] table")
    if pose is None or not hasattr(pose, "__setitem__"):
        raise ValueError("Pose2Sim Config.toml is missing the [pose] table")
    project["project_dir"] = str(destination)
    project["frame_range"] = [0, int(frames)]
    pose["display_detection"] = False
    pose["overwrite_pose"] = True
    pose["save_video"] = "none"
    pose["parallel_workers_pose"] = 1
    copied_config.write_text(tomlkit.dumps(document), encoding="utf-8", newline="\n")
    return destination


def build_runner_command(
    runner: Path,
    arguments: Iterable[str],
    *,
    force_python: bool = False,
) -> tuple[str, ...]:
    executable = str(Path(runner))
    suffix = Path(runner).suffix.casefold()
    name = Path(runner).stem.casefold()
    is_python = force_python or name.startswith("python") and suffix in {"", ".exe"}
    prefix = (executable, "-m", "app.main") if is_python else (executable,)
    return (*prefix, *(str(argument) for argument in arguments))


def _run_logged(command: tuple[str, ...], *, cwd: Path, log) -> int:
    log.write(f"command={subprocess.list2cmdline(command)}\n")
    log.flush()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    for line in process.stdout:
        sys.stdout.write(line)
        log.write(line)
        log.flush()
    return process.wait()


def run_acceptance(
    sample_root: Path,
    runner: Path,
    *,
    frames: int,
    runner_kind: str,
    log_path: Path,
) -> int:
    log_path = Path(log_path).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mas-pose2sim-") as temporary:
        prepared = prepare_sample(sample_root, Path(temporary), frames=frames)
        force_python = runner_kind == "python"
        runtime_command = build_runner_command(
            runner,
            ("--pose2sim-runtime-check",),
            force_python=force_python,
        )
        stage_command = build_runner_command(
            runner,
            (
                "--pose2sim-stage",
                "poseEstimation",
                "--pose2sim-config",
                str(prepared / "Config.toml"),
                "--pose2sim-project-root",
                str(prepared),
            ),
            force_python=force_python,
        )
        cwd = REPOSITORY_ROOT if force_python else prepared
        with log_path.open("w", encoding="utf-8", newline="\n") as log:
            log.write(f"sample_source={Path(sample_root).resolve()}\n")
            log.write(f"prepared_copy={prepared}\n")
            if _run_logged(runtime_command, cwd=cwd, log=log) != 0:
                log.write("result=runtime-check-failed\n")
                return 1
            if _run_logged(stage_command, cwd=cwd, log=log) != 0:
                log.write("result=pose-estimation-failed\n")
                return 1
            pose_files = tuple(
                path
                for path in prepared.rglob("*.json")
                if path.parent.name.casefold().endswith("_json")
            )
            log.write(f"generated_pose_json={len(pose_files)}\n")
            if not pose_files:
                log.write("result=no-pose-output\n")
                return 1
            log.write("result=passed\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", required=True, type=Path)
    parser.add_argument("--runner", required=True, type=Path)
    parser.add_argument("--runner-kind", choices=("python", "exe"), required=True)
    parser.add_argument("--frames", type=int, default=3)
    parser.add_argument("--log", type=Path)
    arguments = parser.parse_args(argv)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = arguments.log or Path("outputs") / "acceptance" / f"pose2sim-sample-{stamp}.log"
    result = run_acceptance(
        arguments.sample,
        arguments.runner,
        frames=arguments.frames,
        runner_kind=arguments.runner_kind,
        log_path=log_path,
    )
    print(f"Pose2Sim sample acceptance {'passed' if result == 0 else 'failed'}; log={Path(log_path).resolve()}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
