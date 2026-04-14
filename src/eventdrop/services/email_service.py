import asyncio
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from eventdrop.config import settings

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, body_html: str, body_text: Optional[str] = None) -> bool:
    """Send an email via configured SMTP. Returns True on success."""
    if not settings.is_smtp_configured():
        logger.warning("SMTP not configured, cannot send email.")
        return False

    def _send():
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from
        msg["To"] = to

        if body_text:
            msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        try:
            if settings.smtp_ssl:
                ctx = ssl.create_default_context()
                with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=ctx) as server:
                    if settings.smtp_username:
                        server.login(settings.smtp_username, settings.smtp_password)
                    server.sendmail(settings.smtp_from, [to], msg.as_string())
            else:
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                    if settings.smtp_tls:
                        server.starttls()
                    if settings.smtp_username:
                        server.login(settings.smtp_username, settings.smtp_password)
                    server.sendmail(settings.smtp_from, [to], msg.as_string())
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to}: {e}")
            return False

    return await asyncio.to_thread(_send)


async def send_password_reset_email(to: str, reset_url: str) -> bool:
    subject = "EventDrop — Reset your password"
    body_html = f"""
    <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
        <h2 style="color: #4f46e5;">Reset your EventDrop password</h2>
        <p>You requested a password reset. Click the link below to set a new password:</p>
        <p><a href="{reset_url}" style="display:inline-block;padding:10px 20px;background:#4f46e5;color:#fff;text-decoration:none;border-radius:6px;">Reset Password</a></p>
        <p style="color:#6b7280;font-size:13px;">This link expires in 1 hour. If you didn't request this, you can ignore this email.</p>
    </div>
    """
    body_text = f"Reset your EventDrop password by visiting: {reset_url}\n\nThis link expires in 1 hour."
    return await send_email(to, subject, body_html, body_text)
