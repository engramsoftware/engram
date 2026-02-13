"""
Email notification service.

Sends emails via SMTP (Gmail app password or any SMTP provider).
Used by Engram to proactively notify users — reminders, summaries,
task alerts, or anything the LLM decides is worth sending.

Typical usage:
    service = EmailService(smtp_host="smtp.gmail.com", smtp_port=587,
                           username="you@gmail.com", password="app-password")
    await service.send(to="you@gmail.com", subject="Reminder", body="Don't forget!")
"""

import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import asyncio

logger = logging.getLogger(__name__)


class EmailService:
    """SMTP email sender with TLS support.

    Args:
        smtp_host: SMTP server hostname (e.g. smtp.gmail.com).
        smtp_port: SMTP port (587 for TLS, 465 for SSL).
        username: SMTP login username (usually your email).
        password: SMTP login password (app password for Gmail).
        from_name: Display name for the sender (default 'Engram').
    """

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        from_name: str = "Engram",
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_name = from_name

    def _build_message(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
    ) -> MIMEMultipart:
        """Build a MIME email message.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Plain text body.
            html_body: Optional HTML body for rich formatting.

        Returns:
            Constructed MIMEMultipart message.
        """
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{self.from_name} <{self.username}>"
        msg["To"] = to
        msg["Subject"] = subject

        # Always attach plain text
        msg.attach(MIMEText(body, "plain", "utf-8"))

        # Attach HTML if provided
        if html_body:
            msg.attach(MIMEText(html_body, "html", "utf-8"))

        return msg

    def _send_sync(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
    ) -> bool:
        """Synchronous SMTP send (runs in thread via asyncio).

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Plain text body.
            html_body: Optional HTML body.

        Returns:
            True if sent successfully, False otherwise.
        """
        msg = self._build_message(to, subject, body, html_body)
        context = ssl.create_default_context()

        try:
            if self.smtp_port == 465:
                # SSL connection
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=context) as server:
                    server.login(self.username, self.password)
                    server.send_message(msg)
            else:
                # STARTTLS connection (port 587)
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    server.ehlo()
                    server.starttls(context=context)
                    server.ehlo()
                    server.login(self.username, self.password)
                    server.send_message(msg)

            logger.info(f"Email sent to {to}: {subject}")
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP auth failed — check username/app password: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to send email to {to}: {e}")
            return False

    async def send(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
    ) -> bool:
        """Send an email asynchronously (runs SMTP in a thread).

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Plain text body (always included).
            html_body: Optional HTML body for rich formatting.

        Returns:
            True if sent successfully, False otherwise.
        """
        return await asyncio.to_thread(
            self._send_sync, to, subject, body, html_body
        )

    def test_connection_sync(self) -> bool:
        """Test SMTP connectivity (synchronous).

        Returns:
            True if login succeeds, False otherwise.
        """
        context = ssl.create_default_context()
        try:
            if self.smtp_port == 465:
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=context) as server:
                    server.login(self.username, self.password)
            else:
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    server.ehlo()
                    server.starttls(context=context)
                    server.ehlo()
                    server.login(self.username, self.password)
            return True
        except Exception as e:
            logger.error(f"SMTP connection test failed: {e}")
            return False

    async def test_connection(self) -> bool:
        """Test SMTP connectivity asynchronously.

        Returns:
            True if login succeeds, False otherwise.
        """
        return await asyncio.to_thread(self.test_connection_sync)


def build_notification_html(
    title: str,
    body: str,
    footer: str = "Sent by Engram — your personal AI assistant",
) -> str:
    """Build a clean HTML email template for Engram notifications.

    Args:
        title: Email heading text.
        body: Main content (supports basic HTML).
        footer: Footer text.

    Returns:
        Complete HTML string for the email body.
    """
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#1a1a2e;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <div style="max-width:560px;margin:24px auto;background:#16213e;border-radius:12px;overflow:hidden;border:1px solid #2a2a4a;">
    <!-- Header -->
    <div style="background:linear-gradient(135deg,#6366f1,#8b5cf6);padding:20px 24px;">
      <h1 style="margin:0;color:#fff;font-size:18px;font-weight:600;">{title}</h1>
    </div>
    <!-- Body -->
    <div style="padding:24px;color:#e2e8f0;font-size:14px;line-height:1.6;">
      {body}
    </div>
    <!-- Footer -->
    <div style="padding:12px 24px;border-top:1px solid #2a2a4a;color:#64748b;font-size:11px;text-align:center;">
      {footer}
    </div>
  </div>
</body>
</html>"""
