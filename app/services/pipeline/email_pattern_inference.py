from __future__ import annotations

import re
from typing import List, Tuple

def _split_local_part(email_address: str) -> List[str]:
    local_part = email_address.split("@", 1)[0].lower()
    return [p for p in re.split(r"[._\-]+", local_part) if p]

def infer_ranked_email_patterns(person_email_addresses: List[str]) -> List[str]:
    """Infer ranked patterns from observed personal emails.
    Output patterns (in order of preference):
      - first.last
      - f.last
      - firstl
      - flast
      - first.last2
    """
    if len(person_email_addresses) < 2:
        return []

    tokenized = [_split_local_part(e) for e in person_email_addresses]
    patterns: List[str] = []

    # if most samples look like two tokens, treat as first.last baseline
    two_token_ratio = sum(1 for tokens in tokenized if len(tokens) == 2) / max(1, len(tokenized))
    if two_token_ratio >= 0.6:
        patterns.append("first.last")

    # if many look like initial + last
    f_last_ratio = 0.0
    for tokens in tokenized:
        if len(tokens) == 2 and len(tokens[0]) == 1 and len(tokens[1]) >= 3:
            f_last_ratio += 1.0
    f_last_ratio = f_last_ratio / max(1, len(tokenized))
    if f_last_ratio >= 0.4:
        patterns.append("f.last")

    # universal fallbacks
    patterns.extend(["firstl", "flast", "first.last2"])

    # dedupe preserve order
    output: List[str] = []
    for pat in patterns:
        if pat not in output:
            output.append(pat)
    return output

def _normalize_name_to_first_and_last(full_name: str) -> Tuple[str, str]:
    parts = [p for p in re.split(r"\s+", full_name.strip()) if p]
    if not parts:
        return ("", "")
    first = re.sub(r"[^a-zA-Z]", "", parts[0]).lower()
    last = re.sub(r"[^a-zA-Z]", "", parts[-1]).lower()
    return (first, last)

def generate_email_candidates_from_name(full_name: str, company_domain: str, ranked_patterns: List[str], maximum_candidates: int = 10) -> List[Tuple[str, str]]:
    first, last = _normalize_name_to_first_and_last(full_name)
    if not first or not last:
        return []

    candidates: List[Tuple[str, str]] = []

    def add(local_part: str, pattern_name: str) -> None:
        candidates.append((f"{local_part}@{company_domain}", pattern_name))

    for pattern in ranked_patterns:
        if pattern == "first.last":
            add(f"{first}.{last}", pattern)
        elif pattern == "f.last":
            add(f"{first[:1]}.{last}", pattern)
        elif pattern == "firstl":
            add(f"{first}{last[:1]}", pattern)
        elif pattern == "flast":
            add(f"{first[:1]}{last}", pattern)
        elif pattern == "first.last2":
            add(f"{first}.{last}2", pattern)

        if len(candidates) >= maximum_candidates:
            break

    # dedupe keep order
    seen = set()
    deduped: List[Tuple[str, str]] = []
    for email, pattern_name in candidates:
        if email not in seen:
            seen.add(email)
            deduped.append((email, pattern_name))
    return deduped[:maximum_candidates]
