"""Generate one portable notebook per scenario/mode, without cloud side effects.

Batch notebooks are use-case leaves like every other example; the shared generator in
``examples`` composes them from the same sections as online and streaming leaves.
"""

from pathlib import Path

from .config import validate_scenario


def render_notebooks(scenario, output_dir, mode="custom", runtime_path="user-config/runtime.local.json") -> dict:
    from .examples import batch_notebook_leaf, render_example

    validate_scenario(scenario)
    if mode not in {"automl", "custom"}:
        raise ValueError("mode must be custom or automl")
    output = render_example(batch_notebook_leaf(scenario["task"], mode), scenario, Path(output_dir), runtime_path)
    return {"notebooks": [str(output)]}
