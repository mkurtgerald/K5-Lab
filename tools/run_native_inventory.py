from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mosaic_lab.native_runtime import measure_native_rss_growth, runtime_native_inventory
from mosaic_lab.streaming import benchmark_stream


if __name__ == "__main__":
    evidence = {
        "native_runtime": runtime_native_inventory(),
        "native_rss_growth": measure_native_rss_growth(benchmark_stream),
    }
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
