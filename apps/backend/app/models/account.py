from typing import Any, Literal

from pydantic import BaseModel, Field


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)


class Profile(BaseModel):
    id: str
    display_name: str
    created_at: str
    updated_at: str


class AccountOverview(BaseModel):
    id: str
    email: str | None
    created_at: str | None
    last_sign_in_at: str | None
    profile: Profile


class AccountDeletion(BaseModel):
    password: str = Field(min_length=1, max_length=1000)
    confirmation: Literal["DELETE"]


class DataExport(BaseModel):
    format_version: Literal[1] = 1
    exported_at: str
    account: dict[str, Any]
    profile: dict[str, Any] | None
    decisions: list[dict[str, Any]]
    decision_options: list[dict[str, Any]]
    decision_messages: list[dict[str, Any]]
    evaluations: list[dict[str, Any]]
