import re
from bs4 import BeautifulSoup
from typing import Dict, List

def extract_clean_text(html: str) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style']):
        tag.decompose()
    return ' '.join(soup.stripped_strings)

def find_empty_fields(data: Dict, parent: str = '') -> List[str]:
    empty = []
    for k, v in data.items():
        if not v:
            empty.append(f"{parent}.{k}" if parent else k)
    return empty

def merge_data(old: Dict, new: Dict) -> Dict:
    for k in new:
        if not old.get(k):
            old[k] = new[k]
    return old

def clean_phone_numbers(phone_list: List[str]) -> List[str]:
    cleaned = []

    for raw in phone_list:
        digits = re.sub(r"[^\d+]", "", raw)

        if re.fullmatch(r"\+?\d{8,15}", digits):
            if not digits.startswith('+') and len(digits) >= 10:
                digits = '+' + digits
            cleaned.append(digits)

    return list(set(cleaned))
