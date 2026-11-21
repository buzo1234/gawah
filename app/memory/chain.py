"""The witness chain: each fact version's hash covers its content and the hash of the
version before it in the same deal, so changing any past fact breaks every link after it."""

import hashlib
import json

from app.contracts import Fact

GENESIS = "0" * 64


def fact_hash(fact: Fact, previous: str) -> str:
    content = json.dumps(fact.model_dump(mode="json", exclude={"hash"}), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"{previous}\n{content}".encode()).hexdigest()


def link(fact: Fact, previous: str) -> Fact:
    return fact.model_copy(update={"hash": fact_hash(fact, previous)})


def first_break(versions: list[Fact]) -> int | None:
    """The index of the first version whose hash does not match, or None if the chain holds."""
    previous = GENESIS
    for i, fact in enumerate(versions):
        if fact.hash != fact_hash(fact, previous):
            return i
        previous = fact.hash
    return None


def fingerprint(versions: list[Fact]) -> str:
    """The last link's hash: what the contract can print."""
    return versions[-1].hash if versions else GENESIS
