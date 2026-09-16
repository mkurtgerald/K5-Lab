"""Fail closed while any exact dependency artifact lacks distribution review."""
from pathlib import Path
import json
import sys
ROOT = Path(__file__).resolve().parents[1]
def blockers(document):
    return [entry["name"] for entry in document["components"] if entry["status"] == "used"
            and (not entry.get("artifact_sha256") or not entry.get("distribution_approved"))]
if __name__ == "__main__":
    pending = blockers(json.loads((ROOT / "provenance/components.json").read_text()))
    print("Release blocked: " + ", ".join(pending) if pending else "Release dependency review passed")
    sys.exit(bool(pending))
