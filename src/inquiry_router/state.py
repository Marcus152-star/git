from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .config import AppConfig
from .models import CustomerMatch, InquiryAssessment, ParsedEmail, RouteDecision
from .router import make_decision


AUTO_BLACKLIST_THRESHOLD = 3


class StateStore:
    def __init__(self, path: str | Path, initial_standard_count: int = 0) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_messages (
                message_key TEXT PRIMARY KEY,
                route_type TEXT NOT NULL,
                salesperson TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sender_reputation (
                sender_email TEXT PRIMARY KEY,
                non_inquiry_count INTEGER NOT NULL DEFAULT 0,
                blacklisted INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS mailbox_checkpoints (
                account TEXT NOT NULL,
                folder TEXT NOT NULL,
                uid_validity TEXT NOT NULL,
                last_uid INTEGER NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(account, folder)
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS mailbox_shadow_state (
                account TEXT NOT NULL,
                folder TEXT NOT NULL,
                standard_count INTEGER NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(account, folder)
            )
            """
        )
        self.connection.execute(
            "INSERT OR IGNORE INTO app_state(key, value) VALUES('standard_inquiry_count', ?)",
            (initial_standard_count,),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "StateStore":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def get_standard_count(self) -> int:
        row = self.connection.execute(
            "SELECT value FROM app_state WHERE key='standard_inquiry_count'"
        ).fetchone()
        return int(row[0])

    def set_standard_count(self, value: int) -> None:
        if value < 0:
            raise ValueError("Standard inquiry count cannot be negative")
        self.connection.execute(
            "UPDATE app_state SET value=? WHERE key='standard_inquiry_count'",
            (value,),
        )
        self.connection.commit()

    def get_blacklisted_senders(self) -> set[str]:
        rows = self.connection.execute(
            "SELECT sender_email FROM sender_reputation WHERE blacklisted=1"
        ).fetchall()
        return {str(row[0]).lower() for row in rows}

    def get_sender_non_inquiry_count(self, sender_email: str) -> int:
        row = self.connection.execute(
            "SELECT non_inquiry_count FROM sender_reputation WHERE sender_email=?",
            (sender_email.strip().lower(),),
        ).fetchone()
        return int(row[0]) if row else 0

    def get_mailbox_checkpoint(self, account: str, folder: str) -> tuple[str, int] | None:
        row = self.connection.execute(
            """
            SELECT uid_validity, last_uid
            FROM mailbox_checkpoints
            WHERE account=? AND folder=?
            """,
            (account.strip().lower(), folder),
        ).fetchone()
        return (str(row[0]), int(row[1])) if row else None

    def set_mailbox_checkpoint(
        self,
        account: str,
        folder: str,
        uid_validity: str,
        last_uid: int,
    ) -> None:
        if last_uid < 0:
            raise ValueError("Mailbox UID cannot be negative")
        self.connection.execute(
            """
            INSERT INTO mailbox_checkpoints(account, folder, uid_validity, last_uid)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(account, folder) DO UPDATE SET
                uid_validity=excluded.uid_validity,
                last_uid=excluded.last_uid,
                updated_at=CURRENT_TIMESTAMP
            """,
            (account.strip().lower(), folder, uid_validity, last_uid),
        )
        self.connection.commit()

    def get_mailbox_shadow_count(self, account: str, folder: str) -> int | None:
        row = self.connection.execute(
            """
            SELECT standard_count
            FROM mailbox_shadow_state
            WHERE account=? AND folder=?
            """,
            (account.strip().lower(), folder),
        ).fetchone()
        return int(row[0]) if row else None

    def set_mailbox_shadow_count(self, account: str, folder: str, count: int) -> None:
        if count < 0:
            raise ValueError("Shadow standard inquiry count cannot be negative")
        self.connection.execute(
            """
            INSERT INTO mailbox_shadow_state(account, folder, standard_count)
            VALUES(?, ?, ?)
            ON CONFLICT(account, folder) DO UPDATE SET
                standard_count=excluded.standard_count,
                updated_at=CURRENT_TIMESTAMP
            """,
            (account.strip().lower(), folder, count),
        )
        self.connection.commit()

    @staticmethod
    def _reputation_sender(parsed: ParsedEmail, config: AppConfig) -> str:
        sender = parsed.envelope_from.strip().lower()
        if not sender or sender in config.internal_email_addresses:
            return ""
        domain = sender.rsplit("@", 1)[1] if "@" in sender else ""
        if domain in config.internal_domains:
            return ""
        return sender

    def preview(
        self,
        parsed: ParsedEmail,
        assessment: InquiryAssessment,
        match: CustomerMatch,
        config: AppConfig,
    ) -> RouteDecision:
        return make_decision(parsed, assessment, match, self.get_standard_count(), config)

    def commit(
        self,
        parsed: ParsedEmail,
        assessment: InquiryAssessment,
        match: CustomerMatch,
        config: AppConfig,
    ) -> RouteDecision:
        cursor = self.connection.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            existing = cursor.execute(
                "SELECT decision_json FROM processed_messages WHERE message_key=?",
                (parsed.message_key,),
            ).fetchone()
            if existing:
                prior = json.loads(existing[0])
                prior["route_type"] = "duplicate"
                prior["advances_standard_counter"] = False
                prior["reasons"] = ["message key already processed"]
                self.connection.rollback()
                return RouteDecision(**prior)

            count = int(
                cursor.execute(
                    "SELECT value FROM app_state WHERE key='standard_inquiry_count'"
                ).fetchone()[0]
            )
            decision = make_decision(parsed, assessment, match, count, config)
            cursor.execute(
                """
                INSERT INTO processed_messages(message_key, route_type, salesperson, decision_json)
                VALUES(?, ?, ?, ?)
                """,
                (
                    decision.message_key,
                    decision.route_type,
                    decision.salesperson,
                    json.dumps(decision.to_dict(), ensure_ascii=False),
                ),
            )
            if decision.advances_standard_counter:
                cursor.execute(
                    "UPDATE app_state SET value=value+1 WHERE key='standard_inquiry_count'"
                )
            reputation_sender = self._reputation_sender(parsed, config)
            if assessment.status == "false" and reputation_sender:
                cursor.execute(
                    """
                    INSERT INTO sender_reputation(sender_email, non_inquiry_count, blacklisted)
                    VALUES(?, 1, 0)
                    ON CONFLICT(sender_email) DO UPDATE SET
                        non_inquiry_count=non_inquiry_count+1,
                        blacklisted=CASE
                            WHEN non_inquiry_count+1>=? THEN 1
                            ELSE blacklisted
                        END
                    """,
                    (reputation_sender, AUTO_BLACKLIST_THRESHOLD),
                )
            self.connection.commit()
            return decision
        except Exception:
            self.connection.rollback()
            raise

