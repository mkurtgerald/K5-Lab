from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def parse_exact_pins(lines: list[str], *, source: str) -> dict[str, str]:
    pins: dict[str, str] = {}
    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN_RE.fullmatch(line)
        if match is None:
            raise ValueError(f"{source}:{lineno}: expected exact == pin: {line!r}")
        name, version = match.groups()
        key = canonical_name(name)
        if key in pins:
            raise ValueError(f"{source}:{lineno}: duplicate pin {key}")
        pins[key] = version
    return pins


def validate_documents(
    *,
    pyproject: dict[str, object],
    manifest: dict[str, object],
    build_tools: dict[str, object],
    core_pins: dict[str, str],
) -> list[str]:
    errors: list[str] = []
    project = pyproject.get("project")
    if not isinstance(project, dict):
        return ["pyproject project table is missing"]
    package = manifest.get("package")
    if not isinstance(package, dict):
        return ["release manifest package table is missing"]
    if project.get("name") != package.get("name"):
        errors.append("pyproject package name does not match release manifest")
    if project.get("version") != package.get("version"):
        errors.append("pyproject package version does not match release manifest")

    deps = project.get("dependencies")
    if not isinstance(deps, list) or not all(isinstance(item, str) for item in deps):
        errors.append("pyproject dependencies must be an exact string list")
    else:
        try:
            project_pins = parse_exact_pins(list(deps), source="pyproject.toml project.dependencies")
        except ValueError as exc:
            errors.append(str(exc))
        else:
            missing = sorted(set(core_pins) - set(project_pins))
            extra = sorted(set(project_pins) - set(core_pins))
            stale = sorted(
                name
                for name in core_pins.keys() & project_pins.keys()
                if core_pins[name] != project_pins[name]
            )
            if missing:
                errors.append("pyproject missing core runtime pins: " + ",".join(missing))
            if extra:
                errors.append("pyproject contains non-core runtime pins: " + ",".join(extra))
            if stale:
                errors.append("pyproject has stale core runtime versions: " + ",".join(stale))

    if build_tools.get("schema") != "k5-lab.build-tools/v1":
        errors.append("build-tools schema must be k5-lab.build-tools/v1")
    epoch = build_tools.get("source_date_epoch")
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 315532800:
        errors.append("source_date_epoch must be a deterministic ZIP-safe epoch")
    tools = build_tools.get("tools")
    if not isinstance(tools, list) or len(tools) != 1 or not isinstance(tools[0], dict):
        return errors + ["exactly one reviewed build tool is required"]
    tool = tools[0]
    if canonical_name(str(tool.get("name", ""))) != "setuptools":
        errors.append("setuptools must be the reviewed build backend")
    version = tool.get("version")
    if not isinstance(version, str) or not version:
        errors.append("reviewed setuptools version is missing")
    build_system = pyproject.get("build-system")
    if not isinstance(build_system, dict):
        errors.append("pyproject build-system table is missing")
    else:
        if build_system.get("build-backend") != "setuptools.build_meta":
            errors.append("build backend must remain setuptools.build_meta")
        expected = [f"setuptools=={version}"] if isinstance(version, str) and version else []
        if build_system.get("requires") != expected:
            errors.append("build-system requires must exactly pin the reviewed setuptools version")
    if tool.get("license_expression") != "MIT":
        errors.append("setuptools build-tool license must remain MIT")
    digest = tool.get("artifact_sha256")
    if not isinstance(digest, str) or HEX64_RE.fullmatch(digest) is None:
        errors.append("setuptools build-tool artifact requires exact sha256")
    filename = tool.get("artifact_filename")
    if not isinstance(filename, str) or filename != f"setuptools-{version}-py3-none-any.whl":
        errors.append("setuptools artifact filename does not match reviewed version")
    evidence_url = tool.get("evidence_url")
    if not isinstance(evidence_url, str) or not evidence_url.startswith("https://pypi.org/project/setuptools/"):
        errors.append("setuptools evidence must reference primary PyPI project metadata")
    if tool.get("shipping_candidate") is not False or tool.get("distribution_approved") is not False:
        errors.append("build tooling must remain non-shipping and unapproved for distribution")
    security = tool.get("security_review")
    if not isinstance(security, dict) or security.get("selected_version_fixed") is not True:
        errors.append("build-tool security review must record the selected fixed version")
    return errors


def load_repository(root: Path = ROOT):
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    manifest = json.loads((root / "provenance/release-manifest.json").read_text(encoding="utf-8"))
    build_tools = json.loads((root / "provenance/build-tools.json").read_text(encoding="utf-8"))
    core_pins = parse_exact_pins(
        (root / "requirements-core.txt").read_text(encoding="utf-8").splitlines(),
        source="requirements-core.txt",
    )
    return pyproject, manifest, build_tools, core_pins


def validate_repository(root: Path = ROOT) -> list[str]:
    try:
        pyproject, manifest, build_tools, core_pins = load_repository(root)
    except (OSError, json.JSONDecodeError, tomllib.TOMLDecodeError, ValueError) as exc:
        return [f"package metadata inputs unavailable or invalid: {exc}"]
    return validate_documents(
        pyproject=pyproject,
        manifest=manifest,
        build_tools=build_tools,
        core_pins=core_pins,
    )


def main() -> int:
    errors = validate_repository()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    _, _, build_tools, core_pins = load_repository()
    tool = build_tools["tools"][0]
    print(
        json.dumps(
            {
                "core_runtime_pins": len(core_pins),
                "build_tool": tool["name"],
                "build_tool_version": tool["version"],
                "shipping_candidate": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
