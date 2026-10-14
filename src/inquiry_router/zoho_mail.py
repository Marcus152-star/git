from __future__ import annotations

import imaplib
import smtplib
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class MailboxSnapshot:
    uid_validity: str
    highest_uid: int


@dataclass(frozen=True)
class DownloadedEmail:
    uid: int
    path: Path


class ZohoMailClient:
    def __init__(
        self,
        email_address: str,
        password: str,
        imap_host: str,
        imap_port: int,
        smtp_host: str,
        smtp_port: int,
        folder: str = "INBOX",
        timeout: int = 30,
        imap_factory: Callable | None = None,
        smtp_factory: Callable | None = None,
    ) -> None:
        self.email_address = email_address
        self.password = password
        self.imap_host = imap_host
        self.imap_port = imap_port
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.folder = folder
        self.timeout = timeout
        self.imap_factory = imap_factory or imaplib.IMAP4_SSL
        self.smtp_factory = smtp_factory or smtplib.SMTP_SSL

    def _open_imap(self):
        client = self.imap_factory(self.imap_host, self.imap_port, timeout=self.timeout)
        try:
            client.login(self.email_address, self.password)
            status, _ = client.select(self.folder, readonly=True)
            if status != "OK":
                raise RuntimeError(f"无法以只读方式打开邮箱文件夹：{self.folder}")
            return client
        except Exception:
            try:
                client.logout()
            except Exception:
                pass
            raise

    @staticmethod
    def _uids(client, criterion: str = "ALL") -> list[int]:
        status, data = client.uid("search", None, criterion)
        if status != "OK":
            raise RuntimeError("无法读取 Zoho 邮件编号")
        raw = data[0] if data else b""
        return [int(value) for value in raw.split()]

    @staticmethod
    def _uid_validity(client) -> str:
        status, data = client.response("UIDVALIDITY")
        if status != "UIDVALIDITY" or not data:
            raise RuntimeError("Zoho 没有返回 UIDVALIDITY，无法安全防止重复读取")
        value = data[0]
        return value.decode("ascii") if isinstance(value, bytes) else str(value)

    def test_imap(self) -> MailboxSnapshot:
        client = self._open_imap()
        try:
            uids = self._uids(client)
            return MailboxSnapshot(self._uid_validity(client), max(uids, default=0))
        finally:
            client.logout()

    def test_smtp(self) -> None:
        context = ssl.create_default_context()
        client = self.smtp_factory(
            self.smtp_host,
            self.smtp_port,
            timeout=self.timeout,
            context=context,
        )
        try:
            client.login(self.email_address, self.password)
            client.noop()
        finally:
            client.quit()

    def download_recent(self, destination: str | Path, limit: int = 20) -> tuple[MailboxSnapshot, list[DownloadedEmail]]:
        if limit < 1:
            raise ValueError("读取数量必须大于0")
        client = self._open_imap()
        try:
            uids = self._uids(client)
            snapshot = MailboxSnapshot(self._uid_validity(client), max(uids, default=0))
            return snapshot, self._download_uids(client, uids[-limit:], destination)
        finally:
            client.logout()

    def download_after(
        self,
        destination: str | Path,
        last_uid: int,
        expected_uid_validity: str,
    ) -> tuple[MailboxSnapshot, list[DownloadedEmail]]:
        client = self._open_imap()
        try:
            uid_validity = self._uid_validity(client)
            if uid_validity != expected_uid_validity:
                raise RuntimeError("邮箱 UIDVALIDITY 已变化，请重新设置监控起点")
            uids = self._uids(client, f"UID {last_uid + 1}:*")
            uids = [uid for uid in uids if uid > last_uid]
            snapshot = MailboxSnapshot(uid_validity, max([last_uid, *uids]))
            return snapshot, self._download_uids(client, uids, destination)
        finally:
            client.logout()

    @staticmethod
    def _download_uids(client, uids: list[int], destination: str | Path) -> list[DownloadedEmail]:
        output_dir = Path(destination)
        output_dir.mkdir(parents=True, exist_ok=True)
        downloaded: list[DownloadedEmail] = []
        for uid in uids:
            status, data = client.uid("fetch", str(uid), "(BODY.PEEK[])")
            if status != "OK":
                raise RuntimeError(f"读取 Zoho 邮件失败：UID {uid}")
            raw_message = next(
                (part[1] for part in data if isinstance(part, tuple) and len(part) > 1),
                None,
            )
            if not isinstance(raw_message, bytes):
                raise RuntimeError(f"Zoho 邮件内容为空：UID {uid}")
            path = output_dir / f"zoho-{uid}.eml"
            path.write_bytes(raw_message)
            downloaded.append(DownloadedEmail(uid, path))
        return downloaded
