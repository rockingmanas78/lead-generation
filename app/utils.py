import re
from typing import Dict, List
from bs4 import BeautifulSoup

IMAGE_OR_ASSET_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "css", "js", "json", "xml"}

def extract_clean_text(html_text: str) -> str:
    soup = BeautifulSoup(html_text, 'html.parser')
    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()
    return ' '.join(soup.stripped_strings)

def find_empty_fields(data: Dict, parent: str = '') -> List[str]:
    empty: List[str] = []
    for key, value in data.items():
        if not value:
            empty.append(f"{parent}.{key}" if parent else key)
    return empty

def merge_data(existing: Dict, new_data: Dict) -> Dict:
    for key in new_data:
        if not existing.get(key):
            existing[key] = new_data[key]
    return existing

def unique_preserve_order(items: List[str]) -> List[str]:
    seen: set[str] = set()
    output: List[str] = []
    for item in items:
        key = item.strip().lower()
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output

def clean_phone_numbers(phone_list: List[str]) -> List[str]:
    """
    Strict-ish cleaning:
    - Keep only digits and '+' sign.
    - Accept E.164-like if starts with '+' and length 8..15 digits after '+'
    - Accept national digits if length 10..15 (no '+')
    - Reject probable dates (e.g., 20250xxxxx), high-repetition, and obviously bogus constants.
    - Do NOT auto-prepend '+' for unknown country.
    """
    cleaned: List[str] = []
    known_bogus_values = {"31536000", "100000000"}  # seconds in a year, etc.

    for raw_value in phone_list:
        if not isinstance(raw_value, str):
            continue
        normalized = re.sub(r"[^\d+]", "", raw_value)

        # Basic shape checks
        if not normalized:
            continue

        has_plus = normalized.startswith("+")
        digits = re.sub(r"\D", "", normalized)

        # Reject known bogus constants
        if digits in known_bogus_values:
            continue

        # Reject date-like (e.g., 20240425...)
        if re.match(r"^(19|20)\d{6,}$", digits):
            continue

        # Reject high repetition (e.g., 0000000000)
        if digits and digits.count(max(set(digits), key=digits.count)) > int(0.7 * len(digits)):
            continue

        if has_plus:
            if 8 <= len(digits) <= 15:
                cleaned.append("+" + digits)
        else:
            # National without plus: require at least 10 digits for quality
            if 10 <= len(digits) <= 15:
                cleaned.append(digits)

    return unique_preserve_order(cleaned)

def clean_emails(email_list: List[str]) -> List[str]:
    """
    Validate and normalize emails:
    - Basic RFC-ish regex.
    - Lowercase the domain part.
    - Drop addresses whose top-level domain looks like an asset extension (png/jpg/etc.).
    """
    cleaned: List[str] = []
    email_regex = re.compile(
        r"(?i)^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,24}$"
    )

    for raw_value in email_list:
        if not isinstance(raw_value, str):
            continue
        candidate = raw_value.strip()
        if not candidate:
            continue
        if not email_regex.match(candidate):
            continue

        local_part, _, domain_part = candidate.rpartition("@")
        if not local_part or not domain_part:
            continue

        # Remove trailing dot if any
        domain_part = domain_part.rstrip(".")

        # Filter out asset-like "TLDs" (e.g., 2x.png)
        tld_match = re.search(r"\.([A-Za-z0-9]{2,24})$", domain_part)
        if not tld_match:
            continue
        tld = tld_match.group(1).lower()
        if tld in IMAGE_OR_ASSET_TLDS:
            continue

        normalized = f"{local_part}@{domain_part.lower()}"
        cleaned.append(normalized)

    return unique_preserve_order(cleaned)


# import re, json
# import phonenumbers
# import tldextract
# from bs4 import BeautifulSoup
# from typing import Dict, List, Tuple, Optional

# EMAIL_SIMPLE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,24}", re.I)
# JUNK_SUFFIXES = (".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif")

# def extract_clean_text(html: str) -> str:
#     soup = BeautifulSoup(html, 'html.parser')
#     for tag in soup(['script', 'style']):
#         tag.decompose()
#     return ' '.join(soup.stripped_strings)

# def find_empty_fields(data: Dict, parent: str = '') -> List[str]:
#     empty = []
#     for k, v in data.items():
#         if not v:
#             empty.append(f"{parent}.{k}" if parent else k)
#     return empty

# def merge_data(old: Dict, new: Dict) -> Dict:
#     for k in new:
#         if not old.get(k):
#             old[k] = new[k]
#     return old

# def clean_phone_numbers(phone_list: List[str]) -> List[str]:
#     cleaned = []

#     for raw in phone_list:
#         digits = re.sub(r"[^\d+]", "", raw)

#         if re.fullmatch(r"\+?\d{8,15}", digits):
#             if not digits.startswith('+') and len(digits) >= 10:
#                 digits = '+' + digits
#             cleaned.append(digits)

#     return list(set(cleaned))

# def registrable_domain(url: str) -> Optional[str]:
#     ext = tldextract.extract(url)
#     if not ext.domain: 
#         return None
#     return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain

# def extract_emails_from_html(html: str) -> List[str]:
#     soup = BeautifulSoup(html, "html.parser")
#     emails = set()

#     # 1) mailto:
#     for a in soup.select("a[href^=mailto]"):
#         href = a.get("href", "")
#         addr = href.split(":", 1)[-1].split("?")[0].strip()
#         if addr and EMAIL_SIMPLE.fullmatch(addr):
#             emails.add(addr)

#     # 2) visible text
#     text = " ".join(soup.stripped_strings)
#     for m in EMAIL_SIMPLE.finditer(text):
#         addr = m.group(0)
#         # drop obvious junk
#         lower = addr.lower()
#         if lower.endswith(JUNK_SUFFIXES):
#             continue
#         emails.add(addr)

#     return list(emails)

# def filter_emails_by_domain(emails: List[str], site_url: str) -> Tuple[List[str], List[str]]:
#     site_dom = registrable_domain(site_url)
#     keep, other = [], []
#     for e in emails:
#         dom = e.split("@")[-1].lower()
#         if site_dom and (dom == site_dom or dom.endswith("." + site_dom)):
#             keep.append(e)
#         else:
#             other.append(e)
#     return list(sorted(set(keep))), list(sorted(set(other)))

# def parse_phones_from_html(html: str, region: str = "IN") -> List[str]:
#     soup = BeautifulSoup(html, "html.parser")
#     text = " ".join(soup.stripped_strings)
#     phones = set()
#     for m in phonenumbers.PhoneNumberMatcher(text, region):
#         num = phonenumbers.format_number(m.number, phonenumbers.PhoneNumberFormat.E164)
#         # basic sanity
#         if 8 <= len(num.replace("+","")) <= 15:
#             phones.add(num)
#     return list(sorted(phones))

# def looks_like_aggregator(url: str, title: str) -> bool:
#     pat = re.compile(r"(top|best|list of|rank|reviews?)", re.I)
#     return "/blog/" in url.lower() and pat.search(title or "") is not None

# def has_location_signal(text: str, locations: List[str]) -> bool:
#     t = text.lower()
#     return any(loc.lower() in t for loc in locations)
