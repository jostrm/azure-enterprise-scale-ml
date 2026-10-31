# Dual-graph snapshots (meta/graphify)

**This folder is empty in Git on purpose.** It is the default output and query root for the
dual knowledge graphs (code graph `[G]` and architecture vault `[A]`), but every generated file is
excluded by [`.gitignore`](.gitignore): `snapshots/`, `release-assets/`, `current.json`,
`graph.json`, `graph.html`, `GRAPH_REPORT.md`. A fresh clone therefore has no snapshot, and the
query CLI reports `snapshot_unavailable`. An empty folder is not evidence of a failed refresh.

## Where the snapshots are

No snapshot is committed to this repository. A snapshot exists in these places:

| Location | What it is |
|---|---|
| **GitHub Release assets** on a `release_NNN` tag | The published snapshot for that release: `aifactory-dual-graph-release_NNN.zip` and its `.sha256` checksum, uploaded only after unit-test tiers 1-5 passed. This is where to get a shared, versioned snapshot. |
| An operator's local `meta/graphify` | Generated on that workstation. `current.json` points to the active `snapshots/<snapshot-id>/` folder (integrity manifest, graph and copied architecture notes). |
| A deployed AI Factory Agent chat bundle | `40-aifactory-agent/deploy.py` copies the snapshot pinned by `dual_graph.expected_snapshot_id` into `deployments/<sha256>/agent-bundle.tar.gz` in the deployment's private Blob container. The app reads it from `/tmp/agent-app/dual_graph/snapshots/<snapshot-id>`. |
| A packaged AI Factory MCP release | `mcp/deploy/release.py` validates and includes the pinned snapshot in the release. |

A deployment's snapshot is the one pinned in its configuration, which may be older than the
latest release. A snapshot ID, a release tag, the repository HEAD and the deployed version are
different facts.

## Use a release snapshot

From the repository root (needs the GitHub CLI signed in, or use `--asset` with downloaded files):

```powershell
python environment_setup\graphify\release_snapshot.py fetch --tag release_125
```

It verifies the checksum and the snapshot's integrity manifest, then unpacks it to
`meta\graphify\snapshots\<snapshot-id>` and prints the `dual_graph` values to pin
(`snapshot_root` and `expected_snapshot_id`) for the chat agent or the MCP. It does not change
`current.json`. Query it directly:

```powershell
$env:PYTHONPATH = Join-Path $PWD 'usecase_code\40-agent-factory\40-aifactory-agent'
python -m aifactory_agent.dual_graph --root meta\graphify\snapshots\<snapshot-id> status
```

## Publish a release snapshot

Only for an explicit release, from a clean checkout of the pushed release commit, in the
extraction environment described in the
[dual-graph lifecycle contract](../../documentation/architecture/contracts/dual-graph-lifecycle.md):

```powershell
environment_setup\graphify\.venv\Scripts\python.exe environment_setup\graphify\release_snapshot.py publish --tag release_125 --test-python <python with test-bicep requirements>
```

It runs unit-test tiers 1-5 first and stops on any failure. Then it generates the snapshot and
writes the zip and checksum to `meta\graphify\release-assets\`, and prints the remaining `git`
and `gh` commands. Add `--apply` to create and push the tag and upload the assets. It runs on your
machine, not in GitHub Actions, and it never replaces a snapshot already uploaded for a tag.
Pushing the tag also runs every test tier once in `infrastructure-tests.yml`.

## Generate a local snapshot

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
