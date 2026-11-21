"""Two logging rules from AGENTS.md, in one place: every line carries the deal id,
and phone numbers show only their last 4 digits."""

import logging


def mask_phone(phone: str | None) -> str:
    return f"***{phone[-4:]}" if phone else "-"


class _DealLogger(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"deal={self.extra['deal_id']} {msg}", kwargs


def deal_log(name: str, deal_id: str) -> logging.LoggerAdapter:
    """A logger that puts the deal id at the start of every line."""
    return _DealLogger(logging.getLogger(name), {"deal_id": deal_id})
