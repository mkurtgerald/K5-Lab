from __future__ import annotations

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)$")
FORBIDDEN_LICENSE_RE = re.compile(
    r"(?:\bAGPL(?:[- .]?\d(?:\.\d)?)?\b|\bGPL(?:[- .]?\d(?:\.\d)?)?\b|"
    r"NON[- ]?COMMERCIAL|RESEARCH[- ]?ONLY|\bUNKNOWN\b)",
    re.IGNORECASE,
)


def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def parse_pins(text: str) -> dict[str, str]:
    pins: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN_RE.fullmatch(line)
        if match is None:
            raise ValueError(f"requirements-core.txt:{lineno}: expected exact == pin: {line!r}")
        name, version = match.groups()
        key = canonical_name(name)
        if key in pins:
            raise ValueError(f"requirements-core.txt:{lineno}: duplicate pin {key}")
        pins[key] = version
    return pins


def validate_documents(
    *,
    release_manifest: dict[str, object],
    license_review: dict[str, object],
    core_pins: dict[str, str],
) -> list[str]:
    errors: list[str] = []
    if license_review.get("schema") != "k5-lab.license-review/v1":
        errors.append("license review schema must be k5-lab.license-review/v1")
    if license_review.get("scope") != "core-shipping-candidate":
        errors.append("license review must cover the core shipping candidate")
    if license_review.get("commercial_distribution") is not False:
        errors.append("license review must keep commercial_distribution=false")
    if license_review.get("owner_license_approval") is not False:
        errors.append("license review must keep owner_license_approval=false")
    if license_review.get("legal_review_approved") is not False:
        errors.append("license review must keep legal_review_approved=false")

    rows = license_review.get("components")
    if not isinstance(rows, list):
        return errors + ["license review components must be a list"]

    by_name: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            errors.append("license review contains malformed component row")
            continue
        name = canonical_name(str(row["name"]))
        if name in by_name:
            errors.append(f"duplicate license-review component {name}")
            continue
        by_name[name] = row

    missing = sorted(set(core_pins) - set(by_name))
    extra = sorted(set(by_name) - set(core_pins))
    if missing:
        errors.append(f"license review missing core components: {','.join(missing)}")
    if extra:
        errors.append(f"license review contains non-core components: {','.join(extra)}")

    for name, version in core_pins.items():
        row = by_name.get(name)
        if row is None:
            continue
        if row.get("version") != version:
            errors.append(f"{name}: license review version {row.get('version')!r} != exact pin {version!r}")
        expression = row.get("license_expression")
        if not isinstance(expression, str) or not expression.strip():
            errors.append(f"{name}: license expression is missing")
        elif FORBIDDEN_LICENSE_RE.search(expression):
            errors.append(f"{name}: forbidden/unreviewed shipping license expression {expression!r}")
        if row.get("project_terms_reviewed") is not True:
            errors.append(f"{name}: project terms must be reviewed before shipping-candidate acceptance")
        evidence = row.get("evidence")
        if not isinstance(evidence, dict):
            errors.append(f"{name}: license evidence is missing")
        else:
            if not isinstance(evidence.get("source"), str) or not str(evidence.get("source")).strip():
                errors.append(f"{name}: license evidence source is missing")
            url = evidence.get("url")
            if not isinstance(url, str) or not url.startswith("https://"):
                errors.append(f"{name}: license evidence URL must be https")
        notice_status = row.get("bundle_notice_status")
        if notice_status not in {"complete", "pending"}:
            errors.append(f"{name}: bundle_notice_status must be complete or pending")

    optional = license_review.get("optional_non_shipping_scopes")
    if not isinstance(optional, list) or not optional:
        errors.append("optional/non-shipping runtime scopes must remain explicitly excluded from core approval")
    else:
        for item in optional:
            if not isinstance(item, dict) or item.get("shipping_candidate") is not False:
                errors.append("optional/non-shipping scope must keep shipping_candidate=false")
            if isinstance(item, dict) and item.get("distribution_approved") is not False:
                errors.append("optional/non-shipping scope must keep distribution_approved=false")

    release_distribution = release_manifest.get("commercial_distribution") is True
    if release_distribution:
        if license_review.get("owner_license_approval") is not True:
            errors.append("commercial distribution requires owner license approval")
        if license_review.get("legal_review_approved") is not True:
            errors.append("commercial distribution requires separate legal review approval")
        pending = sorted(
            name for name, row in by_name.items() if row.get("bundle_notice_status") != "complete"
        )
        if pending:
            errors.append(f"commercial distribution blocked by pending bundle/notices review: {','.join(pending)}")
    elif license_review.get("commercial_distribution") is not False:
        errors.append("license review distribution state does not match fail-closed release state")

    return errors


def validate_repository(root: Path = ROOT) -> list[str]:
    manifest = json.loads((root / "provenance/release-manifest.json").read_text(encoding="utf-8"))
    license_review = json.loads((root / "provenance/license-review.json").read_text(encoding="utf-8"))
    pins = parse_pins((root / "requirements-core.txt").read_text(encoding="utf-8"))
    return validate_documents(release_manifest=manifest, license_review=license_review, core_pins=pins)


def main() -> int:
    errors = validate_repository()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    review = json.loads((ROOT / "provenance/license-review.json").read_text(encoding="utf-8"))
    pending = sum(row["bundle_notice_status"] != "complete" for row in review["components"])
    print(json.dumps({
        "core_components": len(review["components"]),
        "pending_bundle_notice_reviews": pending,
        "commercial_distribution": False,
        "owner_license_approval": False,
        "legal_review_approved": False,
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
