from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
ALIASES = {"or-tools": "ortools"}


def canonical_name(name: str) -> str:
    normalized = re.sub(r"[-_.]+", "-", name.strip().lower())
    return ALIASES.get(normalized, normalized)


def base_version(version: str) -> str:
    return version.split("+", 1)[0]


def parse_pins(text: str, *, source: str) -> dict[str, str]:
    pins: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN_RE.fullmatch(line)
        if not match:
            raise ValueError(f"{source}:{lineno}: requirement must be an exact == pin: {line!r}")
        name, version = match.groups()
        key = canonical_name(name)
        if key in pins:
            raise ValueError(f"{source}:{lineno}: duplicate requirement {key}")
        pins[key] = version
    return pins


def validate_documents(
    *,
    manifest: dict[str, object],
    pyproject: dict[str, object],
    core_pins: dict[str, str],
    neural_pins: dict[str, str],
    runtime_pins: dict[str, str],
    components: dict[str, object],
    s3_review: dict[str, object],
) -> list[str]:
    errors: list[str] = []

    for flag in ("commercial_distribution", "production_qualified", "owner_release_approved"):
        if manifest.get(flag) is not False:
            errors.append(f"release manifest must keep {flag}=false")

    project = pyproject.get("project", {})
    package = manifest.get("package", {})
    if not isinstance(project, dict) or not isinstance(package, dict):
        errors.append("invalid project/package manifest structure")
    else:
        if package.get("name") != project.get("name"):
            errors.append("release manifest package name does not match pyproject")
        if package.get("version") != project.get("version"):
            errors.append("release manifest package version does not match pyproject")

    authoritative = manifest.get("authoritative_inputs")
    expected_inputs = {
        "core": "requirements-core.txt",
        "learned_runtime_python": "requirements-s3-runtime.txt",
        "learned_runtime_torch": "requirements-neural.txt",
        "component_review": "provenance/components.json",
        "learned_runtime_evidence": "provenance/s3-rl-review.json",
    }
    if authoritative != expected_inputs:
        errors.append("release manifest authoritative_inputs changed or is incomplete")

    if components.get("release_approved") is not False:
        errors.append("aggregate component ledger must keep release_approved=false")

    component_rows = components.get("components")
    if not isinstance(component_rows, list):
        errors.append("component ledger must contain a components list")
        component_rows = []

    by_name: dict[str, dict[str, object]] = {}
    for row in component_rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            errors.append("component ledger contains malformed row")
            continue
        key = canonical_name(str(row["name"]))
        if key in by_name:
            errors.append(f"duplicate aggregate component identity: {key}")
            continue
        by_name[key] = row
        if row.get("distribution_approved") is not False:
            errors.append(f"{key}: distribution_approved must remain false")
        digest = row.get("artifact_sha256")
        if digest is not None and (not isinstance(digest, str) or not HEX64_RE.fullmatch(digest)):
            errors.append(f"{key}: artifact_sha256 must be null or lowercase SHA-256")

    combined_pins: dict[str, tuple[str, str]] = {}
    for scope, pins in (
        ("core", core_pins),
        ("learned-runtime-python", runtime_pins),
        ("learned-runtime-torch", neural_pins),
    ):
        for name, version in pins.items():
            if name in combined_pins and base_version(combined_pins[name][1]) != base_version(version):
                errors.append(
                    f"conflicting exact pins for {name}: "
                    f"{combined_pins[name][0]}={combined_pins[name][1]} vs {scope}={version}"
                )
            combined_pins[name] = (scope, version)

    for name, row in by_name.items():
        if name not in combined_pins:
            continue
        version = row.get("version")
        if not isinstance(version, str) or not version:
            errors.append(f"{name}: aggregate component version missing for pinned dependency")
            continue
        expected = combined_pins[name][1]
        if base_version(version) != base_version(expected):
            errors.append(f"{name}: aggregate version {version} does not match exact pin {expected}")

    torch_pin = neural_pins.get("torch")
    if torch_pin is None:
        errors.append("requirements-neural.txt must contain exact torch pin")
    torch_review = s3_review.get("torch")
    if not isinstance(torch_review, dict):
        errors.append("S3 runtime ledger is missing torch review")
    elif torch_pin is not None:
        reviewed_version = torch_review.get("version")
        evaluated_runtime = torch_review.get("evaluated_runtime")
        expected_runtime = f"{torch_pin}+cpu"
        if reviewed_version != torch_pin:
            errors.append(f"S3 torch source version {reviewed_version!r} != neural pin {torch_pin!r}")
        if evaluated_runtime != expected_runtime:
            errors.append(
                f"S3 evaluated torch runtime {evaluated_runtime!r} != expected {expected_runtime!r}"
            )
        torch_row = by_name.get("torch")
        if torch_row is None:
            errors.append("aggregate component ledger is missing torch")
        else:
            if torch_row.get("version") != expected_runtime:
                errors.append(
                    f"aggregate torch runtime {torch_row.get('version')!r} != evaluated {expected_runtime!r}"
                )
            wheel_sha = torch_review.get("linux_cp313_cpu_wheel_sha256")
            if torch_row.get("artifact_sha256") != wheel_sha:
                errors.append("aggregate torch artifact digest does not match reviewed CPU wheel")

    sb3_pin = runtime_pins.get("stable-baselines3")
    sb3_review = s3_review.get("stable_baselines3")
    if sb3_pin is None:
        errors.append("requirements-s3-runtime.txt must contain stable-baselines3")
    elif not isinstance(sb3_review, dict) or sb3_review.get("version") != sb3_pin:
        errors.append("Stable-Baselines3 runtime pin does not match S3 review ledger")
    else:
        sb3_row = by_name.get("stable-baselines3")
        if sb3_row is None or sb3_row.get("version") != sb3_pin:
            errors.append("aggregate Stable-Baselines3 version does not match reviewed runtime")
        elif sb3_row.get("artifact_sha256") != sb3_review.get("wheel_sha256"):
            errors.append("aggregate Stable-Baselines3 artifact digest does not match reviewed wheel")

    release_review = s3_review.get("release_review")
    if not isinstance(release_review, dict):
        errors.append("S3 release_review block missing")
    else:
        for flag in (
            "native_bundle_review_complete",
            "transitive_sbom_complete",
            "notices_complete",
            "vulnerability_review_complete",
            "target_platform_review_complete",
            "commercial_distribution_approved",
        ):
            if release_review.get(flag) is not False:
                errors.append(f"S3 release review must keep {flag}=false until later acceptance")

    return errors


def validate_repository(root: Path = ROOT) -> list[str]:
    manifest = json.loads((root / "provenance/release-manifest.json").read_text(encoding="utf-8"))
    components = json.loads((root / "provenance/components.json").read_text(encoding="utf-8"))
    s3_review = json.loads((root / "provenance/s3-rl-review.json").read_text(encoding="utf-8"))
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    core_pins = parse_pins(
        (root / "requirements-core.txt").read_text(encoding="utf-8"),
        source="requirements-core.txt",
    )
    neural_pins = parse_pins(
        (root / "requirements-neural.txt").read_text(encoding="utf-8"),
        source="requirements-neural.txt",
    )
    runtime_pins = parse_pins(
        (root / "requirements-s3-runtime.txt").read_text(encoding="utf-8"),
        source="requirements-s3-runtime.txt",
    )
    return validate_documents(
        manifest=manifest,
        pyproject=pyproject,
        core_pins=core_pins,
        neural_pins=neural_pins,
        runtime_pins=runtime_pins,
        components=components,
        s3_review=s3_review,
    )


def main() -> int:
    errors = validate_repository()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    manifest = json.loads((ROOT / "provenance/release-manifest.json").read_text(encoding="utf-8"))
    core = parse_pins((ROOT / "requirements-core.txt").read_text(encoding="utf-8"), source="core")
    runtime = parse_pins(
        (ROOT / "requirements-s3-runtime.txt").read_text(encoding="utf-8"),
        source="runtime",
    )
    neural = parse_pins(
        (ROOT / "requirements-neural.txt").read_text(encoding="utf-8"),
        source="neural",
    )
    print(
        json.dumps(
            {
                "schema_version": manifest["schema_version"],
                "core_pin_count": len(core),
                "isolated_python_pin_count": len(runtime),
                "torch_pin": neural["torch"],
                "commercial_distribution": False,
                "production_qualified": False,
                "owner_release_approved": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
