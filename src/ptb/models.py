"""Pydantic schema for the Phase 2 extraction output contract.

Implements the JSON shape defined in specs/extraction.spec.md's "Output contract"
section: one JSON document per source PTB, validated before it may reach
extracted/<filename>.json or be loaded into the database (Phase 3).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

VALID_CODES = {"I", "W", "RX", "R", "S", "O", "ALL"}
VALID_LEVELS = {"Aspirant", "Beginner", "Journey", "Expert"}
Format = Literal["nwcg_nextgen", "nwcg_legacy", "enhanced_gdoc"]


class DocumentMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    sha256: str
    pms_number: str | None
    format: Format
    position_codes: list[str]
    title: str
    edition_date: str | None = None
    ips_reference: str | None = None
    official: bool = True
    page_count: int = Field(gt=0)


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    title: str
    provisional_code: bool = False
    requirements_text: str | None = None
    attaches_to: list[str] | None = None
    extra_fields: dict = Field(default_factory=dict)


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_code: str
    task_number: int = Field(gt=0)
    category: str
    behavior: str | None = None
    level: str | None = None
    verbatim_text: str
    code_raw: str
    code_alternatives: list[str]
    clarifications: list[str] = Field(default_factory=list)
    page: int = Field(gt=0)

    @field_validator("code_alternatives")
    @classmethod
    def alternatives_are_known(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("code_alternatives must be non-empty")
        bad = set(v) - VALID_CODES
        if bad:
            raise ValueError(f"unknown code alternatives: {bad}")
        return v

    @field_validator("level")
    @classmethod
    def level_is_known(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_LEVELS:
            raise ValueError(f"unknown level: {v!r}")
        return v


class FieldObserved(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    page: int = Field(gt=0)


class ExtractedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: DocumentMeta
    positions: list[Position]
    tasks: list[Task]
    fields_observed: list[FieldObserved] = Field(default_factory=list)
    extra_fields: dict = Field(default_factory=dict)
