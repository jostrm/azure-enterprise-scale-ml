from pathlib import Path
import sys

_CODE_ROOT = Path(__file__).resolve().parents[1]
if str(_CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CODE_ROOT))

from ml_model_factory.online import init, run

__all__ = ["init", "run"]
