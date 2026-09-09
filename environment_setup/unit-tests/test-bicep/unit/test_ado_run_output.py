"""Windows output handling for Azure DevOps run monitoring."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SCRIPT = (
    ROOT / "bootstrap/lib/create-new-aifactory-scaleset.sh"
).read_text(encoding="utf-8")


def test_ado_run_status_strips_windows_carriage_returns() -> None:
    function = SCRIPT[
        SCRIPT.index("aif_wait_ado_run()")
        : SCRIPT.index("aif_run_ado_pipeline()")
    ]
    assert "| tr -d '\\r')" in function
