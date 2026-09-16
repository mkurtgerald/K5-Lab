import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mosaic_lab.allocation import benchmark_allocation

if __name__ == "__main__":
    print(json.dumps(benchmark_allocation(), sort_keys=True))
