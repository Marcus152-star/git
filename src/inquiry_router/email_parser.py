from __future__ import annotations

import hashlib
import html
import re
from email import policy
from email.message import Message
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr
from html.parser import HTMLParser
from pathlib import Path

from .config import AppConfig
from .customers import EMAIL_RE, email_domain, normalize_email
from .country import extract_country
from .models import ParsedEmail


FIELD_EMAIL_PATTERNS = (
    re.compile(
        r"(?im)^\s*(?:from|e-?mail|email address|your email|contact email)\s*:\s*"
        r"(?:(?P<name>[^<\r\n]+?)\s*)?<(?P<email>[^>\s]+@[^>\s]+)>\s*$"
    ),
    re.compile(
        r"(?im)^\s*(?:e-?mail|email address|your email|contact email)\s*:\s*"
        r"(?P<email>[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})\s*$"
    ),
)

COMPANY_PATTERN = re.compile(
    r"(?im)^\s*(?:company|company name|organization|organisation|empresa|公司(?:名称)?)\s*:\s*(?P<value>.+?)\s*$"
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        return "\n".join(self.parts)


def _html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    return html.unescape(parser.text())


def _message_text(message: Message) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        try:
            value = part.get_content()
        except (LookupError, UnicodeError):
            payload = part.get_payload(decode=True) or b""
            value = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if content_type == "text/plain":
            plain_parts.append(str(value))
        else:
            html_parts.append(_html_to_text(str(value)))
    return "\n".join(plain_parts or html_parts).strip()


def _is_internal(email: str, config: AppConfig) -> bool:
    normalized = normalize_email(email)
    return normalized in config.internal_email_addresses or email_domain(normalized) in config.internal_domains


def _header_emails(message: Message, header: str) -> list[str]:
    values = message.get_all(header, [])
    return [normalize_email(address) for _, address in getaddresses(values) if address]


def _body_identity(body: str) -> tuple[str, list[str]]:
    name = ""
    prioritized: list[str] = []
    for pattern in FIELD_EMAIL_PATTERNS:
        for match in pattern.finditer(body):
            email = normalize_email(match.group("email"))
            if email and email not in prioritized:
                prioritized.append(email)
            candidate_name = (match.groupdict().get("name") or "").strip()
            if candidate_name and not name:
                name = candidate_name
    return name, prioritized


def _message_key(message: Message, raw: bytes) -> str:
    message_id = str(message.get("Message-ID") or "").strip()
    if message_id:
        return f"message-id:{message_id}"
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def parse_eml(path: str | Path, config: AppConfig) -> ParsedEmail:
    source = Path(path)
    raw = source.read_bytes()
    message = BytesParser(policy=policy.default).parsebytes(raw)
    body = _message_text(message)

    envelope_name, envelope_address = parseaddr(str(message.get("From") or ""))
    envelope_address = normalize_email(envelope_address)
    reply_to_addresses = _header_emails(message, "Reply-To")
    reply_to = reply_to_addresses[0] if reply_to_addresses else ""
    body_name, body_prioritized = _body_identity(body)

    candidates: list[str] = []
    for email in [*reply_to_addresses, *body_prioritized, envelope_address, *EMAIL_RE.findall(body)]:
        normalized = normalize_email(email)
        if not normalized or _is_internal(normalized, config) or normalized in candidates:
            continue
        candidates.append(normalized)

    company_match = COMPANY_PATTERN.search(body)
    company_name = company_match.group("value").strip() if company_match else ""
    country, country_confidence = extract_country(body)

    return ParsedEmail(
        message_key=_message_key(message, raw),
        subject=str(message.get("Subject") or "").strip(),
        envelope_from=envelope_address,
        reply_to=reply_to,
        customer_email_candidates=candidates,
        customer_name=body_name or envelope_name.strip(),
        company_name=company_name,
        country=country,
        country_confidence=country_confidence,
        text_body=body,
        source_path=str(source.resolve()),
    )

