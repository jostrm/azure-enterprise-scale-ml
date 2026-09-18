"""Review and edit JSON-origin legacy drafts without reconstructing wizard state."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from .client import AzureFactoryClient, canonical_json_hash, redact_secrets
from .errors import BlockedError, ConfigError, FailureError


@dataclass(frozen=True)
class ConfigurationDraft:
    client: AzureFactoryClient = field(repr=False)
    folder: str
    project_number: str
    _state: dict[str, Any] = field(repr=False)
    _changes: dict[str, Any] = field(repr=False)
    _warnings: list[dict[str, Any]] = field(repr=False)

    @classmethod
    def load(
        cls, client: AzureFactoryClient, folder: str, project_number: str,
        *, changes: dict[str, Any] | None = None,
    ) -> ConfigurationDraft:
        if not isinstance(project_number, str) or not project_number.isascii() or not project_number.isdigit():
            raise ConfigError("Project number must be a string of digits.")
        patch = {} if changes is None else changes
        if not isinstance(patch, dict):
            raise ConfigError("Configuration changes must be a JSON object of wizard field replacements.")
        try:
            canonical_json_hash(patch)
        except (TypeError, ValueError) as exc:
            raise ConfigError("Configuration changes must contain finite JSON values.") from exc
        number = project_number.zfill(3)
        loaded = client.configuration_load(folder, number)
        state = loaded.get("state")
        selected = state.get("project_number_000") if isinstance(state, dict) else None
        if not isinstance(selected, str) or not selected.isascii() or not selected.isdigit() or selected.zfill(3) != number:
            raise FailureError("Configuration load did not return the selected project.")
        # The reference is opaque: never reconstruct it, expose it as a form field, or drop it.
        if not isinstance(state.get("_json_source"), dict) or not state["_json_source"]:
            raise BlockedError(
                "A persistent JSON-source reference is required. Re-open the original JSON project "
                "with a current API host; do not use an older lossy snapshot or inline import."
            )
        for key in patch:
            if not isinstance(key, str) or key.startswith("_") or key == "project_number_000":
                raise ConfigError("Changes cannot replace private metadata or project identity.")
            if key not in state:
                raise ConfigError(f"Unknown wizard field: {key}. Choose fields from the selected draft/schema.")
        warnings = _issues(loaded.get("warnings", []), "load warnings")
        return cls(client, folder, number, copy.deepcopy(state), copy.deepcopy(patch), warnings)

    def _edited_state(self) -> dict[str, Any]:
        state = copy.deepcopy(self._state)
        state.update(copy.deepcopy(self._changes))
        return state

    def review(self, *, write_variables: bool = True) -> dict[str, Any]:
        """Validate and render in memory; no configuration files are written."""
        state = self._edited_state()
        validation = self.client.configuration_validate(state)
        if type(validation.get("valid")) is not bool:
            raise FailureError("Malformed configuration validation result.")
        issues = _issues(validation.get("issues"), "validation issues")
        if validation["valid"] and any(item.get("severity", "error") != "warning" for item in issues):
            raise FailureError("Configuration validation contradicts its error findings.")
        warnings = copy.deepcopy(self._warnings)
        rendered = None
        if validation["valid"]:
            rendered = self.client.configuration_export(state)
            if rendered.get("format") != "json" or not isinstance(rendered.get("content"), str):
                raise FailureError("Malformed JSON configuration render response.")
            warnings.extend(_issues(rendered.get("warnings", []), "export warnings"))
        # Bind approval to the endpoint, exact source/draft, patch, output and write choice.
        # This is a review checksum, not server-side authorization or an atomic ETag.
        review_id = canonical_json_hash({
            "version": 1, "base_url": self.client.canonical_base_url,
            "folder": self.folder, "project_number": self.project_number,
            "state": self._state, "changes": self._changes,
            "validation": validation, "warnings": warnings,
            "content": rendered["content"] if rendered is not None else None,
            "write_variables": write_variables,
        })
        return {
            "review_id": review_id, "can_save": validation["valid"],
            "folder": self.folder, "project_number": self.project_number,
            "changed_fields": sorted(self._changes),
            "write_variables": write_variables,
            "validation": redact_secrets(validation, self.client.api_key),
            "warnings": redact_secrets(warnings, self.client.api_key),
            "effects": (
                ["Save the selected project's local snapshot and pipeline variable files; no deployment."]
                if write_variables else ["Save only the selected project's local snapshot; no deployment."]
            ),
        }

    def save(self, expected_review: str, *, write_variables: bool = True) -> dict[str, Any]:
        """Caller must authorize this exact review before saving. Never deploys."""
        if not isinstance(expected_review, str) or len(expected_review) != 64:
            raise ConfigError("Supply the review_id from the separately approved configuration review.")
        current = self.review(write_variables=write_variables)
        if not current["can_save"]:
            raise BlockedError("Configuration validation failed; no save was attempted.", details=current)
        if current["review_id"] != expected_review:
            raise BlockedError("Configuration, changes, host or write choice changed; review again before saving.")
        result = self.client.configuration_save(self._edited_state(), write_variables=write_variables)
        if not isinstance(result.get("snapshot_path"), str) or not result["snapshot_path"]:
            raise FailureError("Save response is missing snapshot_path; inspect server state before retrying.")
        variables_path = result.get("variables_path")
        if (write_variables and (not isinstance(variables_path, str) or not variables_path)
                or not write_variables and variables_path is not None):
            raise FailureError("Save response does not match the variable-file write choice; inspect server state before retrying.")
        return redact_secrets({
            "snapshot_path": result["snapshot_path"], "variables_path": variables_path,
            "warnings": _issues(result.get("warnings", []), "save warnings"),
        }, self.client.api_key)


def _issues(value: Any, context: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("message"), str) for item in value
    ):
        raise FailureError(f"Malformed configuration {context}.")
    return copy.deepcopy(value)
