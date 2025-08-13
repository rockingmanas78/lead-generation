import re


def parse_email_response(response: str) -> dict[str, str]:
    result = {}

    subject_match = re.search(r"SUBJECT:\s*(.+?)(?:\n|$)", response, re.IGNORECASE)
    if subject_match:
        result["subject"] = subject_match.group(1).strip()

    reply_match = re.search(
        r"REPLY:\s*(.+?)(?=SCHEDULED_DATE:|REASONING:|$)",
        response,
        re.IGNORECASE | re.DOTALL,
    )
    if reply_match:
        result["reply"] = reply_match.group(1).strip()

    date_match = re.search(r"SCHEDULED_DATE:\s*(.+?)(?:\n|$)", response, re.IGNORECASE)
    if date_match:
        result["scheduled_date"] = date_match.group(1).strip()

    reasoning_match = re.search(
        r"REASONING:\s*(.+?)$", response, re.IGNORECASE | re.DOTALL
    )
    if reasoning_match:
        result["reasoning"] = reasoning_match.group(1).strip()

    return result
