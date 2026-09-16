from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mosaic_lab.simulation import benchmark_simulation

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizon", type=int, default=64)
    args = parser.parse_args()
    print(json.dumps(benchmark_simulation(horizon=args.horizon), sort_keys=True, separators=(",", ":")))
