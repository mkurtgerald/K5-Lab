from __future__ import annotations

from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.check_package_metadata import load_repository, parse_exact_pins, validate_repository

MAX_WHEEL_BYTES = 2 * 1024 * 1024
PROTECTED_SUFFIXES = {".pt", ".pth", ".onnx", ".safetensors", ".pkl", ".pickle", ".joblib", ".mp4", ".avi", ".mov", ".jpg", ".jpeg", ".png", ".wav", ".npy", ".npz", ".parquet", ".db"}


def run(args: list[str], *, cwd: Path, env=None, check=True):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, check=False, timeout=120)
    if check and result.returncode:
        tail = "\n".join((result.stdout + "\n" + result.stderr).splitlines()[-25:])
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}\n{tail}")
    return result


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_source(destination: Path) -> None:
    shutil.copytree(ROOT, destination, ignore=shutil.ignore_patterns(".git", "build", "dist", "__pycache__", ".pytest_cache", "*.egg-info"))


def build(source: Path, wheelhouse: Path, env: dict[str, str]) -> tuple[Path, int]:
    started = time.perf_counter()
    run([sys.executable, "-m", "pip", "wheel", "--disable-pip-version-check", "--no-deps", "--wheel-dir", str(wheelhouse), str(source)], cwd=source, env=env)
    elapsed = round((time.perf_counter() - started) * 1000)
    wheels = sorted(wheelhouse.glob("mosaic_lab-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected one project wheel, found {len(wheels)}")
    return wheels[0], elapsed


def inspect_wheel(wheel: Path, core_pins: dict[str, str]) -> dict[str, int]:
    size = wheel.stat().st_size
    if not 0 < size <= MAX_WHEEL_BYTES:
        raise RuntimeError(f"wheel outside bounded source-only size envelope: {size}")
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError(f"unsafe wheel path: {name}")
            if name.lower().startswith(("tests/", "tools/", "provenance/", ".github/", "docs/")):
                raise RuntimeError(f"non-runtime repository content leaked into wheel: {name}")
            if Path(name.lower()).suffix in PROTECTED_SUFFIXES:
                raise RuntimeError(f"protected artifact leaked into wheel: {name}")
        sources = [name for name in names if name.startswith("mosaic_lab/") and name.endswith(".py")]
        metadata_paths = [name for name in names if name.endswith(".dist-info/METADATA")]
        if not sources or len(metadata_paths) != 1:
            raise RuntimeError("wheel package/metadata structure is incomplete")
        if not any(name.endswith(".dist-info/licenses/LICENSE") for name in names):
            raise RuntimeError("wheel does not carry the project license")
        metadata = Parser().parsestr(archive.read(metadata_paths[0]).decode("utf-8"))
        if metadata.get("Name") != "mosaic-lab" or metadata.get("Version") != "0.1.0":
            raise RuntimeError("wheel identity/version mismatch")
        wheel_pins = parse_exact_pins(metadata.get_all("Requires-Dist") or [], source="wheel METADATA")
        if wheel_pins != core_pins:
            raise RuntimeError("wheel dependencies do not match the exact core runtime boundary")
    return {"wheel_bytes": size, "member_count": len(names), "python_source_members": len(sources)}


def main() -> int:
    errors = validate_repository(ROOT)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    _, _, build_tools, core_pins = load_repository(ROOT)
    build_tool = build_tools["tools"][0]
    epoch = str(build_tools["source_date_epoch"])
    env = os.environ.copy()
    env.update({"SOURCE_DATE_EPOCH": epoch, "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1", "PIP_ONLY_BINARY": ":all:", "PIP_NO_CACHE_DIR": "1"})

    with tempfile.TemporaryDirectory(prefix="k5-package-") as text:
        temp = Path(text)
        reviewed_tool = temp / "reviewed-build-tool"; reviewed_tool.mkdir()
        run([sys.executable, "-m", "pip", "download", "--disable-pip-version-check", "--no-deps", "--only-binary=:all:", f"setuptools=={build_tool['version']}", "--dest", str(reviewed_tool)], cwd=temp, env=env)
        artifacts = sorted(reviewed_tool.glob("*.whl"))
        if len(artifacts) != 1 or artifacts[0].name != build_tool["artifact_filename"] or digest(artifacts[0]) != build_tool["artifact_sha256"]:
            raise RuntimeError("reviewed build-tool artifact identity/hash mismatch")

        source_a, source_b = temp / "source-a", temp / "source-b"
        wheels_a, wheels_b = temp / "wheels-a", temp / "wheels-b"
        wheels_a.mkdir(); wheels_b.mkdir()
        copy_source(source_a); copy_source(source_b)
        wheel_a, build_a_ms = build(source_a, wheels_a, env)
        wheel_b, build_b_ms = build(source_b, wheels_b, env)
        sha_a, sha_b = digest(wheel_a), digest(wheel_b)
        if wheel_a.name != wheel_b.name or sha_a != sha_b or wheel_a.read_bytes() != wheel_b.read_bytes():
            raise RuntimeError("repeated wheel builds are not byte reproducible")
        inspection = inspect_wheel(wheel_a, core_pins)

        target = temp / "installed"
        started = time.perf_counter()
        run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", "--target", str(target), str(wheel_a)], cwd=temp, env=env)
        install_ms = round((time.perf_counter() - started) * 1000)
        code = "import sys;sys.path.insert(0,sys.argv[1]);import mosaic_lab;from mosaic_lab.adapter_contract import contract_document;assert mosaic_lab.__version__=='0.1.0';assert contract_document()['response']['authorized'] is False"
        run([sys.executable, "-I", "-c", code, str(target)], cwd=temp, env=env)

        corrupt_dir = temp / "corrupt"; corrupt_dir.mkdir()
        corrupt = corrupt_dir / wheel_a.name
        payload = wheel_a.read_bytes(); corrupt.write_bytes(payload[: max(1, len(payload) // 2)])
        rejected = run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", "--target", str(temp / "bad-target"), str(corrupt)], cwd=temp, env=env, check=False)
        if rejected.returncode == 0:
            raise RuntimeError("corrupted wheel was unexpectedly installable")

        shutil.rmtree(target)
        removed = run([sys.executable, "-I", "-c", "import sys;sys.path.insert(0,sys.argv[1]);import mosaic_lab", str(target)], cwd=temp, env=env, check=False)
        if removed.returncode == 0:
            raise RuntimeError("package remained importable after lifecycle cleanup")

        print(json.dumps({"schema":"k5-lab.package-lifecycle/v1","wheel":wheel_a.name,"wheel_sha256":sha_a,**inspection,"build_a_ms":build_a_ms,"build_b_ms":build_b_ms,"install_ms":install_ms,"build_tool_hash_verified":True,"byte_reproducible":True,"corrupt_artifact_rejected":True,"post_cleanup_import_rejected":True,"commercial_distribution":False,"production_qualified":False}, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
