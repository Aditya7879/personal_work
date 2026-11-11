"""Business taxonomy is distinct from RCA defect taxonomy; retain provenance."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from pathlib import Path


DOMAIN_ALIASES = {"O2C": "O2C", "OTC": "O2C", "F2S": "F2S", "P2P": "P2P", "R2R": "R2R"}
BUSINESS_DOMAIN_CODES = ("O2C", "F2S", "P2P", "R2R")
USER_CLASSIFICATION_SOURCES = frozenset({'user_submitted', 'user_confirmed', 'reviewer_confirmed'})
# Suggested choices, not a classification of any submitted question. Existing
# workbook labels and owner-visible custom values are retained separately.
DEFAULT_BUSINESS_SUBDOMAINS = {
    "O2C": ("Billing and AR posting", "Collection and Dunning", "Credit Management", "Customer Master Data",
        "Order Creation", "Order Validation", "Payment Matching", "Reverse and Cancellation"),
    "F2S": ("Batch Management", "DC to DC planning", "Demand & Supply Planning", "Destructions Management",
        "Lifecycle Management", "PO SO Master Data & Receiving Activities", "Product master data",
        "Stock Management & Azure Practise", "Sub-contracting/Copacking", "Transportation Management"),
    "P2P": (), "R2R": (), "Unspecified": (),
}


def normalize_business_label(value: str | None, *, domain: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('Business classification must be text')
    value = re.sub(r'\s+', ' ', value).strip()
    if not value:
        return None
    if any(unicodedata.category(char) == 'Cc' or char in '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069' for char in value):
        raise ValueError('Business classification must not contain control characters')
    if domain:
        if value.casefold() == 'unspecified':
            return 'Unspecified'
        return DOMAIN_ALIASES.get(value.upper(), value)
    return value


def business_taxonomy_options(rows: list[dict]) -> dict:
    choices = {domain: set(values) for domain, values in DEFAULT_BUSINESS_SUBDOMAINS.items()}
    for row in rows:
        try:
            domain = normalize_business_label(row.get('business_domain'), domain=True) or 'Unspecified'
            subdomain = normalize_business_label(row.get('business_subdomain'))
        except ValueError:
            continue
        if len(domain) > 100 or subdomain is not None and len(subdomain) > 300:
            continue
        choices.setdefault(domain, set())
        if subdomain:
            choices[domain].add(subdomain)
    domains = [*BUSINESS_DOMAIN_CODES, *sorted((name for name in choices if name not in {*BUSINESS_DOMAIN_CODES, 'Unspecified'}), key=str.casefold)]
    return {'domains': domains, 'subdomains': {name: sorted(values, key=str.casefold) for name, values in choices.items()}, 'allowCustom': True}
DOMAIN_PHRASES = {"O2C": r"order[\s_-]+to[\s_-]+cash", "F2S": r"forecast[\s_-]+to[\s_-]+stock",
                  "P2P": r"procure[\s_-]+to[\s_-]+pay", "R2R": r"record[\s_-]+to[\s_-]+report"}
SUBDOMAINS = [
    ("Batch management", r"batch.{0,5}management"),
    ("Product lifecycle management", r"lifecycle|life.{0,2}cycle"),
    ("Product master data", r"product.{0,6}master|material.{0,6}master"),
    ("Customer master data", r"customer.{0,6}master"),
    ("Order management", r"order.{0,8}(creation|management|validation|processing)"),
    ("Delivery management", r"outbound.{0,6}delivery|delivery.{0,6}(creation|management)"),
    ("Credit management", r"credit.{0,6}management"),
    ("Collection and dunning", r"collection|dunning"),
    ("Co-packing / subcontracting", r"co.{0,2}packing|sub.{0,2}contract"),
    ("Demand and supply planning", r"demand.{0,8}supply|planning"),
    ("Billing and accounts receivable", r"billing|accounts.{0,6}receivable"),
]


def domain_from_metadata(value: str) -> str | None:
    match = re.search(r"(?:^|[^A-Z0-9])(O2C|OTC|F2S|P2P|R2R)(?=$|[^A-Z0-9])", value.upper())
    return DOMAIN_ALIASES.get(match.group(1)) if match else None


def split_business_taxonomy(value: str) -> tuple[str | None, str | None]:
    """Split an explicit spreadsheet label, without guessing a domain from its topic."""
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    match = re.fullmatch(r"(O2C|OTC|F2S|P2P|R2R)\s*[-–—:]\s*(.+)", value, re.I)
    if match:
        return DOMAIN_ALIASES[match.group(1).upper()], match.group(2).strip()
    return None, value or None


def workbook_business_taxonomy(labels: list[str]) -> dict[str, dict]:
    """Resolve bare labels only from unambiguous, explicitly prefixed workbook peers."""
    peers: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for label in labels:
        domain, subdomain = split_business_taxonomy(label)
        if domain and subdomain:
            peers[subdomain.casefold()].append((domain, subdomain))
    result = {}
    for label in labels:
        domain, subdomain = split_business_taxonomy(label)
        matches = peers.get((subdomain or "").casefold(), [])
        if not domain and len({entry[0] for entry in matches}) == 1:
            domain = matches[0][0]
        if domain and matches:
            subdomain = max((entry[1] for entry in matches if entry[0] == domain), key=lambda text: sum(char.isupper() for char in text))
        result[label] = {"domain": domain, "subdomain": subdomain}
    return result


def infer_business_domain(question: str, evidence: list[dict]) -> dict:
    weights: dict[str, float] = defaultdict(float)
    provenance: dict[str, list[dict]] = defaultdict(list)
    for item in evidence:
        source = str(item.get("source") or "")
        domain = domain_from_metadata(source)
        method = "retrieved_document_filename"
        if domain is None:
            text = str(item.get("context") or item.get("excerpt") or "")
            candidates = {DOMAIN_ALIASES[value] for value in re.findall(r"\b(O2C|OTC|F2S|P2P|R2R)\b", text.upper())}
            candidates.update(code for code, pattern in DOMAIN_PHRASES.items() if re.search(pattern, text, re.I))
            if len(candidates) == 1:
                domain = candidates.pop()
                method = "retrieved_document_content"
        if domain is None:
            continue
        weight = max(0.0, float(item.get("score") or 1.0))
        weights[domain] += weight
        provenance[domain].append({"source": Path(source).name, "page": item.get("page"),
                                   "elementId": item.get("element_id"), "evidenceId": item.get("evidence_id"),
                                   "method": method, "retrievalBackend": item.get("origin"),
                                   "documentId": item.get("document_id"), "corpusVersion": item.get("corpus_version"),
                                   "chunkContentSha256": item.get("chunk_content_sha256")})
    if not weights or sum(weights.values()) <= 0:
        return {"domain": "Unspecified", "subdomain": None, "confidence": None, "source": "insufficient_evidence",
                "reason": "No retrieved document establishes a business domain. Please confirm the domain.", "evidence": [], "verified": False}
    winner = max(weights, key=weights.get)
    share = weights[winner] / sum(weights.values())
    question_domain = domain_from_metadata(question)
    conflicting = question_domain is not None and question_domain != winner
    ambiguous = share < 0.75 or conflicting
    chosen = provenance[winner][:4]
    selected_sources = {item["source"] for item in chosen}
    names = " ".join(str(item.get("source") or "") + " " + str(item.get("context") or item.get("excerpt") or "")[:1200] for item in evidence if Path(str(item.get("source") or "")).name in selected_sources).replace("_", " ")
    subdomain = next((label for label, pattern in SUBDOMAINS if re.search(pattern, names, re.I)), None)
    return {"domain": "Unspecified" if ambiguous else winner, "subdomain": None if ambiguous else subdomain,
            "confidence": round(min(0.85, share), 3), "source": "document_inferred",
            "reason": "Retrieved documents disagree with each other or the question; please choose the business domain." if ambiguous else f"Suggested {winner} from domain markers in relevant document names or cited chunks. This is an evidence hint, not a verified classification.",
            "evidence": chosen, "verified": False}
