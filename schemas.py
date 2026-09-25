"""
Stage 1: the /triage request and response shapes, defined in code.

TriageRequest is what FastAPI validates the incoming body against -- a bad
request never reaches the model. TriageResponse is what we validate the
model's answer against before it goes anywhere near the caller. Same
pattern, both directions: untrusted data goes through a schema before
anything downstream trusts it.
"""
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class Category(str, Enum):
    billing = "billing"
    bug = "bug"
    feature = "feature"
    other = "other"


class Urgency(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"


class TriageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be blank")
        return v


class TriageResponse(BaseModel):
    category: Category
    urgency: Urgency
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason: str = Field(..., min_length=1, max_length=300)
