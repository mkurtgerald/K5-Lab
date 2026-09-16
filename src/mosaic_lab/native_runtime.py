"""Bounded runtime/native inventory helpers for the S2 donor candidate."""
from __future__ import annotations

import gc
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
from typing import Iterable

EXPECTED_RUNTIME = {
    "river": "0.26.1",
    "narwhals": "2.26.0",
    "numpy": "2.3.5",
    "scipy": "1.17.0",
}
MAX_NATIVE_FILES_PER_DISTRIBUTION = 512
MAX_NATIVE_BYTES_PER_DISTRIBUTION = 2 * 1024 * 1024 * 1024
MAX_LDD_SECONDS = 4.0
MAX_NATIVE_RSS_GROWTH_KIB = 256 * 1024
_NATIVE_MARKERS = (".so", ".pyd", ".dll", ".dylib")


def _is_native_file(path: str | Path) -> bool:
    name = Path(path).name.lower()
    return any(marker in name for marker in _NATIVE_MARKERS)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_ldd(output: str) -> tuple[list[str], list[str]]:
    dependencies: set[str] = set()
    unresolved: set[str] = set()
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "=>" in line:
            soname, target = (part.strip() for part in line.split("=>", 1))
            if soname:
                dependencies.add(soname)
            if target.startswith("not found") and soname:
                unresolved.add(soname)
            continue
        token = line.split(maxsplit=1)[0]
        if ".so" in token:
            dependencies.add(token)
    return sorted(dependencies), sorted(unresolved)


def _parse_proc_status(text: str) -> int:
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            parts = line.split()
            if len(parts) != 3 or parts[2] != "kB":
                raise RuntimeError("unexpected VmRSS format")
            value = int(parts[1])
            if value < 0:
                raise RuntimeError("negative VmRSS")
            return value
    raise RuntimeError("VmRSS unavailable")


def current_rss_kib() -> int:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("RSS evidence is currently Linux-only")
    return _parse_proc_status(Path("/proc/self/status").read_text(encoding="utf-8"))


def _dynamic_dependencies(path: Path) -> tuple[list[str], list[str]]:
    if not sys.platform.startswith("linux") or ".so" not in path.name.lower():
        return [], []
    result = subprocess.run(
        ["ldd", str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=MAX_LDD_SECONDS,
    )
    combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
    dependencies, unresolved = _parse_ldd(combined)
    if result.returncode not in (0, 1):
        raise RuntimeError(f"ldd failed for {path.name}: return code {result.returncode}")
    if result.returncode == 1 and "not a dynamic executable" not in combined.lower():
        raise RuntimeError(f"ldd could not inspect {path.name}")
    return dependencies, unresolved


def _manifest_digest(native_files: Iterable[dict[str, object]]) -> str:
    canonical = json.dumps(list(native_files), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def inventory_distribution(name: str, expected_version: str) -> dict[str, object]:
    distribution = importlib.metadata.distribution(name)
    version = distribution.version
    if version != expected_version:
        raise RuntimeError(f"{name} version mismatch: {version} != {expected_version}")
    native_entries: list[dict[str, object]] = []
    dynamic_dependencies: set[str] = set()
    unresolved: set[str] = set()
    total_bytes = 0
    for entry in sorted(distribution.files or (), key=lambda value: str(value)):
        relative = str(entry).replace("\\", "/")
        if not _is_native_file(relative):
            continue
        if len(native_entries) >= MAX_NATIVE_FILES_PER_DISTRIBUTION:
            raise RuntimeError(f"{name} native-file budget exceeded")
        path = Path(distribution.locate_file(entry)).resolve()
        if not path.is_file():
            raise RuntimeError(f"{name} native file missing: {relative}")
        size = path.stat().st_size
        total_bytes += size
        if total_bytes > MAX_NATIVE_BYTES_PER_DISTRIBUTION:
            raise RuntimeError(f"{name} native-byte budget exceeded")
        dependencies, missing = _dynamic_dependencies(path)
        dynamic_dependencies.update(dependencies)
        unresolved.update(missing)
        native_entries.append({"path": relative, "size": size, "sha256": _sha256_file(path)})
    if name in {"river", "numpy", "scipy"} and not native_entries:
        raise RuntimeError(f"expected native files for {name}")
    if name == "narwhals" and native_entries:
        raise RuntimeError("unexpected native files in narwhals")
    if unresolved:
        raise RuntimeError(f"unresolved native dependencies for {name}: {sorted(unresolved)}")
    return {
        "name": name,
        "version": version,
        "native_file_count": len(native_entries),
        "native_bytes": total_bytes,
        "native_manifest_sha256": _manifest_digest(native_entries),
        "native_files": native_entries,
        "dynamic_dependency_sonames": sorted(dynamic_dependencies),
        "unresolved_dynamic_dependencies": [],
    }


def runtime_native_inventory() -> dict[str, object]:
    distributions = [inventory_distribution(name, version) for name, version in EXPECTED_RUNTIME.items()]
    return {
        "scope": "hosted_linux_runtime_inventory_only",
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "system": platform.system(),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "distributions": distributions,
        "commercial_distribution_approved": False,
    }


def measure_native_rss_growth(benchmark, *, seeds: tuple[int, ...] = (19, 31, 43, 59, 71), size: int = 600) -> dict[str, object]:
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("unique seeds required")
    benchmark(size=size, seed=7)
    gc.collect()
    baseline = current_rss_kib()
    samples: list[int] = []
    for seed in seeds:
        benchmark(size=size, seed=seed)
        gc.collect()
        samples.append(current_rss_kib())
    max_growth = max([baseline, *samples]) - baseline
    final_growth = samples[-1] - baseline
    if max_growth > MAX_NATIVE_RSS_GROWTH_KIB:
        raise RuntimeError("native RSS growth smoke exceeded bound")
    return {
        "scope": "hosted_linux_synthetic_native_rss_smoke_only",
        "warmup_seed": 7,
        "seeds": list(seeds),
        "samples_per_seed": size,
        "baseline_rss_kib": baseline,
        "observed_rss_kib": samples,
        "max_growth_kib": max_growth,
        "final_growth_kib": final_growth,
        "acceptance_bound_kib": MAX_NATIVE_RSS_GROWTH_KIB,
        "passed": True,
        "production_memory_qualified": False,
    }
