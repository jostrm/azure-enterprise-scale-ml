"""Client-side time budgets of the azurefactory CLI and SDK: three times the originals (doubled 2026-10-27,
tripled 2026-10-28 so every budget keeps a margin of three over its longest observed use)."""
from __future__ import annotations

import inspect

from azurefactory import cli, client, workflow_events


def test_cli_default_budgets_are_tripled():
    assert cli.DEFAULT_REQUEST_TIMEOUT_SECONDS == 90.0
    assert cli.PREFLIGHT_REQUEST_TIMEOUT_SECONDS == 540.0
    assert cli.COST_REQUEST_TIMEOUT_SECONDS == 900.0
    assert cli.WATCH_TIMEOUT_SECONDS == 900.0
    assert cli.WATCH_MAX_RETRIES == 9
    assert cli.POLL_TIMEOUT_SECONDS == 1800.0


def test_cli_parser_uses_the_budgets():
    parser = cli.build_parser()
    args = parser.parse_args(["runtime", "poll", "--folder", "C:\\f", "--job-id", "j"])
    assert args.poll_timeout == cli.POLL_TIMEOUT_SECONDS


def test_sdk_defaults_are_tripled():
    assert client.AzureFactoryClient().timeout == 90.0
    watch = inspect.signature(client.AzureFactoryClient.watch_workflow_run).parameters
    assert watch["timeout"].default == 900.0 and watch["max_retries"].default == 9
    events = inspect.signature(workflow_events.watch).parameters
    assert events["timeout"].default == 900.0 and events["max_retries"].default == 9
