"""The witness chain: each fact version's hash covers its content and the hash of the
version before it in the same deal, so changing any past fact breaks every link after it.

The formula, exactly, so anyone can check it from the fact.recorded events alone:

    links    = the deal's fact.recorded events, in the order they were published
               (the event log's order); every version of a fact is its own link
    prev_0   = "0" * 64
    content  = json.dumps(fact_without_hash, sort_keys=True, ensure_ascii=False)
               where fact_without_hash is the event's `fact` object with the "hash" key
               removed, every other field kept (nulls and empty lists included), as
               pydantic's model_dump(mode="json") writes it: datetimes as ISO 8601
               strings ("2026-11-21T10:00:09Z"), dates as "YYYY-MM-DD", enums as
               their string values. Default separators: ", " and ": ".
    hash_i   = sha256( prev_{i-1} + "\\n" + content ).hexdigest(), the input UTF-8 encoded
    prev_i   = hash_i

A link is broken when its stored `hash` differs from hash_i. The head is the last hash.
"""

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


def report(versions: list[Fact]) -> dict:
    """What GET /memory/chain/<deal_id> answers."""
    broken = first_break(versions)
    return {
        "verified": broken is None,
        "links": len(versions),
        "head": fingerprint(versions),
        "first_broken": None if broken is None else {
            "index": broken, "fact_id": versions[broken].id, "stored_hash": versions[broken].hash,
        },
    }
