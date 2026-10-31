# Dual-graph snapshots (meta/graphify)

**This folder is empty in Git on purpose.** It is the default output and query root for the
dual knowledge graphs (code graph `[G]` and architecture vault `[A]`), but every generated file is
excluded by [`.gitignore`](.gitignore): `snapshots/`, `current.json`, `graph.json`, `graph.html`,
`GRAPH_REPORT.md`. A fresh clone therefore has no snapshot, and the query CLI reports
`snapshot_unavailable`. An empty folder is not evidence of a failed refresh.

## Where the snapshots are

No snapshot is stored anywhere in this repository. A snapshot exists only in these places:

| Location | What it is |
|---|---|
| An operator's local `meta/graphify` | Generated on that workstation. `current.json` points to the active `snapshots/<snapshot-id>/` folder (integrity manifest, graph and copied architecture notes). It is never committed. |
| A deployed AI Factory Agent chat bundle | `40-aifactory-agent/deploy.py` copies the verified snapshot pinned by `dual_graph.expected_snapshot_id` into `deployments/<sha256>/agent-bundle.tar.gz` in the deployment's private Blob container. The app reads it from `/tmp/agent-app/dual_graph/snapshots/<snapshot-id>`. |
| A packaged AI Factory MCP release | `mcp/deploy/release.py` validates and includes the pinned snapshot in the release. |

The latest snapshot is the one an operator generated most recently on their own machine. A
deployment's snapshot is the one pinned in its configuration, which may be older. A snapshot ID,
the repository HEAD and the deployed version are three different facts. Snapshot IDs belong in the
generation handoff or the deployment configuration, not in this folder.

## Generate or refresh a local snapshot

From the repository root, in the dedicated extraction environment (Python 3.12, pinned Graphify;
set it up once as described in the
[dual-graph lifecycle contract](../../documentation/architecture/contracts/dual-graph-lifecycle.md)):

```powershell
environment_setup\graphify\.venv\Scripts\python.exe environment_setup\graphify\generate.py --repository-root .
```

Generation is local and offline. It refuses to publish while the indexed sources change, and a
failed run never replaces a valid active snapshot. Scratch work goes to the git-ignored
`.graph-work-*` and `graphify-out` folders.

## Check what is here

```powershell
$env:PYTHONPATH = Join-Path $PWD 'usecase_code\40-agent-factory\40-aifactory-agent'
python -m aifactory_agent.dual_graph --root meta\graphify --repository-root . status
```

`snapshot_unavailable` means that no snapshot was generated in this checkout. A stale or unverified
status means that a snapshot exists but no longer matches the current source. Neither case gives
permission to skip source inspection: report the limitation and inspect the source directly
(see [AGENTS.md](../../AGENTS.md)).
