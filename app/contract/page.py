"""A Document as the page Chrome prints: A4, black and grey, a footer on every page.

Every value is escaped: names, places and spoken words come from a phone call.
"""

from html import escape as e

from app.contract.document import (
    CONFIRMED, FINGERPRINT, IF_YOU_DISAGREE, IS, IS_NOT, LEAD, SUBTITLE, TITLE, WITNESS, Bi, Clause, Document, both,
)


def html(doc: Document) -> str:
    place = f"<div>काम की जगह / Place of work: <b>{e(both(doc.place))}</b></div>" if doc.place else ""
    parties = "".join(
        f"<tr><th>{e(p.title.hi)} <span>/ {e(p.title.en)}</span><br><small>{e(p.role.hi)} / {e(p.role.en)}</small></th>"
        f"<td>{e(both(p.name)) if p.name else ''}</td><td>फ़ोन / Phone<br>{e(p.phone)}</td></tr>"
        for p in doc.parties
    )
    accepted = "".join(
        f"<div class=sign><h4>{e(a.party.title.hi)} <span>/ {e(a.party.title.en)}</span></h4>"
        + (f"<p class=name>{e(both(a.party.name))}</p>" if a.party.name else "")
        + f"<p>फ़ोन / Phone: {e(a.party.phone)}</p><p>{e(CONFIRMED.hi)}<br>{e(CONFIRMED.en)}</p>"
        f"<p>{e(a.when.hi)}<br>{e(a.when.en)}</p>"
        + (f"<p>कहा / Said: \u201c{e(a.said)}\u201d</p>" if a.said else "")
        + "</div>"
        for a in doc.acceptances
    )
    prints = "".join(f"<p>{e(who.hi)} / {e(who.en)}<br><code>{e(digest)}</code></p>" for who, digest in doc.fingerprints)
    witness = (
        _two(WITNESS) + (_two(doc.call) if doc.call else "")
        + (f"<div class=prints>{_two(FINGERPRINT)}{prints}</div>" if prints else "")
    )
    return _PAGE.format(
        reference=e(doc.reference), reference_css=_css(doc.reference), made_css=_css(doc.made.en),
        title_hi=e(TITLE.hi), title_en=e(TITLE.en), subtitle=f"{e(SUBTITLE.hi)}<br>{e(SUBTITLE.en)}",
        date=e(f"{doc.date.hi} / {doc.date.en}"), place=place, parties=parties, lead=_two(LEAD),
        clauses="".join(_clause(n, c) for n, c in enumerate(doc.clauses, 1)),
        accepted=accepted, witness=witness, notes=_two(IS) + _two(IS_NOT), disagree=_two(IF_YOU_DISAGREE),
    )


def _clause(n: int, clause: Clause) -> str:
    rows = "".join(
        f"<tr><th>{e(p.label.hi)}<br><span>{e(p.label.en)}</span></th><td class=amount>{e(both(p.amount, ' / '))}</td>"
        f"<td>{e(p.when.hi)}<br>{e(p.when.en)}</td><td class=at>{e(p.said_at or '')}</td></tr>"
        for p in clause.payments
    )
    table = (
        "<table class=pay><thead><tr><th>भुगतान<br><span>Payment</span></th><th>रकम<br><span>Amount</span></th>"
        "<th>कब और कैसे<br><span>When and how</span></th><th class=at>कॉल<br><span>call</span></th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    ) if rows else ""
    at = f"<div class=at>कॉल / call<br>{e(clause.said_at)}</div>" if clause.said_at else ""
    return (
        f"<section><div class=num>{n}.</div><div><h3>{e(clause.title.hi)} <span>/ {e(clause.title.en)}</span></h3>"
        f"{_two(clause.body) if clause.body else ''}{table}</div>{at}</section>"
    )


def _two(text: Bi) -> str:
    return f"<p>{e(text.hi)}</p><p>{e(text.en)}</p>"


def _css(text: str) -> str:
    """Safe inside a CSS double-quoted string."""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


_FONTS = '"Charter", "Iowan Old Style", Georgia, "ITF Devanagari", "Kohinoor Devanagari", "Noto Serif Devanagari", "Nirmala UI", serif'

# Each margin box needs its own copy: a grouped selector is not allowed for them.
_FOOT = "font-family: FONTS; font-size: 7pt; color: #555; vertical-align: top; padding-top: 6mm; white-space: nowrap;"

_PAGE = """<!doctype html>
<html lang="hi"><head><meta charset="utf-8"><title>{title_en} {reference}</title><style>
@page {{
  size: A4; margin: 18mm 21mm 21mm;
  @bottom-left {{ content: "संदर्भ / Ref. {reference_css}"; FOOT }}
  @bottom-center {{ content: "पेज " counter(page) " / " counter(pages) "  ·  Page " counter(page) " of " counter(pages); FOOT }}
  @bottom-right {{ content: "बनाया गया / Made: {made_css}"; FOOT }}
}}
body {{ font-family: FONTS; font-size: 10pt; line-height: 1.42; color: #111; margin: 0; }}
p {{ margin: 0; }}
span, small {{ font-weight: normal; }}
header {{ text-align: center; padding-bottom: 3.5mm; border-bottom: 0.9mm double #111; }}
h1 {{ font-size: 19pt; line-height: 1.25; margin: 0; }}
h1 span {{ display: block; font-size: 11.5pt; font-weight: bold; letter-spacing: 0.22em; text-transform: uppercase; margin-top: 0.5mm; }}
header p {{ font-size: 8.8pt; color: #444; margin-top: 1.5mm; }}
.meta {{ display: flex; justify-content: space-between; flex-wrap: wrap; gap: 0 8mm; margin: 3mm 0 0; font-size: 9.5pt; }}
h2 {{ font-size: 9.5pt; letter-spacing: 0.08em; margin: 5mm 0 1.8mm; padding-bottom: 0.8mm; border-bottom: 0.25mm solid #111; }}
h2 span {{ font-weight: bold; text-transform: uppercase; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ text-align: left; vertical-align: top; padding: 1mm 4mm 1mm 0; }}
.parties th {{ width: 44mm; }}
.parties td:last-child {{ width: 42mm; padding-right: 0; }}
.parties td {{ font-weight: bold; }}
.parties td:last-child, small {{ font-weight: normal; font-size: 9pt; color: #333; }}
.lead {{ margin: 2.5mm 0 1mm; color: #333; font-size: 9.5pt; }}
section {{ display: grid; grid-template-columns: 8mm 1fr 15mm; margin-top: 3.2mm; break-inside: avoid; }}
.num {{ font-size: 13pt; font-weight: bold; line-height: 1.1; }}
h3 {{ font-size: 10.5pt; margin: 0 0 0.6mm; }}
.at {{ font-size: 7.5pt; line-height: 1.3; color: #555; text-align: right; white-space: nowrap; }}
.pay {{ margin-top: 1mm; border-top: 0.25mm solid #111; border-bottom: 0.25mm solid #111; }}
section:has(.pay) > div:nth-child(2) {{ grid-column: 2 / -1; }}
.pay th, .pay td {{ padding: 1.2mm 3mm 1.2mm 0; border-top: 0.12mm solid #999; }}
.pay thead th {{ font-size: 8.5pt; border-top: 0; line-height: 1.25; }}
.pay th:first-child {{ width: 21mm; }}
.pay .amount {{ width: 24mm; font-weight: bold; white-space: nowrap; }}
.pay .at {{ width: 9mm; padding-right: 0; }}
.signs {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0 9mm; }}
.sign {{ border: 0.2mm solid #777; padding: 2mm 3mm 2.5mm; break-inside: avoid; }}
.sign, .witness {{ font-size: 9.2pt; }}
.sign p, .witness p + p {{ margin-top: 1mm; }}
.witness p:nth-child(even) {{ margin-top: 0; }}
h4 {{ font-size: 9.5pt; margin: 0 0 0.5mm; }}
.name {{ font-size: 10.5pt; font-weight: bold; }}
.block {{ break-inside: avoid; }}
.prints {{ margin-top: 1.5mm; }}
code {{ font-family: Menlo, Consolas, monospace; font-size: 7.2pt; word-break: break-all; }}
.notes {{ font-size: 9.2pt; }}
.notes p:nth-child(odd) {{ margin-top: 1mm; }}
</style></head><body>
<header><h1>{title_hi}<span>{title_en}</span></h1><p>{subtitle}</p></header>
<div class="meta"><div>संदर्भ संख्या / Reference no.: <b>{reference}</b></div><div>तारीख / Date: <b>{date}</b></div>{place}</div>
<h2>पक्ष <span>/ Parties</span></h2>
<table class="parties">{parties}</table>
<div class="lead">{lead}</div>
{clauses}
<div class="block"><h2>स्वीकृति <span>/ Acceptance</span></h2><div class="signs">{accepted}</div></div>
<div class="block"><h2>गवाह <span>/ Witness</span></h2><div class="witness">{witness}</div></div>
<div class="block"><h2>यह दस्तावेज़ क्या है <span>/ What this document is</span></h2>
<div class="notes">{notes}{disagree}</div></div>
</body></html>
""".replace("FOOT", _FOOT).replace("FONTS", _FONTS)
