import re
from typing import List

LOCATION_HINT_REGEX = r"(?:in|near|around|from|for|within|across|based in)\s+"
CAPITALIZED_SEQUENCE_REGEX = r"(?:[A-Z][\w'&.-]+(?:\s+[A-Z][\w'&.-]+){0,3})"
QUOTED_LOCATION_REGEX = r"\"([^\"]{2,80})\"|'([^']{2,80})'"

def extract_locations(user_prompt: str) -> List[str]:
    """
    Very light, dependency-free location extractor from the user's prompt.
    Returns up to 5 deduplicated locations (case-insensitive).
    """
    text = user_prompt.strip()
    found_locations: List[str] = []

    # Hinted, capitalized segments: "agencies in New Delhi", "firms near San Francisco Bay"
    for match in re.finditer(LOCATION_HINT_REGEX + CAPITALIZED_SEQUENCE_REGEX, text, flags=re.IGNORECASE):
        fragment = match.group(0)
        cleaned = re.sub(LOCATION_HINT_REGEX, "", fragment, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if cleaned:
            found_locations.append(cleaned)

    # Quoted locations: "paris", 'tokyo', "São Paulo"
    for match in re.finditer(QUOTED_LOCATION_REGEX, text):
        candidate = next(group for group in match.groups() if group)
        if re.search(r"[A-Za-z]", candidate):
            found_locations.append(candidate.strip())

    # Comma-style: "Mumbai, India", "Paris, FR"
    for match in re.finditer(r"\b([A-Z][\w.&'-]+(?:\s+[A-Z][\w.&'-]+){0,2}),\s*([A-Za-z]{2,})\b", text):
        found_locations.append(f"{match.group(1)} {match.group(2)}")

    # Tail: "... in india", "... in delhi ncr"
    tail_match = re.search(r"(?:\bin\s+)([a-z][\w\s.&'-]{2,50})$", text, flags=re.IGNORECASE)
    if tail_match:
        found_locations.append(tail_match.group(1).strip())

    # Normalize and dedupe case-insensitively
    normalized: List[str] = [re.sub(r"\s+", " ", s).strip(" ,") for s in found_locations]
    unique: List[str] = []
    seen_lower: set[str] = set()
    for item in normalized:
        key = item.lower()
        if key not in seen_lower:
            seen_lower.add(key)
            unique.append(item)

    return unique[:5]



# # app/services/location.py
# import re
# from typing import List

# LOC_HINTS = r"(?:in|near|around|from|for|within|across|based in)\s+"

# # very light heuristic: grab up to 4 capitalized tokens after a hint
# CAP_SEQ = r"(?:[A-Z][\w'&.-]+(?:\s+[A-Z][\w'&.-]+){0,3})"

# # also allow quoted locations: "new delhi", "bengaluru", etc.
# QUOTED = r"\"([^\"]{2,80})\"|'([^']{2,80})'"

# def extract_locations(prompt: str) -> List[str]:
#     text = prompt.strip()

#     locs = set()

#     # 1) Hinted, capitalized segments:  e.g. "agencies in New Delhi", "firms near San Francisco Bay"
#     for m in re.finditer(LOC_HINTS + CAP_SEQ, text, flags=re.IGNORECASE):
#         frag = m.group(0)
#         # keep the part after the hint
#         cleaned = re.sub(LOC_HINTS, "", frag, flags=re.IGNORECASE).strip()
#         # normalize spacing
#         cleaned = re.sub(r"\s+", " ", cleaned)
#         if cleaned:
#             locs.add(cleaned)

#     # 2) Explicit quoted locations: "paris", 'tokyo', "São Paulo"
#     for m in re.finditer(QUOTED, text):
#         candidate = next(g for g in m.groups() if g)
#         # if quoted piece looks like a place (contains letter)
#         if re.search(r"[A-Za-z]", candidate):
#             locs.add(candidate.strip())

#     # 3) Comma-style place hints: e.g. "Mumbai, India", "Paris, FR"
#     for m in re.finditer(r"\b([A-Z][\w.&'-]+(?:\s+[A-Z][\w.&'-]+){0,2}),\s*([A-Za-z]{2,})\b", text):
#         locs.add(f"{m.group(1)} {m.group(2)}")

#     # 4) If user writes obvious geo words at end: "... in india", "... in delhi ncr"
#     for m in re.finditer(r"(?:\bin\s+)([a-z][\w\s.&'-]{2,50})$", text, flags=re.IGNORECASE):
#         locs.add(m.group(1).strip())

#     # Keep short, relevant list
#     out = [re.sub(r"\s+", " ", s).strip(" ,") for s in locs]
#     # de-dupe case-insensitively
#     seen = set()
#     uniq = []
#     for s in out:
#         k = s.lower()
#         if k not in seen:
#             seen.add(k)
#             uniq.append(s)
#     return uniq[:5]
