from __future__ import annotations

from dataclasses import dataclass

from .config import AppConfig
from .country import canonical_country
from .models import CustomerMatch, InquiryAssessment, ParsedEmail, RouteDecision


EARLY_SEQUENCE = ("Chloe", "Nicole", "Nicole", "Ella", "Ella")
STEADY_SEQUENCE = ("Chloe", "Nicole", "Nicole", "Nicole", "Ella", "Ella")
EARLY_CYCLES = 5
EARLY_TOTAL = len(EARLY_SEQUENCE) * EARLY_CYCLES

EXCLUSIVE_MARKETS = {
    "Russia": "Chloe",
    "Indonesia": "Chloe",
    "Israel": "Nicole",
    "Hungary": "Nicole",
    "Ukraine": "Chloe",
    "Colombia": "Chloe",
    "Turkey": "Chloe",
    "Slovenia": "Chloe",
    "Iran": "Nicole",
}

PE_TIP_TERMS = (
    "pe tip",
    "pe tips",
    "pe pipette tip",
    "pe pipette tips",
    "polyethylene tip",
    "polyethylene tips",
    "polyethylene pipette tip",
    "polyethylene pipette tips",
    "pe吸头",
    "聚乙烯吸头",
)


@dataclass(frozen=True)
class StandardAssignment:
    salesperson: str
    inquiry_number: int
    cycle_number: int
    cycle_position: int


def standard_assignment(completed_standard_count: int) -> StandardAssignment:
    if completed_standard_count < 0:
        raise ValueError("completed_standard_count cannot be negative")
    if completed_standard_count < EARLY_TOTAL:
        sequence = EARLY_SEQUENCE
        offset = completed_standard_count
        cycle_number = offset // len(sequence) + 1
        position = offset % len(sequence)
    else:
        sequence = STEADY_SEQUENCE
        offset = completed_standard_count - EARLY_TOTAL
        cycle_number = EARLY_CYCLES + 1 + offset // len(sequence)
        position = offset % len(sequence)
    return StandardAssignment(
        salesperson=sequence[position],
        inquiry_number=completed_standard_count + 1,
        cycle_number=cycle_number,
        cycle_position=position + 1,
    )


def exclusive_assignment(parsed: ParsedEmail) -> tuple[str, str]:
    if parsed.country_confidence != "high":
        return "", ""
    country = canonical_country(parsed.country)
    if country == "United Arab Emirates":
        text = f"{parsed.subject}\n{parsed.text_body}".casefold()
        if any(term.casefold() in text for term in PE_TIP_TERMS):
            return "Nicole", "United Arab Emirates + PE pipette tips"
        return "", ""
    salesperson = EXCLUSIVE_MARKETS.get(country, "")
    return (salesperson, country) if salesperson else ("", "")


def make_decision(
    parsed: ParsedEmail,
    assessment: InquiryAssessment,
    match: CustomerMatch,
    completed_standard_count: int,
    config: AppConfig,
) -> RouteDecision:
    common = {
        "message_key": parsed.message_key,
        "inquiry_status": assessment.status,
        "inquiry_confidence": assessment.confidence,
        "customer_match_status": match.status,
        "customer_match_reason": match.reason,
        "extracted_customer_emails": parsed.customer_email_candidates,
        "country": parsed.country,
        "country_confidence": parsed.country_confidence,
    }

    if assessment.status == "false":
        return RouteDecision(
            **common,
            route_type="ignored",
            salesperson="",
            recipient_email="",
            exclusive_rule="",
            standard_inquiry_number=None,
            cycle_number=None,
            cycle_position=None,
            advances_standard_counter=False,
            reasons=assessment.reasons,
        )
    if assessment.status != "true":
        return RouteDecision(
            **common,
            route_type="manual_review",
            salesperson="",
            recipient_email="",
            exclusive_rule="",
            standard_inquiry_number=None,
            cycle_number=None,
            cycle_position=None,
            advances_standard_counter=False,
            reasons=assessment.reasons,
        )
    if match.status == "ambiguous":
        return RouteDecision(
            **common,
            route_type="manual_review",
            salesperson="",
            recipient_email="",
            exclusive_rule="",
            standard_inquiry_number=None,
            cycle_number=None,
            cycle_position=None,
            advances_standard_counter=False,
            reasons=[match.reason],
        )
    if match.status == "matched":
        return RouteDecision(
            **common,
            route_type="existing_customer",
            salesperson=match.owner,
            recipient_email=config.sales_email_addresses.get(match.owner, ""),
            exclusive_rule="",
            standard_inquiry_number=None,
            cycle_number=None,
            cycle_position=None,
            advances_standard_counter=False,
            reasons=[match.reason],
        )

    possible_exclusive_country = canonical_country(parsed.country)
    if parsed.country_confidence == "low" and possible_exclusive_country in {
        *EXCLUSIVE_MARKETS,
        "United Arab Emirates",
    }:
        return RouteDecision(
            **common,
            route_type="manual_review",
            salesperson="",
            recipient_email="",
            exclusive_rule="",
            standard_inquiry_number=None,
            cycle_number=None,
            cycle_position=None,
            advances_standard_counter=False,
            reasons=[f"possible exclusive market needs country confirmation: {possible_exclusive_country}"],
        )

    salesperson, exclusive_rule = exclusive_assignment(parsed)
    if salesperson:
        return RouteDecision(
            **common,
            route_type="exclusive_market",
            salesperson=salesperson,
            recipient_email=config.sales_email_addresses.get(salesperson, ""),
            exclusive_rule=exclusive_rule,
            standard_inquiry_number=None,
            cycle_number=None,
            cycle_position=None,
            advances_standard_counter=False,
            reasons=[f"exclusive market: {exclusive_rule}"],
        )

    assignment = standard_assignment(completed_standard_count)
    return RouteDecision(
        **common,
        route_type="standard_round_robin",
        salesperson=assignment.salesperson,
        recipient_email=config.sales_email_addresses.get(assignment.salesperson, ""),
        exclusive_rule="",
        standard_inquiry_number=assignment.inquiry_number,
        cycle_number=assignment.cycle_number,
        cycle_position=assignment.cycle_position,
        advances_standard_counter=True,
        reasons=["new inquiry with no CRM customer match"],
    )

