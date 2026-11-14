"""Every test file of this suite is assigned to exactly one tier."""
from pathlib import Path

from tiers import MANIFEST

SUITE = Path(__file__).resolve().parent


def test_every_test_file_has_a_tier():
    files = sorted(path.relative_to(SUITE).as_posix() for path in SUITE.glob("test_*.py"))
    unlisted = [name for name in files if MANIFEST.tier_of(name) is None]
    missing = [name for tier in MANIFEST.tiers for name in tier.files if not (SUITE / name).is_file()]
    assert not unlisted, f"add to tiers.py: {unlisted}"
    assert not missing, f"listed in tiers.py but absent: {missing}"
