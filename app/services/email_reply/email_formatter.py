from app.config import OPENAI_MODEL, OPENAI_API_KEY
from app.services.database import db
from .constants import MAX_EMAIL_CHAIN_TOKENS
from .token_utils import count_tokens, tokenizer
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain_core.output_parsers.string import StrOutputParser
import asyncio
import logging

logger = logging.getLogger(__name__)

OPENAI_SUMMARIZE_MAX_TOKENS = 500


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


async def format_chain_for_llm(
    email_chain: list[dict[str, str]], max_tokens: int = MAX_EMAIL_CHAIN_TOKENS
) -> tuple[str, int]:
    if not email_chain:
        return "", 0

    formatted_chain: list[str] = []
    total_tokens = 0
    emails_included = 0

    latest_email = email_chain[-1]
    latest_formatted = format_single_email(latest_email)
    latest_tokens = count_tokens(latest_formatted)

    if latest_tokens <= max_tokens:
        formatted_chain.append(latest_formatted)
        total_tokens += latest_tokens
        emails_included = 1

        remaining_emails = email_chain[:-1]
        emails_to_summarize = []

        for email in reversed(remaining_emails):
            email_formatted = format_single_email(email)
            email_tokens = count_tokens(email_formatted)

            if total_tokens + email_tokens <= max_tokens:
                formatted_chain.insert(0, email_formatted)
                total_tokens += email_tokens
                emails_included += 1
            else:
                emails_to_summarize.insert(0, email)

        if emails_to_summarize:
            summary_tokens_available = max_tokens - total_tokens - 100
            if summary_tokens_available > 50:
                summary = await create_email_summary(
                    emails_to_summarize, summary_tokens_available
                )
                if summary:
                    formatted_chain.insert(0, summary)
                    total_tokens += count_tokens(summary)

    else:
        truncated_email = truncate_email_content(latest_email, max_tokens)
        formatted_chain.append(format_single_email(truncated_email))
        emails_included = 1

    chain_text = "\n".join(formatted_chain)

    total_emails = len(email_chain)
    if emails_included < total_emails and not any(
        "SUMMARY:" in part for part in formatted_chain
    ):
        summary_note = f"\n[NOTE: Showing {emails_included} most recent emails out of {total_emails} total emails in this conversation]\n"
        chain_text = summary_note + chain_text

    return chain_text, emails_included


async def create_email_summary(emails: list[dict[str, str]], max_tokens: int) -> str:
    if not emails:
        return ""

    try:
        emails_for_summary = []
        for i, email in enumerate(emails, 1):
            direction = "INBOUND" if email.get("direction") == "inbound" else "OUTBOUND"
            email_text = f"""Email {i} ({direction}):
            From: {email.get("sender_name", "")} <{email.get("sender", "")}>
            Subject: {email.get("subject", "")}
            Date: {email.get("timestamp", "")}
            Content: {email.get("content", "")[:500]}...
"""
            emails_for_summary.append(email_text)

        emails_content = "\n".join(emails_for_summary)

        target_summary_words = int(max_tokens * 0.7 / 1.3)

        summary = await generate_llm_summary(emails_content, target_summary_words)

        if summary:
            formatted_summary = f"SUMMARY: {summary}\n---\n"

            if count_tokens(formatted_summary) <= max_tokens:
                return formatted_summary
            else:
                shorter_target = int(target_summary_words * 0.6)
                shorter_summary = await generate_llm_summary(
                    emails_content, shorter_target
                )
                if shorter_summary:
                    formatted_summary = f"SUMMARY: {shorter_summary}\n---\n"
                    if count_tokens(formatted_summary) <= max_tokens:
                        return formatted_summary

    except Exception as e:
        logger.error(f"Error generating LLM summary: {e}")

    return "Could not generate summary"


async def generate_llm_summary(emails_content: str, target_words: int) -> str:
    try:
        llm = ChatOpenAI(
            api_key=OPENAI_API_KEY,
            model=OPENAI_MODEL,
            temperature=0.4,
            timeout=30,
            max_completion_tokens=min(target_words * 2, OPENAI_SUMMARIZE_MAX_TOKENS),
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """You are an expert at summarizing email conversations. Create a concise summary that captures:
                    1. The main topics and decisions discussed
                    2. Key participants and their roles
                    3. Important dates, deadlines, or action items
                    4. Current status or outcomes

                    Keep the summary to approximately {target_words} words. Focus on information that would be most relevant for understanding the context of future emails in this conversation.

                    Return only the summary text without any prefixes like "Summary:" or "Here's a summary:".""",
                ),
                (
                    "human",
                    """Please summarize the following email conversation:

                    {emails_content}

                    Provide a concise summary that captures the essential context and key points.""",
                ),
            ]
        )

        chain = prompt | llm | StrOutputParser()

        summary = await chain.ainvoke(
            {
                "emails_content": emails_content,
                "target_words": target_words,
            }
        )

        return summary.strip()

    except asyncio.TimeoutError:
        logger.error("LLM summary generation timed out")
        return ""
    except Exception as e:
        logger.error(f"Error calling LLM for summary: {e}")
        return ""


def format_single_email(email: dict[str, str]) -> str:
    direction_indicator = (
        "INBOUND" if email.get("direction") == "inbound" else "OUTBOUND"
    )

    return f"""
    {direction_indicator}
    FROM: {email["sender_name"]} <{email["sender"]}>
    TO: {email["recipients"]}
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
    TO: {email["recipients"]}
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

    if len(encoded_content) > available_tokens - 20:
        start_tokens = int((available_tokens - 20) * 0.6)
        end_tokens = int((available_tokens - 20) * 0.2)

        start_content = tokenizer.decode(encoded_content[:start_tokens])
        end_content = (
            tokenizer.decode(encoded_content[-end_tokens:]) if end_tokens > 0 else ""
        )

        if end_content:
            truncated_content = (
                f"{start_content}\n\n[... Content truncated ...]\n\n{end_content}"
            )
        else:
            truncated_content = (
                f"{start_content}\n\n[... Content truncated for length ...]"
            )
    else:
        truncated_tokens = encoded_content[: available_tokens - 20]
        truncated_content = tokenizer.decode(truncated_tokens)
        truncated_content += "\n\n[... Content truncated for length ...]"

    email_copy["content"] = truncated_content
    return email_copy
