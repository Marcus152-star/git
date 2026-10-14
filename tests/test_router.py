from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from inquiry_router.classifier import assess_inquiry
from inquiry_router.config import AppConfig
from inquiry_router.credential_store import WindowsCredentialStore
from inquiry_router.customers import CustomerIndex
from inquiry_router.email_parser import parse_eml
from inquiry_router.gui import email_overview, format_customer_match, format_customer_summary
from inquiry_router.models import CustomerMatch, CustomerRecord, InquiryAssessment, ParsedEmail
from inquiry_router.router import make_decision, standard_assignment
from inquiry_router.state import StateStore
from inquiry_router.zoho_mail import ZohoMailClient


def parsed_email(
    *,
    key: str = "test:1",
    country: str = "",
    confidence: str = "none",
    body: str = "Please send a quotation and samples.",
    subject: str = "New inquiry",
    envelope_from: str = "genfollower@genfollower.com",
    customer_emails: list[str] | None = None,
) -> ParsedEmail:
    return ParsedEmail(
        message_key=key,
        subject=subject,
        envelope_from=envelope_from,
        reply_to="",
        customer_email_candidates=(
            ["buyer@example-company.test"] if customer_emails is None else customer_emails
        ),
        customer_name="Buyer",
        company_name="",
        country=country,
        country_confidence=confidence,
        text_body=body,
        source_path="test.eml",
    )


TRUE_INQUIRY = InquiryAssessment(status="true", confidence=0.99, reasons=["test"])
NO_MATCH = CustomerMatch(status="not_found", reason="test no match")

CUSTOMER_HEADERS = (
    "客户编号",
    "公司名称",
    "国家",
    "公司网址",
    "公司邮箱",
    "联系人工作邮箱",
    "联系人个人邮箱",
    "当前跟进人",
)


def write_customer_workbook(path: Path, rows: list[tuple]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(CUSTOMER_HEADERS)
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    workbook.close()


class RoundRobinTests(unittest.TestCase):
    def test_first_five_cycles_use_1_2_2(self) -> None:
        expected = ["Chloe", "Nicole", "Nicole", "Ella", "Ella"] * 5
        self.assertEqual([standard_assignment(i).salesperson for i in range(25)], expected)
        self.assertEqual(standard_assignment(24).cycle_number, 5)

    def test_sixth_cycle_and_later_use_1_3_2(self) -> None:
        expected = ["Chloe", "Nicole", "Nicole", "Nicole", "Ella", "Ella"]
        self.assertEqual([standard_assignment(i).salesperson for i in range(25, 31)], expected)
        self.assertEqual(standard_assignment(25).cycle_number, 6)
        self.assertEqual(standard_assignment(30).cycle_position, 6)


class RoutingPriorityTests(unittest.TestCase):
    def test_existing_customer_overrides_exclusive_market(self) -> None:
        match = CustomerMatch(status="matched", reason="exact email", owner="Ella")
        decision = make_decision(
            parsed_email(country="Russia", confidence="high"),
            TRUE_INQUIRY,
            match,
            0,
            AppConfig(),
        )
        self.assertEqual(decision.route_type, "existing_customer")
        self.assertEqual(decision.salesperson, "Ella")
        self.assertFalse(decision.advances_standard_counter)

    def test_exclusive_market_does_not_advance_counter(self) -> None:
        decision = make_decision(
            parsed_email(country="Russia", confidence="high"),
            TRUE_INQUIRY,
            NO_MATCH,
            7,
            AppConfig(),
        )
        self.assertEqual(decision.route_type, "exclusive_market")
        self.assertEqual(decision.salesperson, "Chloe")
        self.assertFalse(decision.advances_standard_counter)

    def test_uae_only_exclusive_for_pe_tips(self) -> None:
        pe = make_decision(
            parsed_email(
                country="United Arab Emirates",
                confidence="high",
                body="Country: United Arab Emirates\nPlease quote PE pipette tips.",
            ),
            TRUE_INQUIRY,
            NO_MATCH,
            0,
            AppConfig(),
        )
        other = make_decision(
            parsed_email(
                country="United Arab Emirates",
                confidence="high",
                body="Country: United Arab Emirates\nPlease quote centrifuge tubes.",
            ),
            TRUE_INQUIRY,
            NO_MATCH,
            0,
            AppConfig(),
        )
        self.assertEqual(pe.route_type, "exclusive_market")
        self.assertEqual(pe.salesperson, "Nicole")
        self.assertEqual(other.route_type, "standard_round_robin")

    def test_low_confidence_exclusive_country_requires_manual_review(self) -> None:
        decision = make_decision(
            parsed_email(country="Russia", confidence="low"),
            TRUE_INQUIRY,
            NO_MATCH,
            0,
            AppConfig(),
        )
        self.assertEqual(decision.route_type, "manual_review")
        self.assertFalse(decision.advances_standard_counter)


class CustomerMatchTests(unittest.TestCase):
    def test_exact_email_returns_current_owner(self) -> None:
        record = CustomerRecord(
            row_number=2,
            customer_id="C-1",
            company_name="Example Co",
            country="Brazil",
            owner="Nicole",
            emails=("buyer@example.com",),
            domains=("example.com",),
        )
        index = CustomerIndex(
            records=[record],
            by_email={"buyer@example.com": [record]},
            by_domain={"example.com": [record]},
            by_company={"exampleco": [record]},
        )
        match = index.match(["buyer@example.com"])
        self.assertEqual(match.status, "matched")
        self.assertEqual(match.owner, "Nicole")

    def test_multiple_workbooks_merge_and_show_plain_chinese_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "customers-1.xlsx"
            second = Path(temp_dir) / "customers-2.xlsx"
            write_customer_workbook(
                first,
                [("C-1", "Laboratorios Geminis, C.A.", "Venezuela", "", "", "rmendez@labgeminis.com", "", "Ella")],
            )
            write_customer_workbook(
                second,
                [("C-2", "Second Laboratory", "Brazil", "", "", "buyer@second-lab.com", "", "Nicole")],
            )

            index = CustomerIndex.from_xlsx_files([first, second])
            match = index.match(["rmendez@labgeminis.com"])
            summary = index.summary()

        self.assertEqual(summary["source_file_count"], 2)
        self.assertEqual(summary["records"], 2)
        self.assertEqual(match.countries, ("Venezuela",))
        self.assertEqual(
            format_customer_match(match),
            "匹配状态：已匹配\n"
            "客户所属国家：Venezuela\n"
            "所属公司：Laboratorios Geminis, C.A.\n"
            "负责人：Ella",
        )
        self.assertNotIn("{", format_customer_summary(summary))
        self.assertIn("客户记录总数：2条", format_customer_summary(summary))

    def test_conflicting_owners_across_workbooks_are_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "customers-1.xlsx"
            second = Path(temp_dir) / "customers-2.xlsx"
            row = ("C-1", "Example Laboratory", "Venezuela", "", "", "buyer@example-lab.com", "", "Ella")
            conflict = ("C-1", "Example Laboratory", "Venezuela", "", "", "buyer@example-lab.com", "", "Nicole")
            write_customer_workbook(first, [row])
            write_customer_workbook(second, [conflict])

            match = CustomerIndex.from_xlsx_files([first, second]).match(["buyer@example-lab.com"])

        self.assertEqual(match.status, "ambiguous")
        self.assertEqual(match.owner, "")


class EmailParserTests(unittest.TestCase):
    def test_extracts_customer_from_wordpress_body(self) -> None:
        raw = b"""From: WordPress <genfollower@genfollower.com>\r
To: marcus.chen@genfollower.com\r
Subject: New Inquiry\r
Message-ID: <sample-1@example.test>\r
Content-Type: text/plain; charset=utf-8\r
\r
From: Ana Luiza Paiva <analuiza.paiva@funed.mg.gov.br>\r
Country: Brazil\r
Message Body:\r
Please send a quotation and samples.\r
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.eml"
            path.write_bytes(raw)
            parsed = parse_eml(path, AppConfig())
        self.assertEqual(parsed.envelope_from, "genfollower@genfollower.com")
        self.assertEqual(parsed.customer_email_candidates[0], "analuiza.paiva@funed.mg.gov.br")
        self.assertEqual(parsed.customer_name, "Ana Luiza Paiva")
        self.assertEqual(assess_inquiry(parsed).status, "true")

    def test_email_overview_reads_headers_without_routing(self) -> None:
        raw = b"""From: Buyer <buyer@example.com>\r
Date: Tue, 14 Oct 2026 09:30:00 +0800\r
Subject: Latest mailbox check\r
\r
Body is intentionally irrelevant.\r
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mail.eml"
            path.write_bytes(raw)
            overview = email_overview(path)
        self.assertEqual(overview["from"], "Buyer <buyer@example.com>")
        self.assertEqual(overview["subject"], "Latest mailbox check")


class InquiryClassifierTests(unittest.TestCase):
    def test_fixed_non_inquiry_senders_override_inquiry_words(self) -> None:
        senders = (
            "request@medicalexpo.com",
            "no-reply@runcloud.io",
            "bella.ni@genfollower.com",
            "marcus.chen@genfollower.com",
            "vimeo@vimeo.com",
            "ads-noreply@google.com",
            "analytics-noreply@google.com",
            "noreply@tm.openai.com",
            "mail-cn@y.made-in-china.com",
        )
        for sender in senders:
            with self.subTest(sender=sender):
                assessment = assess_inquiry(
                    parsed_email(
                        envelope_from=sender,
                        body="Please send a quotation for pipette tips.",
                    )
                )
                self.assertEqual(assessment.status, "false")

    def test_tidio_with_external_customer_email_is_true(self) -> None:
        assessment = assess_inquiry(
            parsed_email(
                envelope_from="no-reply@notifications.tidio.com",
                body="Bonjour, cet incubateur enregistre historique de la temperature?",
                customer_emails=["youssef.dinar@ammps.gov.ma"],
            )
        )
        self.assertEqual(assessment.status, "true")

    def test_view_excel_is_non_inquiry(self) -> None:
        assessment = assess_inquiry(
            parsed_email(
                envelope_from="info@bnh360.in",
                subject="Proforma invoice for quote",
                body="Please find attached Proforma invoice. View Excel",
            )
        )
        self.assertEqual(assessment.status, "false")

    def test_vendor_language_without_product_is_manual_review(self) -> None:
        assessment = assess_inquiry(
            parsed_email(
                envelope_from="sarah.alfalasi@dhccprocurement.com",
                body=(
                    "We invite your company to participate in our vendor program for upcoming "
                    "healthcare projects. Request the Vendor Questionnaire."
                ),
            )
        )
        self.assertEqual(assessment.status, "review")

    def test_multilingual_product_term_supports_real_inquiry(self) -> None:
        assessment = assess_inquiry(
            parsed_email(
                envelope_from="buyer@example.de",
                body="Please send a quote for PCR-Röhrchen.",
            )
        )
        self.assertEqual(assessment.status, "true")


class StateTests(unittest.TestCase):
    def test_exclusive_does_not_advance_and_duplicate_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "state.sqlite3"
            with StateStore(db, 0) as state:
                first = state.commit(
                    parsed_email(key="same", country="Russia", confidence="high"),
                    TRUE_INQUIRY,
                    NO_MATCH,
                    AppConfig(),
                )
                duplicate = state.commit(
                    parsed_email(key="same", country="Russia", confidence="high"),
                    TRUE_INQUIRY,
                    NO_MATCH,
                    AppConfig(),
                )
                self.assertEqual(first.route_type, "exclusive_market")
                self.assertEqual(duplicate.route_type, "duplicate")
                self.assertEqual(state.get_standard_count(), 0)

    def test_standard_route_advances_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "state.sqlite3"
            with StateStore(db, 0) as state:
                decision = state.commit(
                    parsed_email(key="standard"), TRUE_INQUIRY, NO_MATCH, AppConfig()
                )
                self.assertEqual(decision.salesperson, "Chloe")
                self.assertEqual(state.get_standard_count(), 1)

    def test_sender_is_blacklisted_after_three_committed_non_inquiries(self) -> None:
        sender = "spam@example.test"
        false_assessment = InquiryAssessment(status="false", confidence=0.99, reasons=["test"])
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "state.sqlite3"
            with StateStore(db, 0) as state:
                for number in range(3):
                    state.commit(
                        parsed_email(key=f"spam:{number}", envelope_from=sender),
                        false_assessment,
                        NO_MATCH,
                        AppConfig(),
                    )
                self.assertEqual(state.get_sender_non_inquiry_count(sender), 3)
                self.assertIn(sender, state.get_blacklisted_senders())
                later = assess_inquiry(
                    parsed_email(
                        key="spam:later",
                        envelope_from=sender,
                        body="Please send a quote for pipette tips.",
                    ),
                    state.get_blacklisted_senders(),
                )
                self.assertEqual(later.status, "false")

    def test_internal_relay_is_never_added_to_dynamic_blacklist(self) -> None:
        sender = "genfollower@genfollower.com"
        false_assessment = InquiryAssessment(status="false", confidence=0.99, reasons=["test"])
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "state.sqlite3"
            with StateStore(db, 0) as state:
                for number in range(3):
                    state.commit(
                        parsed_email(key=f"relay:{number}", envelope_from=sender),
                        false_assessment,
                        NO_MATCH,
                        AppConfig(),
                    )
                self.assertEqual(state.get_sender_non_inquiry_count(sender), 0)
                self.assertNotIn(sender, state.get_blacklisted_senders())

    def test_mailbox_checkpoint_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "state.sqlite3"
            with StateStore(db, 0) as state:
                self.assertIsNone(state.get_mailbox_checkpoint("user@example.com", "INBOX"))
                state.set_mailbox_checkpoint("User@Example.com", "INBOX", "123", 456)
                self.assertEqual(
                    state.get_mailbox_checkpoint("user@example.com", "INBOX"),
                    ("123", 456),
                )

    def test_mailbox_shadow_count_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "state.sqlite3"
            with StateStore(db, 30) as state:
                self.assertIsNone(state.get_mailbox_shadow_count("user@example.com", "INBOX"))
                state.set_mailbox_shadow_count("User@Example.com", "INBOX", 33)
                self.assertEqual(
                    state.get_mailbox_shadow_count("user@example.com", "INBOX"),
                    33,
                )


class FakeImap:
    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.readonly = None
        self.fetch_queries: list[str] = []
        self.messages = {
            4: b"From: old@example.com\r\nSubject: Old\r\n\r\nOld",
            5: b"From: buyer@example.com\r\nSubject: Quote\r\n\r\nPipette tips quote",
        }

    def login(self, email, password):
        return "OK", []

    def select(self, folder, readonly=False):
        self.readonly = readonly
        return "OK", [b"2"]

    def response(self, name):
        return "UIDVALIDITY", [b"777"]

    def uid(self, command, *args):
        if command == "search":
            criterion = args[-1]
            if criterion == "ALL":
                return "OK", [b"4 5"]
            return "OK", [b"5"]
        if command == "fetch":
            uid, query = args
            self.fetch_queries.append(query)
            raw = self.messages[int(uid)]
            return "OK", [(b"RFC822", raw), b")"]
        raise AssertionError(command)

    def logout(self):
        return "BYE", []


class ZohoMailTests(unittest.TestCase):
    def test_download_uses_readonly_mailbox_and_body_peek(self) -> None:
        created: list[FakeImap] = []

        def factory(*args, **kwargs):
            client = FakeImap(*args, **kwargs)
            created.append(client)
            return client

        client = ZohoMailClient(
            "marcus.chen@genfollower.com",
            "secret",
            "imappro.zoho.com",
            993,
            "smtppro.zoho.com",
            465,
            imap_factory=factory,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot, downloaded = client.download_recent(temp_dir, limit=1)
            content = downloaded[0].path.read_bytes()

        self.assertEqual(snapshot.uid_validity, "777")
        self.assertEqual(snapshot.highest_uid, 5)
        self.assertTrue(created[0].readonly)
        self.assertEqual(created[0].fetch_queries, ["(BODY.PEEK[])"])
        self.assertIn(b"Pipette tips quote", content)

    def test_windows_credential_store_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = WindowsCredentialStore(Path(temp_dir) / "secret.dpapi")
            store.save("test-app-password")
            self.assertEqual(store.load(), "test-app-password")
            self.assertNotIn(b"test-app-password", store.path.read_bytes())


if __name__ == "__main__":
    unittest.main()

