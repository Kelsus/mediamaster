from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class Medium(str, Enum):
    show = "show"
    book = "book"


class ShowType(str, Enum):
    tv = "tv"
    movie = "movie"
    book = "book"


class Status(str, Enum):
    to_watch = "to_watch"
    watching = "watching"
    done = "done"
    poubelle = "poubelle"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ShowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    show_type: ShowType
    medium: Medium = Medium.show
    author: Optional[str] = Field(default=None, max_length=200)
    series: Optional[str] = Field(default=None, max_length=200)
    series_index: Optional[float] = Field(default=None, ge=0, le=200)
    unverified: bool = False
    service: Optional[str] = Field(default=None, max_length=100)
    source: Optional[str] = Field(default=None, max_length=200)
    status: Status = Status.to_watch
    rating: Optional[int] = Field(default=None, ge=1, le=3)
    created_at: Optional[str] = None  # importer may backdate

    @field_validator("name", "service", "source", "author", "series")
    @classmethod
    def strip_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = " ".join(v.split())
        return v or None


class ShowPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=300)
    show_type: Optional[ShowType] = None
    # service/source/author/series are clearable: distinguish "absent" from
    # explicit null via model_fields_set in the route
    author: Optional[str] = Field(default=None, max_length=200)
    series: Optional[str] = Field(default=None, max_length=200)
    series_index: Optional[float] = Field(default=None, ge=0, le=200)
    unverified: Optional[bool] = None  # clearing the triage flag = claiming the book
    service: Optional[str] = Field(default=None, max_length=100)
    source: Optional[str] = Field(default=None, max_length=200)
    status: Optional[Status] = None
    rating: Optional[int] = Field(default=None, ge=1, le=3)

    @field_validator("name", "service", "source", "author", "series")
    @classmethod
    def strip_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = " ".join(v.split())
        return v or None


class Show(BaseModel):
    show_id: str
    name: str
    show_type: ShowType
    medium: Medium = Medium.show
    # book-only fields
    author: Optional[str] = None
    series: Optional[str] = None
    series_index: Optional[float] = None
    unverified: bool = False  # imported from the shared account, ownership unconfirmed
    service: Optional[str] = None
    source: Optional[str] = None
    status: Status
    rating: Optional[int] = None
    created_at: str
    updated_at: str
    status_changed_at: str
    rated_at: Optional[str] = None
    # Set by Discovery runs; while present the card pins to the top of the
    # queue with a NEW badge. Cleared by the next full re-score of its medium.
    discovered_at: Optional[str] = None
    # LLM taste-engine outputs — persisted on the item (unlike the computed
    # stats fields below, so they MUST survive patch_show's item rebuild)
    llm_score: Optional[int] = None
    llm_reason: Optional[str] = None
    scored_at: Optional[str] = None
    profile_version: Optional[str] = None
    # computed at read time, never stored
    predicted_score: Optional[float] = None
    score_breakdown: Optional[dict] = None


class BulkCreate(BaseModel):
    shows: list[ShowCreate] = Field(max_length=100)


class TokenCreate(BaseModel):
    label: str = Field(min_length=1, max_length=100)
