# AI Factory IaC test suite

Scalable, N-tier test suite for AI Factory infrastructure-as-code. Bash + Python +
Azure CLI; mocking for offline unit tests; live deploy/cleanup for integration.

## Layers (once-and-only-once)

```
tests/
  base/        # no domain knowledge: paths, config parsing, az/nslookup wrappers
  domain/      # AI Factory concepts: scenarios, common/project deploy, PaaS checks
  app/         # lifecycle context managers (deploy -> verify -> guaranteed cleanup)
  unit/        # offline, fast, mocked (no Azure)
  integration/ # live Azure; skipped unless LIVE_AZURE=1
  test_env_parity.py        # existing ADO <-> GitHub var parity
  test_workflow_parity.py   # existing workflow parity
```

## Run

```bash
cd environment_setup/unit-tests/test-bicep
python -m pytest unit -q            # offline unit tests
LIVE_AZURE=1 az login && python -m pytest integration -q   # live (opt-in)
```

## Idempotency
Integration tests deploy through `app/lifecycle.py` context managers that always
run cleanup (delete resource groups) in `finally`, so the suite re-runs cleanly.

## Implementation status
Base/domain/app scaffolding + offline unit tests implemented. Deploy/cleanup and
live PaaS checks are placeholders to fill in one-by-one. See SUGGESTED_TESTS.md.
