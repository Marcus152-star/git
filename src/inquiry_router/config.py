from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    internal_domains: tuple[str, ...] = ("genfollower.com",)
    internal_email_addresses: tuple[str, ...] = (
        "genfollower@genfollower.com",
        "marcus.chen@genfollower.com",
    )
    sales_email_addresses: dict[str, str] = field(
        default_factory=lambda: {"Chloe": "", "Nicole": "", "Ella": ""}
    )
    initial_standard_inquiry_count: int = 0
    zoho_email_address: str = "marcus.chen@genfollower.com"
    zoho_imap_host: str = "imappro.zoho.com"
    zoho_imap_port: int = 993
    zoho_smtp_host: str = "smtppro.zoho.com"
    zoho_smtp_port: int = 465
    zoho_folder: str = "INBOX"


def load_config(path: str | Path | None) -> AppConfig:
    if path is None:
        return AppConfig()

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    count = int(raw.get("initial_standard_inquiry_count", 0))
    if count < 0:
        raise ValueError("initial_standard_inquiry_count cannot be negative")

    return AppConfig(
        internal_domains=tuple(
            str(x).strip().lower()
            for x in raw.get("internal_domains", ["genfollower.com"])
            if str(x).strip()
        ),
        internal_email_addresses=tuple(
            str(x).strip().lower()
            for x in raw.get("internal_email_addresses", [])
            if str(x).strip()
        ),
        sales_email_addresses={
            str(name).strip(): str(email).strip().lower()
            for name, email in raw.get("sales_email_addresses", {}).items()
        },
        initial_standard_inquiry_count=count,
        zoho_email_address=str(raw.get("zoho_email_address", "marcus.chen@genfollower.com")).strip().lower(),
        zoho_imap_host=str(raw.get("zoho_imap_host", "imappro.zoho.com")).strip(),
        zoho_imap_port=int(raw.get("zoho_imap_port", 993)),
        zoho_smtp_host=str(raw.get("zoho_smtp_host", "smtppro.zoho.com")).strip(),
        zoho_smtp_port=int(raw.get("zoho_smtp_port", 465)),
        zoho_folder=str(raw.get("zoho_folder", "INBOX")).strip() or "INBOX",
    )

