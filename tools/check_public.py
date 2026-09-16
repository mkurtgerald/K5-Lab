"""Defense-in-depth file/content gate. Not a guarantee of confidentiality."""
from pathlib import Path
import hashlib
import ipaddress
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "build", "dist"}
FORBIDDEN_SUFFIXES = {".pt", ".pth", ".onnx", ".safetensors", ".pkl", ".pickle", ".joblib",
 ".mp4", ".avi", ".mov", ".jpg", ".jpeg", ".png", ".wav", ".npy", ".npz", ".parquet", ".db", ".zip"}
ALLOWED_TOP = {"src", "tests", "tools", "docs", "provenance", ".github"}
ALLOWED_ROOT = {"README.md", "LICENSE", "AGENTS.md", "SECURITY.md", "THIRD_PARTY.md",
 ".gitignore", "pyproject.toml", "requirements-core.txt", "requirements-neural.txt",
 "requirements-s3-runtime.txt"}
TOKEN_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]*")
IP_RE = re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])")


def scan(root: Path, *, use_index: bool = False) -> list[str]:
    deny = set(json.loads((root / "provenance/public-token-denylist.json").read_text())["digests"])
    if use_index:
        output = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
        files = [root / name.decode() for name in output.split(b"\0") if name]
    else:
        files = [p for p in root.rglob("*") if not any(s in SKIP_DIRS for s in p.relative_to(root).parts)]
    failures = []
    for path in sorted(files):
        rel = path.relative_to(root)
        if path.is_symlink():
            failures.append(f"symlink: {rel}")
            continue
        if not path.is_file():
            continue
        if (len(rel.parts) == 1 and rel.name not in ALLOWED_ROOT) or (len(rel.parts) > 1 and rel.parts[0] not in ALLOWED_TOP):
            failures.append(f"unapproved path: {rel}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or path.name.startswith(".env"):
            failures.append(f"protected artifact type: {rel}")
        if path.stat().st_size > 300000:
            failures.append(f"oversize file: {rel}")
            continue
        try:
            data = path.read_text(encoding="utf-8")
        except UnicodeError:
            failures.append(f"non-text file: {rel}")
            continue
        for token in TOKEN_RE.findall(str(rel) + "\n" + data):
            if hashlib.sha256(token.lower().encode()).hexdigest() in deny:
                failures.append(f"protected token: {rel}")
                break
        lower = data.lower()
        # Assemble patterns to avoid treating scanner source as exposed content.
        needles = ["rt" + "sp://", "-----begin " + "private key", "github_" + "pat_", "gh" + "p_"]
        if any(s in lower for s in needles):
            failures.append(f"endpoint or credential pattern: {rel}")
        for match in IP_RE.findall(data):
            try:
                address = ipaddress.IPv4Address(match)
            except ValueError:
                continue
            if address.is_private or address.is_loopback or address.is_link_local:
                failures.append(f"private address pattern: {rel}")
                break
    return failures


if __name__ == "__main__":
    issues = scan(ROOT, use_index="--index" in sys.argv)
    if issues:
        print("Publication check FAILED\n" + "\n".join(issues))
        sys.exit(1)
    print("Publication check passed (heuristic checks only; manual review still required).")
