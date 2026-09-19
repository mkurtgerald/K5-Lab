from __future__ import annotations

import ast
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mosaic_lab.adapter_contract import CONTRACT_VERSION

FORBIDDEN_IMPORT_ROOTS = {
    "socket",
    "ssl",
    "http",
    "urllib",
    "requests",
    "httpx",
    "aiohttp",
    "ftplib",
    "smtplib",
    "pickle",
    "dill",
    "cloudpickle",
    "shelve",
    "sqlite3",
    "tempfile",
    "marshal",
}
WRITE_METHODS = {"write_text", "write_bytes", "touch", "mkdir", "unlink", "rename"}
WRITE_MODE_CHARS = set("wax+")
ALLOWED_SUBPROCESS_FILE = "native_runtime.py"
ALLOWED_SUBPROCESS_EXE = "ldd"
MAX_SUBPROCESS_TIMEOUT_SECONDS = 5.0


def _call_name(node: ast.Call) -> str | None:
    value = node.func
    parts: list[str] = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
        return ".".join(reversed(parts))
    return None


def _constant_string(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _keyword(node: ast.Call, name: str) -> ast.AST | None:
    return next((item.value for item in node.keywords if item.arg == name), None)


def _validate_subprocess_call(path: Path, node: ast.Call, errors: list[str]) -> None:
    rel = path.as_posix()
    if path.name != ALLOWED_SUBPROCESS_FILE:
        errors.append(f"{rel}:{node.lineno}: subprocess is not allowed in shipping runtime")
        return
    if not node.args or not isinstance(node.args[0], (ast.List, ast.Tuple)) or not node.args[0].elts:
        errors.append(f"{rel}:{node.lineno}: native inspection subprocess must use a literal argv")
        return
    executable = _constant_string(node.args[0].elts[0])
    if executable != ALLOWED_SUBPROCESS_EXE:
        errors.append(f"{rel}:{node.lineno}: only reviewed ldd native inspection is allowed")
    shell = _keyword(node, "shell")
    if isinstance(shell, ast.Constant) and shell.value is True:
        errors.append(f"{rel}:{node.lineno}: shell=True is forbidden")
    timeout = _keyword(node, "timeout")
    if timeout is None:
        errors.append(f"{rel}:{node.lineno}: native inspection subprocess requires bounded timeout")
    elif isinstance(timeout, ast.Constant):
        value = timeout.value
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < float(value) <= MAX_SUBPROCESS_TIMEOUT_SECONDS:
            errors.append(f"{rel}:{node.lineno}: subprocess timeout exceeds reviewed bound")
    elif not (isinstance(timeout, ast.Name) and timeout.id == "MAX_LDD_SECONDS"):
        errors.append(f"{rel}:{node.lineno}: subprocess timeout must use reviewed bound")


def scan_source(path: Path, text: str) -> list[str]:
    errors: list[str] = []
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return [f"{path.as_posix()}:{exc.lineno}: invalid Python syntax"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in FORBIDDEN_IMPORT_ROOTS:
                    errors.append(f"{path.as_posix()}:{node.lineno}: forbidden runtime import {alias.name}")
                if root == "subprocess" and path.name != ALLOWED_SUBPROCESS_FILE:
                    errors.append(f"{path.as_posix()}:{node.lineno}: subprocess import is restricted to native inspection")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".", 1)[0]
            if root in FORBIDDEN_IMPORT_ROOTS:
                errors.append(f"{path.as_posix()}:{node.lineno}: forbidden runtime import {module}")
            if root == "subprocess" and path.name != ALLOWED_SUBPROCESS_FILE:
                errors.append(f"{path.as_posix()}:{node.lineno}: subprocess import is restricted to native inspection")
        elif isinstance(node, ast.Call):
            name = _call_name(node)
            if name in {"subprocess.run", "subprocess.Popen", "subprocess.call", "subprocess.check_call", "subprocess.check_output"}:
                _validate_subprocess_call(path, node, errors)
            method = node.func.attr if isinstance(node.func, ast.Attribute) else None
            if method in WRITE_METHODS:
                errors.append(f"{path.as_posix()}:{node.lineno}: runtime filesystem mutation is forbidden ({method})")
            if name == "open" or method == "open":
                mode_node = _keyword(node, "mode")
                if mode_node is None:
                    if name == "open" and len(node.args) >= 2:
                        mode_node = node.args[1]
                    elif method == "open" and node.args:
                        mode_node = node.args[0]
                mode = _constant_string(mode_node) if mode_node is not None else "r"
                if mode is None:
                    errors.append(f"{path.as_posix()}:{node.lineno}: dynamic file mode is not allowed in runtime source")
                elif any(char in mode for char in WRITE_MODE_CHARS):
                    errors.append(f"{path.as_posix()}:{node.lineno}: runtime file write mode is forbidden")
            if name in {"__import__", "importlib.import_module"}:
                errors.append(f"{path.as_posix()}:{node.lineno}: dynamic runtime import is forbidden")
    return errors


def validate_documents(*, security: dict[str, object], adapter_contract: dict[str, object], release_manifest: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if security.get("schema") != "k5-lab.security-review/v1":
        errors.append("security review schema must be k5-lab.security-review/v1")
    if security.get("scope") != "public-core-shipping-candidate":
        errors.append("security review must cover public core shipping candidate")
    for flag in ("commercial_distribution", "production_qualified", "owner_security_approval", "privacy_review_approved", "external_pen_test_complete"):
        if security.get(flag) is not False:
            errors.append(f"security review must keep {flag}=false")
    runtime = security.get("runtime_policy")
    if not isinstance(runtime, dict):
        errors.append("runtime security policy is missing")
    else:
        expected = {
            "network_default": False,
            "persistence_default": False,
            "unsafe_deserialization": False,
            "temporary_file_runtime": False,
            "unrestricted_subprocess": False,
        }
        for key, value in expected.items():
            if runtime.get(key) is not value:
                errors.append(f"runtime policy must keep {key}={str(value).lower()}")
        exception = runtime.get("subprocess_exception")
        if not isinstance(exception, dict) or exception.get("module") != "native_runtime.py" or exception.get("executable") != "ldd" or exception.get("max_timeout_seconds") != MAX_SUBPROCESS_TIMEOUT_SECONDS:
            errors.append("runtime subprocess exception must remain the bounded ldd native inspection")
    checkpoint = security.get("checkpoint_policy")
    if not isinstance(checkpoint, dict) or checkpoint.get("format") != "canonical-json" or checkpoint.get("filesystem_io") is not False or checkpoint.get("unsafe_deserialization") is not False or checkpoint.get("trusted_origin_required") is not True or checkpoint.get("integrity_is_authenticity") is not False:
        errors.append("checkpoint policy must remain canonical JSON, in-memory, trusted-origin and non-authenticating")
    fixtures = security.get("fixture_policy")
    if not isinstance(fixtures, dict) or fixtures.get("public_fixture_class") != "synthetic-or-opaque" or fixtures.get("real_sensor_data_allowed") is not False:
        errors.append("public fixture policy must remain synthetic/opaque with no real sensor data")
    publication = security.get("publication_boundary")
    expected_publication = {
        "credential_endpoint_scan": True,
        "private_address_scan": True,
        "forbidden_artifact_scan": True,
        "non_text_and_size_scan": True,
    }
    if publication != expected_publication:
        errors.append("security review must preserve the complete publication scanning boundary")

    transport = adapter_contract.get("transport") if isinstance(adapter_contract, dict) else None
    privacy = adapter_contract.get("privacy") if isinstance(adapter_contract, dict) else None
    if not isinstance(transport, dict) or transport.get("network_required") is not False or transport.get("persistence_required") is not False:
        errors.append("adapter contract must default to no network and no persistence")
    if not isinstance(privacy, dict) or privacy.get("opaque_identifiers_only") is not True or privacy.get("synthetic_public_fixtures_only") is not True:
        errors.append("adapter contract privacy boundary must remain opaque/synthetic-only")
    for flag in ("commercial_distribution", "production_qualified", "owner_release_approved"):
        if release_manifest.get(flag) is not False:
            errors.append(f"release manifest must keep {flag}=false during security qualification")
    return errors


def active_adapter_contract_path(root: Path = ROOT) -> Path:
    return root / f"docs/contracts/adapter-v{CONTRACT_VERSION}.json"


def validate_repository(root: Path = ROOT) -> list[str]:
    try:
        security = json.loads((root / "provenance/security-review.json").read_text(encoding="utf-8"))
        adapter = json.loads(active_adapter_contract_path(root).read_text(encoding="utf-8"))
        manifest = json.loads((root / "provenance/release-manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"security review inputs unavailable or invalid: {exc}"]
    errors = validate_documents(security=security, adapter_contract=adapter, release_manifest=manifest)
    source_root = root / "src/mosaic_lab"
    sources = sorted(source_root.glob("*.py"))
    if not sources:
        errors.append("shipping runtime source is missing")
        return errors
    for path in sources:
        errors.extend(scan_source(path.relative_to(root), path.read_text(encoding="utf-8")))
    return errors


def main() -> int:
    errors = validate_repository()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    source_count = len(list((ROOT / "src/mosaic_lab").glob("*.py")))
    print(json.dumps({
        "schema": "k5-lab.security-release-check/v1",
        "shipping_source_files": source_count,
        "network_default": False,
        "persistence_default": False,
        "unsafe_deserialization": False,
        "temporary_file_runtime": False,
        "commercial_distribution": False,
        "production_qualified": False,
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
