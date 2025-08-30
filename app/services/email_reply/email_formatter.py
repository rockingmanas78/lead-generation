from app.services.database import db
from .constants import MAX_EMAIL_CHAIN_TOKENS
from .token_utils import count_tokens, tokenizer


async def get_email_chain(
    conversation_id: str, limit: int = 50
) -> list[dict[str, str]]:
    emails = await db.emailmessage.find_many(
        where={"conversationId": conversation_id},
        order={"createdAt": "asc"},
        take=limit,
    )
    return [format_email(email) for email in emails]


def format_email(email) -> dict[str, str]:
    return {
        "id": email.id,
        "sender": email.from_[0] if email.from_ else "",
        "sender_name": email.from_[0].split("<")[0].strip()
        if email.from_ and "<" in email.from_[0]
        else "",
        "recipients": " ".join(email.to + email.cc + email.bcc),
        "subject": email.subject or "",
        "content": email.text or email.html or "",
        "timestamp": (email.sentAt or email.receivedAt or email.createdAt).isoformat(),
        "direction": email.direction.lower(),
        "provider_message_id": email.providerMessageId,
    }


def format_chain_for_llm(
    email_chain: list[dict[str, str]], max_tokens: int = MAX_EMAIL_CHAIN_TOKENS
) -> tuple[str, int]:
    if not email_chain:
        return "", 0

    formatted_chain: list[str] = []
    total_tokens = 0
    emails_included = 0

    latest_email = email_chain[-1] if email_chain else None
    if latest_email:
        latest_formatted = format_single_email(latest_email)
        latest_tokens = count_tokens(latest_formatted)

        if latest_tokens <= max_tokens:
            formatted_chain.append(latest_formatted)
            total_tokens += latest_tokens
            emails_included = 1

            for email in reversed(email_chain[:-1]):
                email_formatted = format_single_email(email)
                email_tokens = count_tokens(email_formatted)

                if total_tokens + email_tokens <= max_tokens:
                    formatted_chain.insert(0, email_formatted)
                    total_tokens += email_tokens
                    emails_included += 1
                else:
                    break
        else:
            truncated_email = truncate_email_content(latest_email, max_tokens)
            formatted_chain.append(format_single_email(truncated_email))
            emails_included = 1

    chain_text = "\n".join(formatted_chain)

    total_emails = len(email_chain)
    if emails_included < total_emails:
        summary = f"\n[NOTE: Showing {emails_included} most recent emails out of {total_emails} total emails in this conversation for context management]\n"
        chain_text = summary + chain_text

    return chain_text, emails_included


def format_single_email(email: dict[str, str]) -> str:
    direction_indicator = (
        "INBOUND" if email.get("direction") == "inbound" else "OUTBOUND"
    )

    return f"""
    {direction_indicator}
    FROM: {email["sender_name"]} <{email["sender"]}>
    TO: {", ".join(email["recipients"])}
    DATE: {email["timestamp"]}
    SUBJECT: {email["subject"]}

    {email["content"]}
    ---
    """


def truncate_email_content(email: dict[str, str], max_tokens: int) -> dict[str, str]:
    email_copy = email.copy()

    direction_indicator = (
        "INBOUND " if email.get("direction") == "inbound" else "OUTBOUND "
    )

    metadata = f"""
    {direction_indicator}
    FROM: {email["sender_name"]} <{email["sender"]}>
    TO: {", ".join(email["recipients"])}
    DATE: {email["timestamp"]}
    SUBJECT: {email["subject"]}

    ---
    """
    metadata_tokens = count_tokens(metadata)
    available_tokens = max_tokens - metadata_tokens - 50

    if available_tokens <= 0:
        email_copy["subject"] = (
            email["subject"][:50] + "..."
            if len(email["subject"]) > 50
            else email["subject"]
        )
        email_copy["content"] = "[Content truncated due to length]"
        return email_copy

    content = email["content"]
    content_tokens = count_tokens(content)

    if content_tokens <= available_tokens:
        return email_copy

    encoded_content = tokenizer.encode(content)
    truncated_tokens = encoded_content[: available_tokens - 20]
    truncated_content = tokenizer.decode(truncated_tokens)

    email_copy["content"] = (
        truncated_content + "\n\n[... Content truncated for length ...]"
    )
    return email_copy
