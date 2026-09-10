"""Reviewed parameter forms derived from the selected published ARM schemas."""

from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from src.factory_catalog_models import ClosedModel, CatalogSourceVersion


class ParameterField(ClosedModel):
    name: str
    required: bool
    resolved: bool
    configured: bool
    sensitive: bool


class ParameterTemplate(ClosedModel):
    template: str
    scope: Literal["subscription", "resource-group"]
    parameter_schema: dict[str, JsonValue]
    fields: list[ParameterField]
    resource_group_ids: list[str]
    common_dependency_ids: list[str]


class CatalogParameters(ClosedModel):
    contract_version: Literal[1] = 1
    source_revision: str
    schema_revision: str
    factory_id: UUID
    scale_set_id: UUID
    project_id: UUID | None = None
    source_version: CatalogSourceVersion
    templates: list[ParameterTemplate]
    requires_profile_reset: bool
    warnings: list[str]


class ParameterPatch(ClosedModel):
    template: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    parameters: dict[str, JsonValue] = Field(default_factory=dict, max_length=1000)
    unset: list[str] = Field(default_factory=list, max_length=1000)
    resource_group_id: str | None = Field(default=None, max_length=1024)
    template_spec_id: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def unique_edits(self):
        if len(set(self.unset)) != len(self.unset) or set(self.unset) & set(self.parameters):
            raise ValueError("Parameter edits must be disjoint and unique.")
        return self


class CatalogParameterPrepare(ClosedModel):
    folder: str = Field(min_length=1, max_length=1024)
    contract_version: Literal[1]
    factory_id: UUID
    scale_set_id: UUID
    project_id: UUID | None = None
    version_ref: str | None = Field(default=None, min_length=1, max_length=100)
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    schema_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    reset_profile: bool = Field(default=False, strict=True)
    templates: list[ParameterPatch] = Field(min_length=1, max_length=64)

    @model_validator(mode="before")
    @classmethod
    def acknowledged_contract(cls, value):
        if isinstance(value, dict) and type(value.get("contract_version")) is not int:
            raise ValueError("Contract version must be the integer 1.")
        return value

    @model_validator(mode="after")
    def unique_templates(self):
        if len({item.template for item in self.templates}) != len(self.templates):
            raise ValueError("Each template may occur only once.")
        return self
