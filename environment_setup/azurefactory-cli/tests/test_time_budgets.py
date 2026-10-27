"""Client-side time budgets of the azurefactory CLI and SDK (doubled 2026-10-27)."""
from __future__ import annotations

import inspect

from azurefactory import cli, client, workflow_events


def test_cli_default_budgets_are_doubled():
    assert cli.DEFAULT_REQUEST_TIMEOUT_SECONDS == 60.0
    assert cli.PREFLIGHT_REQUEST_TIMEOUT_SECONDS == 360.0
    assert cli.COST_REQUEST_TIMEOUT_SECONDS == 600.0
    assert cli.WATCH_TIMEOUT_SECONDS == 600.0
    assert cli.WATCH_MAX_RETRIES == 6
    assert cli.POLL_TIMEOUT_SECONDS == 1200.0


def test_cli_parser_uses_the_budgets():
    parser = cli.build_parser()
    args = parser.parse_args(["runtime", "poll", "--folder", "C:\\f", "--job-id", "j"])
    assert args.poll_timeout == cli.POLL_TIMEOUT_SECONDS


def test_sdk_defaults_are_doubled():
    assert client.AzureFactoryClient().timeout == 60.0
    watch = inspect.signature(client.AzureFactoryClient.watch_workflow_run).parameters
    assert watch["timeout"].default == 600.0 and watch["max_retries"].default == 6
    events = inspect.signature(workflow_events.watch).parameters
    assert events["timeout"].default == 600.0 and events["max_retries"].default == 6
