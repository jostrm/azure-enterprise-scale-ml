import re

import pytest

from aif_lifecycle.domain import regions
from aif_lifecycle.domain.errors import InvalidId

from conftest import find_accelerator_file

SHELL_TABLE = "bootstrap/lib/create-new-aifactory-scaleset.sh"


def test_region_codes_map_both_ways():
    assert regions.code_for("swedencentral") == "sdc"
    assert regions.region_for("sdc") == "swedencentral"
    assert regions.region_for("gwc") == "germanywestcentral"


def test_unknown_region_or_code_is_an_invalid_id():
    with pytest.raises(InvalidId):
        regions.code_for("moon")
    with pytest.raises(InvalidId):
        regions.region_for("xyz")


def test_table_matches_the_accelerator_bootstrap_table():
    """The bootstrap shell script owns purple's region codes; this copy must not drift."""
    path = find_accelerator_file(SHELL_TABLE)
    assert path is not None, f"{SHELL_TABLE} must be reachable from the template (purple or its submodule)"
    case_block = path.read_text(encoding="utf-8").split('case "${AIF_LOCATION,,}" in', 1)[1].split("esac", 1)[0]
    pairs = re.findall(r'AIF_LOCATION="([a-z0-9]+)"\s*;?\s*AIF_LOCATION_SHORT="([a-z0-9]+)"', case_block)
    assert pairs, "the bootstrap region table could not be read"
    assert dict(pairs) == regions.REGION_CODES
