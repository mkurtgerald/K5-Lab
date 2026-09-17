from __future__ import annotations

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_NATIVE_STATUSES = {
    "unresolved",
    "review-required",
    "confirmed-native",
    "reviewed-no-native",
    "reviewed-native",
}
REVIEWED_NATIVE_STATUSES = {"reviewed-no-native", "reviewed-native"}


def _flag(document: dict[str, object], name: str) -> bool:
    return document.get(name) is True


def validate_documents(
    *,
    release_manifest: dict[str, object],
    sbom: dict[str, object],
) -> list[str]:
    errors: list[str] = []
    if sbom.get("schema") != "k5-lab.release-sbom/v1":
        errors.append("SBOM schema must be k5-lab.release-sbom/v1")

    flags = sbom.get("release_flags")
    if not isinstance(flags, dict):
        return errors + ["SBOM release_flags must be an object"]
    for name in ("commercial_distribution", "production_qualified", "owner_release_approved"):
        if (flags.get(name) is True) != _flag(release_manifest, name):
            errors.append(f"SBOM release flag {name} does not match release manifest")

    scopes = sbom.get("scopes")
    if not isinstance(scopes, dict):
        return errors + ["SBOM scopes must be an object"]
    core = scopes.get("core")
    if not isinstance(core, dict):
        return errors + ["SBOM core scope is missing"]
    if core.get("shipping_candidate") is not True or core.get("optional") is not False:
        errors.append("core scope must remain the non-optional shipping candidate")

    core_rows: list[dict[str, object]] = []
    for scope_name, scope in scopes.items():
        if not isinstance(scope, dict):
            errors.append(f"{scope_name}: scope must be an object")
            continue
        shipping_candidate = scope.get("shipping_candidate") is True
        optional = scope.get("optional") is True
        rows = scope.get("components")
        if not isinstance(rows, list):
            errors.append(f"{scope_name}: components must be a list")
            continue
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("name"), str):
                errors.append(f"{scope_name}: malformed component row")
                continue
            name = str(row["name"]).strip().lower()
            if not name:
                errors.append(f"{scope_name}: empty component name")
                continue
            if name in seen:
                errors.append(f"{scope_name}: duplicate component {name}")
                continue
            seen.add(name)
            status = row.get("native_status")
            if status not in ALLOWED_NATIVE_STATUSES:
                errors.append(f"{scope_name}/{name}: invalid native_status {status!r}")
                continue
            if status == "reviewed-native":
                digest = row.get("artifact_sha256")
                if not isinstance(digest, str) or HEX64_RE.fullmatch(digest) is None:
                    errors.append(f"{scope_name}/{name}: reviewed-native requires exact artifact_sha256")
            if row.get("distribution_approved") is True:
                if not shipping_candidate or optional:
                    errors.append(f"{scope_name}/{name}: optional/non-shipping component cannot be distribution-approved")
                if status not in REVIEWED_NATIVE_STATUSES:
                    errors.append(f"{scope_name}/{name}: distribution approval requires completed native review")
            if scope_name == "core":
                core_rows.append(row)

    commercial_distribution = _flag(release_manifest, "commercial_distribution")
    if commercial_distribution:
        if not _flag(release_manifest, "owner_release_approved"):
            errors.append("commercial distribution requires owner_release_approved=true")
        blockers = sorted(
            str(row.get("name"))
            for row in core_rows
            if row.get("native_status") not in REVIEWED_NATIVE_STATUSES
        )
        if blockers:
            errors.append("commercial distribution blocked by unresolved native review: " + ",".join(blockers))
        unapproved = sorted(
            str(row.get("name"))
            for row in core_rows
            if row.get("distribution_approved") is not True
        )
        if unapproved:
            errors.append("commercial distribution blocked by component approval state: " + ",".join(unapproved))

    return errors


def validate_repository(root: Path = ROOT) -> list[str]:
    manifest = json.loads((root / "provenance/release-manifest.json").read_text(encoding="utf-8"))
    sbom = json.loads((root / "provenance/sbom.json").read_text(encoding="utf-8"))
    return validate_documents(release_manifest=manifest, sbom=sbom)


def main() -> int:
    errors = validate_repository()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    sbom = json.loads((ROOT / "provenance/sbom.json").read_text(encoding="utf-8"))
    core_rows = sbom["scopes"]["core"]["components"]
    pending = sum(row["native_status"] not in REVIEWED_NATIVE_STATUSES for row in core_rows)
    print(json.dumps({
        "core_components": len(core_rows),
        "pending_core_native_reviews": pending,
        "commercial_distribution": False,
        "owner_release_approved": False,
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
