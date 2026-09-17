from __future__ import annotations

import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.check_release_provenance import HEX64_RE, base_version, canonical_name, parse_pins

ROOT = Path(__file__).resolve().parents[1]


def _component(
    *,
    name: str,
    declared_version: str,
    review_row: dict[str, object] | None,
    runtime_version: str | None = None,
) -> dict[str, object]:
    row = review_row or {}
    review_scope = str(row.get("review_scope", "")).lower()
    if name == "torch" and runtime_version:
        native_status = "confirmed-native"
    elif "native" in review_scope:
        native_status = "review-required"
    else:
        native_status = "unresolved"
    result: dict[str, object] = {
        "name": name,
        "declared_version": declared_version,
        "runtime_version": runtime_version or declared_version,
        "native_status": native_status,
        "distribution_approved": row.get("distribution_approved") is True,
    }
    digest = row.get("artifact_sha256")
    if isinstance(digest, str) and HEX64_RE.fullmatch(digest):
        result["artifact_sha256"] = digest
    license_expr = row.get("project_license")
    if isinstance(license_expr, str) and license_expr.strip():
        result["license_expression"] = license_expr.strip()
    return result


def build_sbom(
    *,
    manifest: dict[str, object],
    core_pins: dict[str, str],
    runtime_pins: dict[str, str],
    neural_pins: dict[str, str],
    components: dict[str, object],
    s3_review: dict[str, object],
) -> dict[str, object]:
    package = manifest.get("package", {})
    if not isinstance(package, dict):
        raise ValueError("release manifest package must be an object")
    rows = components.get("components", [])
    if not isinstance(rows, list):
        raise ValueError("component ledger components must be a list")

    by_name: dict[str, dict[str, object]] = {}
    non_shipping: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            continue
        if row.get("status") == "non-shipping-candidate":
            non_shipping.append(
                {
                    "name": str(row["name"]),
                    "selected": False,
                    "distribution_approved": row.get("distribution_approved") is True,
                }
            )
            continue
        by_name[canonical_name(str(row["name"]))] = row

    torch_runtime: str | None = None
    torch_pin = neural_pins.get("torch")
    torch_review = s3_review.get("torch")
    if torch_pin is not None and isinstance(torch_review, dict):
        evaluated = torch_review.get("evaluated_runtime")
        if isinstance(evaluated, str) and base_version(evaluated) == base_version(torch_pin):
            torch_runtime = evaluated

    def rows_for(pins: dict[str, str], *, torch_scope: bool = False) -> list[dict[str, object]]:
        return [
            _component(
                name=name,
                declared_version=version,
                review_row=by_name.get(name),
                runtime_version=torch_runtime if torch_scope and name == "torch" else None,
            )
            for name, version in sorted(pins.items())
        ]

    return {
        "schema": "k5-lab.release-sbom/v1",
        "package": {"name": package.get("name"), "version": package.get("version")},
        "release_flags": {
            "commercial_distribution": manifest.get("commercial_distribution") is True,
            "production_qualified": manifest.get("production_qualified") is True,
            "owner_release_approved": manifest.get("owner_release_approved") is True,
        },
        "scopes": {
            "core": {
                "shipping_candidate": True,
                "optional": False,
                "components": rows_for(core_pins),
            },
            "learned_policy_python": {
                "shipping_candidate": False,
                "optional": True,
                "components": rows_for(runtime_pins),
            },
            "learned_policy_torch": {
                "shipping_candidate": False,
                "optional": True,
                "components": rows_for(neural_pins, torch_scope=True),
            },
        },
        "non_shipping_candidates": sorted(non_shipping, key=lambda row: str(row["name"])),
    }


def canonical_text(document: dict[str, object]) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"


def validate_sbom_text(expected: dict[str, object], actual_text: str) -> list[str]:
    try:
        actual = json.loads(actual_text)
    except json.JSONDecodeError as exc:
        return [f"SBOM is not valid JSON: {exc}"]
    errors: list[str] = []
    if actual != expected:
        errors.append("SBOM content is stale or does not match authoritative release inputs")
    if actual_text != canonical_text(actual):
        errors.append("SBOM must use deterministic canonical JSON formatting")
    return errors


def load_repository_documents(root: Path = ROOT):
    manifest = json.loads((root / "provenance/release-manifest.json").read_text(encoding="utf-8"))
    components = json.loads((root / "provenance/components.json").read_text(encoding="utf-8"))
    s3_review = json.loads((root / "provenance/s3-rl-review.json").read_text(encoding="utf-8"))
    core_pins = parse_pins((root / "requirements-core.txt").read_text(encoding="utf-8"), source="requirements-core.txt")
    runtime_pins = parse_pins((root / "requirements-s3-runtime.txt").read_text(encoding="utf-8"), source="requirements-s3-runtime.txt")
    neural_pins = parse_pins((root / "requirements-neural.txt").read_text(encoding="utf-8"), source="requirements-neural.txt")
    return manifest, core_pins, runtime_pins, neural_pins, components, s3_review


def validate_repository(root: Path = ROOT) -> list[str]:
    manifest, core, runtime, neural, components, s3_review = load_repository_documents(root)
    expected = build_sbom(
        manifest=manifest,
        core_pins=core,
        runtime_pins=runtime,
        neural_pins=neural,
        components=components,
        s3_review=s3_review,
    )
    path = root / "provenance/sbom.json"
    if not path.is_file():
        return ["provenance/sbom.json is missing"]
    return validate_sbom_text(expected, path.read_text(encoding="utf-8"))


def main() -> int:
    errors = validate_repository()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    manifest, core, runtime, neural, components, s3_review = load_repository_documents()
    document = build_sbom(
        manifest=manifest,
        core_pins=core,
        runtime_pins=runtime,
        neural_pins=neural,
        components=components,
        s3_review=s3_review,
    )
    unresolved_native = sum(
        component["native_status"] == "unresolved"
        for scope in document["scopes"].values()
        for component in scope["components"]
    )
    print(
        json.dumps(
            {
                "component_count": len(core) + len(runtime) + len(neural),
                "unresolved_native_reviews": unresolved_native,
                "non_shipping_candidates": len(document["non_shipping_candidates"]),
                "commercial_distribution": False,
                "production_qualified": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
