"""The witness chain, checked again from the fact.recorded events alone, with the formula
memory documents in app/memory/chain.py. Kept here so the contract never prints a head it
has not checked itself."""

import hashlib
import json

from app.contracts import Fact

GENESIS = "0" * 64


def head(facts: list[Fact]) -> tuple[str, int] | None:
    """(head fingerprint, number of links) when every link holds; None when any link is
    broken or there are no facts."""
    previous = GENESIS
    for fact in facts:
        content = json.dumps(fact.model_dump(mode="json", exclude={"hash"}), sort_keys=True, ensure_ascii=False)
        if fact.hash != hashlib.sha256(f"{previous}\n{content}".encode()).hexdigest():
            return None
        previous = fact.hash
    return (previous, len(facts)) if facts else None
