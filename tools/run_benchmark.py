"""Run synthetic benchmark; print aggregates, never weights or source records."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mosaic_lab.benchmark import benchmark

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--neural", action="store_true")
    parser.add_argument("--samples", type=int, default=2400)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    try:
        result = benchmark(size=args.samples, seed=args.seed, neural=args.neural)
    except (ValueError, ImportError) as exc:
        parser.exit(2, f"Benchmark not completed: {exc}\n")
    print(json.dumps(result, indent=2, allow_nan=False))
