"""
Read-only IMAP email client.

Uses the same app password stored in email settings (SMTP config).
Supports listing, searching, and reading emails — NO deletes or modifications.
Designed to give the LLM context about the user's emails for recommendations.

Typical usage:
    reader = EmailReader("imap.gmail.com", "user@gmail.com", "app-password")
    emails = reader.search("from:amazon subject:order")
    full = reader.get_message(emails[0]["uid"])
"""

import email
import imaplib
import logging
import re
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Max emails to return per search (cost/memory control)
MAX_RESULTS = 50

# Max body length to extract per email (token budget)
MAX_BODY_LENGTH = 4000


def _decode_header_value(raw: str) -> str:
    """Decode an RFC 2047 encoded email header into a plain string.

    Args:
        raw: Raw header value, possibly MIME-encoded.

    Returns:
        Decoded UTF-8 string.
    """
    if not raw:
        return ""
    parts = decode_header(raw)
    decoded = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(str(data))
    return " ".join(decoded)


def _extract_text_body(msg: email.message.Message) -> str:
    """Walk a MIME message and extract the plain text body.

    Falls back to stripping HTML tags if no text/plain part exists.

    Args:
        msg: Parsed email.message.Message object.

    Returns:
        Plain text body string, truncated to MAX_BODY_LENGTH.
    """
    text_parts = []
    html_parts = []

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    text_parts.append(payload.decode("utf-8", errors="replace"))
            elif ctype == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    html_parts.append(payload.decode("utf-8", errors="replace"))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            ctype = msg.get_content_type()
            decoded = payload.decode("utf-8", errors="replace")
            if ctype == "text/plain":
                text_parts.append(decoded)
            elif ctype == "text/html":
                html_parts.append(decoded)

    # Prefer plain text
    if text_parts:
        body = "\n".join(text_parts)
    elif html_parts:
        # Strip HTML tags for a rough plain-text version
        body = re.sub(r"<[^>]+>", " ", "\n".join(html_parts))
        body = re.sub(r"\s+", " ", body).strip()
    else:
        body = ""

    return body[:MAX_BODY_LENGTH]


class EmailReader:
    """Read-only IMAP email client using app password.

    Connects to an IMAP server (Gmail by default) and provides
    methods to list, search, and read emails. Never modifies or
    deletes anything.

    Args:
        imap_host: IMAP server hostname (default: imap.gmail.com).
        username: Email address / IMAP login.
        password: App password (decrypted).
        imap_port: IMAP SSL port (default: 993).
    """

    def __init__(
        self,
        imap_host: str = "imap.gmail.com",
        username: str = "",
        password: str = "",
        imap_port: int = 993,
    ) -> None:
        self.imap_host = imap_host
        self.username = username
        self.password = password
        self.imap_port = imap_port
        self._conn: Optional[imaplib.IMAP4_SSL] = None

    def connect(self) -> bool:
        """Establish IMAP connection and login.

        Returns:
            True if connected successfully, False otherwise.
        """
        try:
            self._conn = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
            self._conn.login(self.username, self.password)
            logger.info(f"IMAP connected to {self.imap_host} as {self.username}")
            return True
        except Exception as e:
            logger.error(f"IMAP connection failed: {e}")
            self._conn = None
            return False

    def disconnect(self) -> None:
        """Close the IMAP connection gracefully."""
        if self._conn:
            try:
                self._conn.logout()
            except Exception:
                pass
            self._conn = None

    def _ensure_connected(self) -> bool:
        """Reconnect if the connection was lost."""
        if self._conn is None:
            return self.connect()
        try:
            self._conn.noop()
            return True
        except Exception:
            return self.connect()

    def list_recent(self, folder: str = "INBOX", count: int = 20) -> List[Dict[str, Any]]:
        """List the most recent emails in a folder.

        Args:
            folder: IMAP folder name (default: INBOX).
            count: Max number of emails to return.

        Returns:
            List of email metadata dicts (uid, from, subject, date, snippet).
        """
        if not self._ensure_connected() or not self._conn:
            return []

        try:
            self._conn.select(folder, readonly=True)
            # Search for recent emails (last 30 days)
            since = (datetime.now() - timedelta(days=30)).strftime("%d-%b-%Y")
            status, data = self._conn.search(None, f'(SINCE "{since}")')
            if status != "OK":
                return []

            uids = data[0].split()
            # Take the most recent ones
            uids = uids[-min(count, MAX_RESULTS):]
            uids.reverse()

            return self._fetch_headers(uids)
        except Exception as e:
            logger.error(f"IMAP list_recent failed: {e}")
            return []

    def search(self, query: str, folder: str = "INBOX", count: int = 20) -> List[Dict[str, Any]]:
        """Search emails using IMAP search criteria.

        Supports natural language-ish queries that get converted to IMAP search:
        - "from:amazon" → FROM "amazon"
        - "subject:order" → SUBJECT "order"
        - "from:bank subject:statement" → FROM "bank" SUBJECT "statement"
        - Plain text → BODY "text" OR SUBJECT "text"

        Args:
            query: Search query string.
            folder: IMAP folder to search in.
            count: Max results.

        Returns:
            List of email metadata dicts.
        """
        if not self._ensure_connected() or not self._conn:
            return []

        try:
            self._conn.select(folder, readonly=True)
            imap_query = self._build_imap_query(query)
            status, data = self._conn.search(None, imap_query)
            if status != "OK":
                return []

            uids = data[0].split()
            uids = uids[-min(count, MAX_RESULTS):]
            uids.reverse()

            return self._fetch_headers(uids)
        except Exception as e:
            logger.error(f"IMAP search failed: {e}")
            return []

    def get_message(self, uid: str, folder: str = "INBOX") -> Optional[Dict[str, Any]]:
        """Fetch full email content by UID.

        Args:
            uid: Email UID from list/search results.
            folder: IMAP folder.

        Returns:
            Dict with full email data (headers + body), or None.
        """
        if not self._ensure_connected() or not self._conn:
            return None

        try:
            self._conn.select(folder, readonly=True)
            # PEEK so we don't mark as read
            status, data = self._conn.fetch(uid.encode(), "(BODY.PEEK[])")
            if status != "OK" or not data or not data[0]:
                return None

            raw = data[0][1] if isinstance(data[0], tuple) else data[0]
            if not isinstance(raw, bytes):
                return None

            msg = email.message_from_bytes(raw)

            return {
                "uid": uid,
                "from": _decode_header_value(msg.get("From", "")),
                "to": _decode_header_value(msg.get("To", "")),
                "subject": _decode_header_value(msg.get("Subject", "")),
                "date": msg.get("Date", ""),
                "body": _extract_text_body(msg),
                "has_attachments": any(
                    part.get_filename() for part in msg.walk() if part.get_filename()
                ),
            }
        except Exception as e:
            logger.error(f"IMAP get_message failed: {e}")
            return None

    def _fetch_headers(self, uids: List[bytes]) -> List[Dict[str, Any]]:
        """Fetch headers for a list of UIDs.

        Args:
            uids: List of IMAP message UIDs.

        Returns:
            List of email metadata dicts.
        """
        if not self._conn or not uids:
            return []

        results = []
        for uid in uids:
            try:
                status, data = self._conn.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                if status != "OK" or not data or not data[0]:
                    continue

                raw = data[0][1] if isinstance(data[0], tuple) else data[0]
                if not isinstance(raw, bytes):
                    continue

                msg = email.message_from_bytes(raw)
                subject = _decode_header_value(msg.get("Subject", ""))
                from_addr = _decode_header_value(msg.get("From", ""))
                date_str = msg.get("Date", "")

                results.append({
                    "uid": uid.decode() if isinstance(uid, bytes) else str(uid),
                    "from": from_addr,
                    "subject": subject,
                    "date": date_str,
                })
            except Exception:
                continue

        return results

    @staticmethod
    def _build_imap_query(query: str) -> str:
        """Convert a human-friendly query into IMAP search syntax.

        Args:
            query: Natural language query (e.g. "from:amazon subject:order").

        Returns:
            IMAP search string.
        """
        parts = []

        # Extract from: patterns
        from_matches = re.findall(r'from:(\S+)', query, re.IGNORECASE)
        for fm in from_matches:
            parts.append(f'FROM "{fm}"')
            query = query.replace(f"from:{fm}", "", 1)

        # Extract subject: patterns
        subj_matches = re.findall(r'subject:(\S+)', query, re.IGNORECASE)
        for sm in subj_matches:
            parts.append(f'SUBJECT "{sm}"')
            query = query.replace(f"subject:{sm}", "", 1)

        # Extract to: patterns
        to_matches = re.findall(r'to:(\S+)', query, re.IGNORECASE)
        for tm in to_matches:
            parts.append(f'TO "{tm}"')
            query = query.replace(f"to:{tm}", "", 1)

        # Remaining text → search body and subject
        remaining = query.strip()
        if remaining:
            parts.append(f'OR SUBJECT "{remaining}" BODY "{remaining}"')

        if not parts:
            return "ALL"

        return " ".join(parts)


def get_email_reader_from_settings(email_cfg: Dict[str, Any], password: str) -> Optional[EmailReader]:
    """Create an EmailReader from the user's stored email settings.

    Derives the IMAP host from the SMTP host (smtp.gmail.com → imap.gmail.com).

    Args:
        email_cfg: Email config dict from MongoDB (smtpHost, username, etc.).
        password: Decrypted app password.

    Returns:
        Connected EmailReader, or None if connection fails.
    """
    smtp_host = email_cfg.get("smtpHost", "smtp.gmail.com")
    # Derive IMAP host from SMTP host
    imap_host = smtp_host.replace("smtp.", "imap.")
    username = email_cfg.get("username", "")

    if not username or not password:
        return None

    reader = EmailReader(
        imap_host=imap_host,
        username=username,
        password=password,
    )
    if reader.connect():
        return reader
    return None
