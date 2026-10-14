from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


InquiryStatus = Literal["true", "false", "review"]
MatchStatus = Literal["matched", "ambiguous", "not_found"]
RouteType = Literal[
    "existing_customer",
    "exclusive_market",
    "standard_round_robin",
    "manual_review",
    "ignored",
    "duplicate",
]


@dataclass(frozen=True)
class ParsedEmail:
    message_key: str
    subject: str
    envelope_from: str
    reply_to: str
    customer_email_candidates: list[str]
    customer_name: str
    company_name: str
    country: str
    country_confidence: Literal["high", "low", "none"]
    text_body: str
    source_path: str


@dataclass(frozen=True)
class InquiryAssessment:
    status: InquiryStatus
    confidence: float
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CustomerRecord:
    row_number: int
    customer_id: str
    company_name: str
    country: str
    owner: str
    emails: tuple[str, ...]
    domains: tuple[str, ...]
    source_path: str = ""


@dataclass(frozen=True)
class CustomerMatch:
    status: MatchStatus
    reason: str
    matched_email: str = ""
    owner: str = ""
    customer_ids: tuple[str, ...] = ()
    company_names: tuple[str, ...] = ()
    countries: tuple[str, ...] = ()


@dataclass(frozen=True)
class RouteDecision:
    message_key: str
    route_type: RouteType
    salesperson: str
    recipient_email: str
    inquiry_status: InquiryStatus
    inquiry_confidence: float
    customer_match_status: MatchStatus
    customer_match_reason: str
    extracted_customer_emails: list[str]
    country: str
    country_confidence: str
    exclusive_rule: str
    standard_inquiry_number: int | None
    cycle_number: int | None
    cycle_position: int | None
    advances_standard_counter: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

