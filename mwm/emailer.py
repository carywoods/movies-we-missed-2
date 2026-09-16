from __future__ import annotations

from dataclasses import dataclass

from .config import Config


@dataclass
class EmailMessage:
    to: str
    subject: str
    html: str


class DisabledEmailProvider:
    name = "disabled"

    def send(self, message: EmailMessage) -> bool:
        return False


class ConsoleEmailProvider:
    name = "console"

    def send(self, message: EmailMessage) -> bool:
        print(f"EMAIL to={message.to!r} subject={message.subject!r}")
        return True


def get_email_provider(config: Config):
    if config.email_provider == "console":
        return ConsoleEmailProvider()
    return DisabledEmailProvider()
