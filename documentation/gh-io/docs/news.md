# News & Releases

Stay up to date with the latest AI Factory releases, features, and breaking changes.

---

## Latest Releases

### Release 1.24
See [RELEASE_124.md](https://github.com/azure/Enterprise-Scale-AIFactory/blob/main/RELEASE_124.md) for full details.

### Release 1.23
See [RELEASE_123.md](https://github.com/azure/Enterprise-Scale-AIFactory/blob/main/RELEASE_123.md) for full details.

### Release 1.20
See [RELEASE_120.md](https://github.com/azure/Enterprise-Scale-AIFactory/blob/main/RELEASE_120.md) for full details.

---

## Feature Roadmap

The AI Factory follows a **pin-to-release-branch** model. When a new feature is available or a breaking change requires a fix, you update by pointing your submodule to the latest release branch.

See the main [README](index.md) for the current recommended release branch.

---

## Breaking Changes Policy

All breaking changes are documented in the release notes. The AI Factory team aims to maintain backward compatibility for all `variables.yaml` / `.env` parameters across minor releases.

!!! warning
    When upgrading between major releases, review the release notes carefully. Pay particular attention to deprecated variables (e.g. `enableAIServices`, `enableAIFoundryHub`, `addAIFoundryHub` — all deprecated from 2026-01 onwards; use `enableAIFoundry` instead).
