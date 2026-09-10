import copy
import json

import pytest

from src import wizard


@pytest.mark.parametrize("mode", ["private", "hybrid", "public"])
@pytest.mark.parametrize("kind", ["json", "env"])
def test_imported_flags_determine_mode_and_roundtrip_without_changing_values(tmp_path, mode, kind):
    flags = wizard.NETWORK_MODE_FLAGS[mode]
    path = tmp_path / ("variables.json" if kind == "json" else ".env")
    if kind == "json":
        path.write_text(json.dumps({"dev": flags}), encoding="utf-8")
    else:
        path.write_text("\n".join(f"{wizard.ENV_MAP[key]}={value}" for key, value in flags.items()), encoding="utf-8")
    state = copy.deepcopy(wizard.DEFAULT_STATE)
    state["network_mode"] = "public" if mode != "public" else "private"
    importer = wizard._import_json_to_state if kind == "json" else wizard._import_env_to_state
    assert importer(str(path), state) == 3
    assert state["network_mode"] == mode
    assert {key: state[key] for key in flags} == flags
    exported = wizard._render_variables_json(state)
    assert {key: str(exported["dev"][key]).lower() for key in flags} == flags


def test_incomplete_or_unmatched_flags_do_not_guess_a_mode(tmp_path):
    for supplied in (
        {"allowPublicAccessWhenBehindVnet": "false"},
        {"allowPublicAccessWhenBehindVnet": "false", "enablePublicGenAIAccess": "false",
         "enablePublicAccessWithPerimeter": "true"},
    ):
        state = {"network_mode": "original"}
        path = tmp_path / "variables.json"
        path.write_text(json.dumps({"dev": supplied}), encoding="utf-8")
        wizard._import_json_to_state(str(path), state)
        assert state["network_mode"] == "original"
        assert all(state[key] == value for key, value in supplied.items())
