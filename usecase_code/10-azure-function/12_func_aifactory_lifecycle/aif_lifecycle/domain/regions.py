"""Azure region <-> AI Factory location suffix.

Copy of the table in purple's `bootstrap/lib/create-new-aifactory-scaleset.sh`, which owns it;
`tests/test_regions.py` fails if the two drift.
"""

from __future__ import annotations

from .errors import InvalidId

REGION_CODES = {
    "swedencentral": "sdc",
    "westeurope": "weu",
    "northeurope": "neu",
    "eastus": "eus",
    "eastus2": "eus2",
    "uksouth": "uks",
    "germanywestcentral": "gwc",
}
_REGIONS = {code: region for region, code in REGION_CODES.items()}


def code_for(region: str) -> str:
    try:
        return REGION_CODES[region.lower()]
    except (KeyError, AttributeError):
        raise InvalidId(f"Region '{region}' has no AI Factory location suffix.") from None


def region_for(code: str) -> str:
    try:
        return _REGIONS[code]
    except (KeyError, TypeError):
        known = ", ".join(sorted(_REGIONS))
        raise InvalidId(f"Region code '{code}' is not one of: {known}.") from None
