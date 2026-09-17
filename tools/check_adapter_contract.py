from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mosaic_lab.adapter_contract import canonical_contract_text


def validate_repository(root: Path = ROOT) -> list[str]:
    path = root / "docs/contracts/adapter-v1.json"
    if not path.is_file():
        return ["docs/contracts/adapter-v1.json is missing"]
    actual = path.read_text(encoding="utf-8")
    expected = canonical_contract_text()
    if actual != expected:
        return ["adapter contract file is stale or not canonical"]
    return []


def main() -> int:
    errors = validate_repository()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("adapter-contract-v1:ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
