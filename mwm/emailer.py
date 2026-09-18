from __future__ import annotations

from dataclasses import dataclass, field
from email.message import EmailMessage as MimeMessage
import smtplib
import ssl
from html import unescape
import re

from .config import Config


@dataclass
class EmailMessage:
    to: str
    subject: str
    html: str
    headers: dict[str, str] = field(default_factory=dict)


class DisabledEmailProvider:
    name = "disabled"

    def send(self, message: EmailMessage) -> bool:
        return False


class ConsoleEmailProvider:
    name = "console"

    def send(self, message: EmailMessage) -> bool:
        print(f"EMAIL to={message.to!r} subject={message.subject!r} headers={message.headers!r}")
        return True


class SMTPEmailProvider:
    name = "smtp"

    def __init__(self, config: Config):
        self.config = config

    def send(self, message: EmailMessage) -> bool:
        mime = MimeMessage()
        mime["To"] = message.to
        mime["From"] = self.config.email_from
        mime["Subject"] = message.subject
        for name, value in message.headers.items():
            mime[name] = value
        plain = re.sub(r"<[^>]+>", " ", message.html)
        mime.set_content(re.sub(r"\s+", " ", unescape(plain)).strip())
        mime.add_alternative(message.html, subtype="html")
        context = ssl.create_default_context()
        with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=20) as smtp:
            if self.config.smtp_starttls:
                smtp.starttls(context=context)
            if self.config.smtp_username:
                smtp.login(self.config.smtp_username, self.config.smtp_password)
            smtp.send_message(mime)
        return True


def get_email_provider(config: Config):
    if config.email_provider == "console":
        return ConsoleEmailProvider()
    if config.email_provider == "smtp" and config.email_enabled:
        return SMTPEmailProvider(config)
    return DisabledEmailProvider()
