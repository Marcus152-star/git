from __future__ import annotations

import re

from .models import InquiryAssessment, ParsedEmail


ALWAYS_NON_INQUIRY_SENDERS = {
    "request@medicalexpo.com",
    "no-reply@runcloud.io",
    "bella.ni@genfollower.com",
    "marcus.chen@genfollower.com",
    "vimeo@vimeo.com",
    "ads-noreply@google.com",
    "analytics-noreply@google.com",
    "noreply@tm.openai.com",
    "mail-cn@y.made-in-china.com",
}

TRUSTED_INQUIRY_SENDERS = {
    "no-reply@notifications.tidio.com",
}

INQUIRY_INTENT_TERMS = (
    "quotation",
    "quote",
    "pricing",
    "price",
    "catalog",
    "catalogue",
    "sample",
    "purchase",
    "buy",
    "order",
    "distributor",
    "interested in",
    "request for",
    "cotação",
    "cotacao",
    "amostra",
    "amostras",
    "interesse",
    "报价",
    "询价",
    "样品",
    "采购",
)

PRODUCT_TERMS = (
    "pipette tips",
    "puntas de pipeta",
    "pointes de pipette",
    "pipettenspitzen",
    "pcr tips",
    "puntas de pipeta para pcr",
    "pointes de pipette pour pcr",
    "pcr-pipettenspitzen",
    "pcr tubes",
    "tubos de pcr",
    "tubes pcr",
    "pcr-röhrchen",
    "microcentrifuge tubes",
    "tubos de microcentrífuga",
    "tubes de microcentrifugation",
    "mikrozentrifugenröhrchen",
    "centrifuge tubes",
    "tubos de centrífuga",
    "tubes de centrifugation",
    "zentrifugenröhrchen",
    "tubes",
    "tubos",
    "röhrchen",
    "cryogenic tubes",
    "crioviales",
    "cryotubes",
    "kryoröhrchen",
    "cryogenic boxes",
    "cajas criogénicas",
    "boîtes cryogéniques",
    "kryoboxen",
    "petri dishes",
    "placas de petri",
    "boîtes de petri",
    "petrischalen",
    "cell scraper",
    "raspador celular",
    "grattoir cellulaire",
    "zellschaber",
    "cell lifter",
    "espátula para células",
    "spatule cellulaire",
    "zellheber",
    "cell spreader",
    "espátula de siembra",
    "étaleur cellulaire",
    "zellspatel",
    "cell culture flasks",
    "frascos de cultivo celular",
    "flacons de culture cellulaire",
    "zellkulturflaschen",
    "syringe filters",
    "filtros de jeringa",
    "filtres pour seringue",
    "spritzenfilter",
    "sealing mat",
    "tapete de sellado para microplacas",
    "tapis de scellement pour microplaques",
    "verschlussmatte für mikrotiterplatten",
    "reagent reservoirs",
    "reservorios de reactivos",
    "réservoirs à réactifs",
    "reagenzreservoirs",
    "tip combs",
    "peines de puntas",
    "peignes à embouts",
    "spitzenkämme",
    "racks",
    "gradillas",
    "portoirs",
    "gestelle",
    "sample bottles",
    "frascos para muestras",
    "flacons pour échantillons",
    "probenflaschen",
    "serum bottles",
    "frascos para suero",
    "flacons pour sérum",
    "serumflaschen",
    "liquid handling",
    "manipulación de líquidos",
    "manipulation de liquides",
    "blu-ray gel cutting apparatus",
    "transiluminador de luz azul para corte de geles",
    "transilluminateur à lumière bleue pour découpe de gels",
    "blaulicht-transilluminator zur gelexzision",
    "thermostatic box",
    "cámara termostatizada",
    "enceinte thermostatée",
    "thermostatschrank",
    "dry bath incubator",
    "incubador de baño seco",
    "incubateur à bain sec",
    "trockenblock-inkubator",
    "centrifuge",
    "centrífuga",
    "centrifugeuse",
    "zentrifuge",
    "vortex mixer",
    "agitador vórtex",
    "agitateur vortex",
    "vortexmischer",
    "heat sealer",
    "termoselladora de microplacas",
    "thermoscelleuse de microplaques",
    "mikroplatten-heißsiegelgerät",
    "spin column",
    "columna de centrifugación",
    "colonne de centrifugation",
    "zentrifugationssäule",
    "pasteur pipette",
    "pipeta pasteur",
    "pipette pasteur",
    "pasteurpipette",
    "elisa plate",
    "placa elisa",
    "plaque elisa",
    "elisa-platte",
    "serological pipette",
    "pipeta serológica",
    "pipette sérologique",
    "serologische pipette",
    "lab accessories",
    "accesorios de laboratorio",
    "accessoires de laboratoire",
    "laborzubehör",
)

NON_INQUIRY_TERMS = (
    "delivery status notification",
    "mail delivery failed",
    "undeliverable",
    "automatic reply",
    "auto reply",
    "out of office",
    "unsubscribe",
    "newsletter",
    "verify your email",
    "password reset",
    "job application",
    "resume attached",
)

PHISHING_TERMS = ("view excel",)

INDUSTRY_ONLY_TERMS = (
    "vendor program",
    "vendor questionnaire",
    "vendor selection",
    "registered vendor",
    "supplier registration",
    "expression of interest",
    "healthcare project",
    "medical project",
    "business opportunity",
    "partnership opportunity",
)


def _normalize_text(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", " ", value.casefold(), flags=re.UNICODE).strip()


def _term_hits(terms: tuple[str, ...], normalized_text: str) -> list[str]:
    return sorted({term for term in terms if _normalize_text(term) in normalized_text})


def assess_inquiry(
    parsed: ParsedEmail,
    blacklisted_senders: set[str] | frozenset[str] | None = None,
) -> InquiryAssessment:
    sender = parsed.envelope_from.strip().lower()
    blacklist = {value.strip().lower() for value in (blacklisted_senders or set())}

    if sender in ALWAYS_NON_INQUIRY_SENDERS:
        return InquiryAssessment(
            status="false",
            confidence=1.0,
            reasons=[f"fixed non-inquiry sender: {sender}"],
        )
    if sender in blacklist:
        return InquiryAssessment(
            status="false",
            confidence=1.0,
            reasons=[f"sender is on automatic blacklist: {sender}"],
        )

    normalized_text = _normalize_text(f"{parsed.subject}\n{parsed.text_body}")
    phishing_hits = _term_hits(PHISHING_TERMS, normalized_text)
    if phishing_hits:
        return InquiryAssessment(
            status="false",
            confidence=0.99,
            reasons=[f"phishing marker: {term}" for term in phishing_hits],
        )

    inquiry_hits = _term_hits(INQUIRY_INTENT_TERMS, normalized_text)
    product_hits = _term_hits(PRODUCT_TERMS, normalized_text)
    negative_hits = _term_hits(NON_INQUIRY_TERMS, normalized_text)
    industry_hits = _term_hits(INDUSTRY_ONLY_TERMS, normalized_text)

    if sender in TRUSTED_INQUIRY_SENDERS:
        external_customer_emails = [
            email for email in parsed.customer_email_candidates if email.strip().lower() != sender
        ]
        if external_customer_emails:
            return InquiryAssessment(
                status="true",
                confidence=0.95,
                reasons=["trusted Tidio inquiry notification"],
            )
        return InquiryAssessment(
            status="review",
            confidence=0.7,
            reasons=["Tidio notification has no external customer email"],
        )

    if negative_hits and not inquiry_hits and not product_hits:
        return InquiryAssessment(
            status="false",
            confidence=0.97,
            reasons=[f"non-inquiry marker: {term}" for term in negative_hits],
        )

    wordpress_template = bool(
        re.search(r"(?im)^\s*from\s*:", parsed.text_body)
        and re.search(r"(?im)^\s*message body\s*:", parsed.text_body)
    )
    if parsed.customer_email_candidates and (inquiry_hits or product_hits) and wordpress_template:
        return InquiryAssessment(
            status="true",
            confidence=0.96,
            reasons=[
                "recognized website inquiry template",
                *[f"inquiry intent: {term}" for term in inquiry_hits],
                *[f"laboratory product: {term}" for term in product_hits],
            ],
        )
    if parsed.customer_email_candidates and inquiry_hits and product_hits:
        return InquiryAssessment(
            status="true",
            confidence=0.93,
            reasons=[
                *[f"inquiry intent: {term}" for term in inquiry_hits],
                *[f"laboratory product: {term}" for term in product_hits],
            ],
        )
    if parsed.customer_email_candidates and len(inquiry_hits) >= 2:
        return InquiryAssessment(
            status="true",
            confidence=0.9,
            reasons=[f"inquiry intent: {term}" for term in inquiry_hits],
        )
    if industry_hits and not product_hits:
        return InquiryAssessment(
            status="review",
            confidence=0.55,
            reasons=[
                "industry or vendor language found without a specific laboratory product request",
                *[f"industry-only term: {term}" for term in industry_hits],
            ],
        )
    if inquiry_hits or product_hits:
        return InquiryAssessment(
            status="review",
            confidence=0.6,
            reasons=["inquiry evidence found but sender identity, product, or intent is incomplete"],
        )
    return InquiryAssessment(
        status="review",
        confidence=0.3,
        reasons=["no reliable inquiry or non-inquiry markers"],
    )
