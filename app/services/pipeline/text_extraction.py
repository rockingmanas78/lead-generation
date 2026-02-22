from __future__ import annotations

import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from bs4 import BeautifulSoup

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})")

ROLE_ACCOUNT_LOCAL_PARTS = {
    "info","hello","contact","careers","career","jobs","job","hr","humanresources","support",
    "help","admin","privacy","legal","billing","accounts","sales","marketing","press","media","investors",
    "office","team","enquiry","enquiries","query","queries","service","customerservice"
}

def extract_company_domain_from_url(url: str) -> Optional[str]:
    try:
        host = urlparse(url).netloc.lower().strip()
        if host.startswith("www."):
            host = host[4:]
        return host or None
    except Exception:
        return None

def extract_emails(text: str) -> List[str]:
    if not text:
        return []
    found = []
    for match in re.finditer(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text):
        email = match.group(0).strip(".,;:()<>[]{}\"'")
        found.append(email)
    return sorted(set(found))

def is_person_like_email_address(email_address: str) -> bool:
    local_part = email_address.split("@", 1)[0].lower()

    normalized = local_part.replace(".", "").replace("_", "").replace("-", "")
    if normalized in ROLE_ACCOUNT_LOCAL_PARTS:
        return False

    tokens = [t for t in re.split(r"[._\-]+", local_part) if t]
    if len(tokens) < 2:
        return False
    if any(t in ROLE_ACCOUNT_LOCAL_PARTS for t in tokens):
        return False

    # avoid purely numeric or single-character-only patterns
    if all(len(t) == 1 for t in tokens):
        return False
    if all(t.isdigit() for t in tokens):
        return False

    return True

def extract_person_emails_for_domain(text: str, company_domain: str) -> List[str]:
    emails = extract_emails(text)
    emails = [e for e in emails if e.lower().endswith("@" + company_domain.lower())]
    return [e for e in emails if is_person_like_email_address(e)]

def extract_visible_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)

def looks_like_full_name(candidate: str) -> bool:
    words = [w for w in re.split(r"\s+", candidate.strip()) if w]
    if not (2 <= len(words) <= 4):
        return False
    if any(len(w) < 2 for w in words):
        return False
    if not all(w[0].isupper() for w in words if w and w[0].isalpha()):
        return False
    return True

def extract_person_name_from_search_title_or_snippet(title: str, snippet: str) -> List[Tuple[str, Optional[str]]]:
    """Extract (full_name, role_hint) from metadata only (no page fetch)."""
    title = title or ""
    snippet = snippet or ""
    combined = (title + " " + snippet).strip()
    if not combined:
        return []

    # Common format: "First Last - Title - Company | LinkedIn"
    match = re.match(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s*[-|–]", title)
    if match:
        full_name = match.group(1).strip()
        if looks_like_full_name(full_name):
            parts = re.split(r"[-|–]", title)
            role_hint = parts[1].strip()[:120] if len(parts) > 1 else None
            return [(full_name, role_hint)]

    # fallback: pick a few TitleCase sequences
    candidates = re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}", combined)
    out: List[Tuple[str, Optional[str]]] = []
    for cand in candidates[:6]:
        if looks_like_full_name(cand):
            out.append((cand.strip(), None))

    # dedupe
    seen = set()
    deduped = []
    for full_name, role_hint in out:
        key = full_name.lower()
        if key not in seen:
            seen.add(key)
            deduped.append((full_name, role_hint))
    return deduped
