from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mosaic_lab.stream_multiseed import evaluate_multi_seed_quality

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=600)
    args = parser.parse_args()
    result = evaluate_multi_seed_quality(size=args.samples)
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 2)
