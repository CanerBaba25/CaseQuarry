import re
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator


def _date_only(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Use a date in YYYY-MM-DD format, without a time or timezone.")
    return date.fromisoformat(value)


DateOnly = Annotated[date, BeforeValidator(_date_only)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginInput(Input):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)
    totp_code: str | None = None


class SetupInput(LoginInput):
    token: str = Field(min_length=1, max_length=200)
    firm_name: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=1024)


class UserInput(Input):
    email: str = Field(min_length=3, max_length=320)
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=1024)
    role: Literal[
        "firm_admin", "attorney", "review_manager", "reviewer", "expert", "read_only", "auditor"
    ] = "reviewer"


class CaseInput(Input):
    matter_number: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=10000)
    client: str = Field(default="", max_length=200)
    jurisdiction: str = Field(default="", max_length=200)
    case_type: str = Field(default="civil", max_length=100)


class CasePatch(Input):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=10000)
    client: str | None = Field(default=None, max_length=200)
    jurisdiction: str | None = Field(default=None, max_length=200)
    case_type: str | None = Field(default=None, max_length=100)


class Reason(Input):
    reason: str = Field(min_length=3, max_length=2000)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value):
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Provide a meaningful reason of at least three characters.")
        return value


class MemberInput(Input):
    user_id: str
    role: Literal["matter_lead", "attorney", "review_manager", "reviewer", "expert", "read_only", "auditor"]


class CustodianInput(Input):
    display_name: str = Field(min_length=1, max_length=200)
    organization: str = Field(default="", max_length=200)


class SourceInput(Input):
    label: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="file-upload", max_length=100)
    custodian_id: str | None = None


class Filters(Input):
    item_types: list[str] = Field(default_factory=list, max_length=20)
    review_status: list[str] = Field(default_factory=list, max_length=20)
    privilege_status: list[str] = Field(default_factory=list, max_length=10)
    parser_state: list[str] = Field(default_factory=list, max_length=20)
    source_ids: list[str] = Field(default_factory=list, max_length=50)
    custodian_ids: list[str] = Field(default_factory=list, max_length=50)
    tags: list[str] = Field(default_factory=list, max_length=30)
    exclude_tags: list[str] = Field(default_factory=list, max_length=30)
    sender: str | None = Field(default=None, max_length=320)
    recipient: str | None = Field(default=None, max_length=320)
    date_field: str = "sent_at"
    date_from: str | None = None
    date_to: str | None = None
    has_attachment: bool | None = None
    bookmarked: bool | None = None
    thread_id: str | None = None
    person_id: str | None = None
    sender_person_id: str | None = Field(default=None, max_length=64)
    recipient_person_id: str | None = Field(default=None, max_length=64)
    missing_date: bool | None = None
    parent_id: str | None = None
    assigned_to: str | None = None


class Sort(Input):
    field: str = "sent_at"
    order: Literal["asc", "desc"] = "desc"


class SearchInput(Input):
    query: str = Field(default="", max_length=4096)
    mode: Literal["keyword", "hybrid", "semantic"] = "keyword"
    filters: Filters = Field(default_factory=Filters)
    sort: list[Sort] = Field(default_factory=lambda: [Sort()], min_length=1, max_length=1)
    group_by: str | None = None
    page_size: int = Field(default=50, ge=1, le=200)
    cursor: str | None = Field(default=None, max_length=2048)


class ReviewInput(Input):
    review_status: Literal["unreviewed", "needs_review", "responsive", "non_responsive"] | None = None
    privilege_status: Literal["none", "suspected", "confirmed", "cleared"] | None = None
    bookmarked: bool | None = None
    tags: list[str] | None = Field(default=None, max_length=100)
    assigned_to: str | None = None
    note: str | None = Field(default=None, max_length=10000)
    expected_version: int | None = Field(default=None, ge=0)

    @field_validator("review_status", mode="before")
    @classmethod
    def normalize_status(cls, value):
        return value.replace("-", "_") if isinstance(value, str) else value

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, value):
        if value is not None and any(not tag.strip() or len(tag) > 100 for tag in value):
            raise ValueError("Tags must be nonempty and at most 100 characters.")
        return list(dict.fromkeys(tag.strip() for tag in value)) if value is not None else None


class AnnotationInput(Input):
    text: str = Field(min_length=1, max_length=10000)
    span_id: str | None = None


class SavedInput(Input):
    name: str = Field(min_length=1, max_length=200)
    query_spec: SearchInput


class ReviewSetInput(Input):
    name: str = Field(min_length=1, max_length=200)
    query_spec: SearchInput | None = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=20000)


class ExportInput(Input):
    format: Literal["csv", "json", "zip"]
    reason: str = Field(min_length=3, max_length=2000)
    confirmed: bool
    query_spec: SearchInput | None = None
    evidence_ids: list[str] | None = Field(default=None, max_length=20000)
    review_set_id: str | None = None


class HoldInput(Reason):
    name: str = Field(min_length=1, max_length=200)


class IssueInput(Input):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=10000)


class IssueLinkInput(Input):
    evidence_id: str
    side: Literal["supports", "contradicts", "unclear"]
    note: str = Field(default="", max_length=10000)


class TaskInput(Input):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=10000)
    assigned_to: str | None = None
    due_date: DateOnly | None = None


class BulkReviewInput(Input):
    evidence_ids: list[str] = Field(min_length=1, max_length=200)
    changes: ReviewInput


class UploadInput(Input):
    filename: str = Field(min_length=1, max_length=500)
    byte_size: int = Field(ge=1)
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    source_id: str | None = None
    source_label: str = Field(default="Resumable upload", max_length=200)
    part_size: int = Field(default=4 * 1024 * 1024, ge=1024, le=8 * 1024 * 1024)
