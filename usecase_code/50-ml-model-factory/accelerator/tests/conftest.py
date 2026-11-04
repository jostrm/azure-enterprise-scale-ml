"""Keep default local tracking artifacts in the generated environment."""

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MLFLOW_TRACKING_URI", (ROOT / "ml-environment" / "mlruns").as_uri())
