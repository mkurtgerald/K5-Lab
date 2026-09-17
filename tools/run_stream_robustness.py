from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mosaic_lab.stream_robustness import (
    evaluate_stream_robustness,
    require_stream_robustness_acceptance,
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=600)
    parser.add_argument("--seed", type=int, default=31)
    parser.add_argument("--multi-seed", action="store_true")
    args = parser.parse_args()
    if args.multi_seed:
        result = require_stream_robustness_acceptance(size=args.samples)
    else:
        result = evaluate_stream_robustness(size=args.samples, seed=args.seed)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
