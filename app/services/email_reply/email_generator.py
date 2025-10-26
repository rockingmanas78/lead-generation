import logging
from typing import Any, Optional, Tuple
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from app.config import OPENAI_API_KEY
from .constants import OPENAI_MODEL
from .tools import (
    get_relevant_information,
    calculate_future_datetime,
    get_current_datetime,
)
from .email_formatter import get_email_chain, format_chain_for_llm
from .token_utils import count_tokens
from .response_parser import parse_email_response
from app.services.database import db
from app.helper.reply_html import text_to_html_reply
from app.helper.reply_brand_wrapper import wrap_reply_body

DEFAULT_FONT   = "Arial, Helvetica, sans-serif"
DEFAULT_COLORS = []  # means: unbranded
DEFAULT_LOGO   = None
DEFAULT_FOOTER = False

llm = ChatOpenAI(api_key=OPENAI_API_KEY, model=OPENAI_MODEL, temperature=0.7)
logger = logging.getLogger(__name__)


# async def generate_email_reply(
#     conversation_id: str,
#     latest_email_content: str,
#     sender_info: dict,
#     config: dict,
#     instructions: str | None = None,
# ) -> dict[str, Any]:
#     email_chain = await get_email_chain(conversation_id)
#     formatted_chain, emails_included = await format_chain_for_llm(email_chain)

#     chain_tokens = count_tokens(formatted_chain)
#     latest_email_tokens = count_tokens(latest_email_content)

#     tools = [
#         get_relevant_information,
#         calculate_future_datetime,
#         get_current_datetime,
#     ]
#     agent_executor = create_react_agent(llm, tools)

#     system_prompt = f"""
#     You are an AI email assistant that helps compose professional email replies. Your tasks are:

#     1. ANALYZE the previous email thread context and the latest email content.
#     2. RETRIEVE relevant company information if needed using the get_relevant_information tool.
#     3. COMPOSE the email reply exactly as it should appear at the moment it will be sent.
#        - Pretend the current date is SCHEDULED_DATE.
#        - Rewrite the timeline so that any events between now and SCHEDULED_DATE are considered already completed.
#        - Do not include phrases implying the message or its contents will be provided later than SCHEDULED_DATE.
#        - If the original request referred to a future month or vague delay, remove or reframe it as a present/past event in the REPLY.
#        - INCLUDE DELIVERABLES: If the latest email explicitly requests a deliverable (e.g., "full product list", "report", "pricing", "attachments"), the assistant MUST include the deliverable content directly in the REPLY body as it should appear when sent on SCHEDULED_DATE.
#          - Do NOT reply with an acknowledgement-only message such as "I have noted your request" or "I will send this later."
#          - If the deliverable requires external data, call get_relevant_information and embed the results. If data is still incomplete, include all available content and clearly label any missing/unverified parts without mentioning scheduling.
#     4. DETERMINE if the email mentions scheduling or timing (like "next week", "in a few days", "in a few months", "later this year").
#     5. If the latest email requests a reply or action at a future time (explicitly or with vague terms such as "in a few days", "in a few months", "later this year"), ALWAYS schedule SCHEDULED_DATE in the future accordingly.
#        - For vague terms, interpret generously in favor of the senderâ€™s timing. Example:
#             "a few months" -> 2 months from today
#             "a few weeks"  -> 2 weeks from today
#             "later this year" -> choose an appropriate date within the year
#     6. If the email mentions future timing, use calculate_future_date to determine when.
#        Example: "next Tuesday" -> Use calculate_future_date("next Tuesday")
#                 "in 3 days" -> Use calculate_future_date("in 3 days")
#     7. The field in SCHEDULED_DATE should always contain the date in ISO 8601 format (UTC).
#        - If the email should be sent immediately, set SCHEDULED_DATE to 5 minutes from current time
#        - Use the get_current_datetime tool to get the current time and add 5 minutes to it.
#     8. Never include the send time or scheduling details inside the email body; those belong only in SCHEDULED_DATE.
#     9. VALIDATION BEFORE RETURN:
#        - If the latest email requested a deliverable, REPLY must contain a concrete version of it (not just placeholders).
#        - REPLY must not contain scheduling phrases like "I will send", "I have scheduled", "I'll provide later", "noted", "will send in".
#        - If any validation fails, regenerate up to two times to correct the REPLY.
#     10. Keep the tone professional, concise, and aligned with the conversation history.
#     11. Do not write the generated email in markdown.

#     Current sender information:
#     - Name: {sender_info.get("name", "Unknown")}
#     - Email: {sender_info.get("email", "Unknown")}

#     LATEST EMAIL TO REPLY TO ({latest_email_tokens} tokens):
#     {latest_email_content}

#     {"SPECIAL INSTRUCTIONS: " + instructions if instructions else ""}

#     CONTEXT MANAGEMENT NOTE: Due to token limits, {emails_included} out of {len(email_chain)} total emails are shown.
#     Focus on the most recent context while being aware this is part of a longer conversation.

#     Format your final response as:
#     SUBJECT: [email subject line]
#     REPLY: [email content]
#     SCHEDULED_DATE: [the date when this should be sent in ISO 8601 format]
#     REASONING: [brief explanation of your approach and any scheduling decisions]
#     """

#     base_prompt_tokens = count_tokens(system_prompt)
#     total_prompt_tokens = base_prompt_tokens + chain_tokens + latest_email_tokens

#     messages = [
#         SystemMessage(content=system_prompt),
#         HumanMessage(
#             content=f"""
#             Please analyze this email thread and generate an appropriate reply to the latest email.

#             PREVIOUS EMAIL THREAD CONTEXT (This thread has {len(email_chain)} total emails, showing {emails_included} most recent ones.):
#             {formatted_chain}

#             Estimated prompt tokens: {total_prompt_tokens}

#             Latest email content: {latest_email_content}

#             Make sure to:
#             1. Consider the available context of the email thread
#             2. Use company information if relevant to the response
#             4. Provide a professional and helpful reply
#             """
#         ),
#     ]

#     try:
#         response_messages = []
#         async for step in agent_executor.astream(
#             {"messages": messages}, config, stream_mode="values"
#         ):
#             response_messages = step["messages"]

#         final_response = (
#             response_messages[-1].content
#             if response_messages
#             else "No response generated"
#         )

#         reply_data = parse_email_response(final_response)

#         print("Parsed reply data:", reply_data)

#         return {
#             "success": True,
#             "subject": reply_data.get(
#                 "subject",
#                 "Re: " + email_chain[0]["subject"] if email_chain else "Re: Your Email",
#             ),
#             "content": reply_data.get("reply", final_response),
#             "scheduled_date": reply_data.get("scheduled_date"),
#             "reasoning": reply_data.get("reasoning", "Standard email reply generated"),
#             "conversation_id": conversation_id,
#             "full_response": final_response,
#             "context_info": {
#                 "total_emails_in_thread": len(email_chain),
#                 "emails_included_in_context": emails_included,
#                 "estimated_prompt_tokens": total_prompt_tokens,
#                 "chain_tokens": chain_tokens,
#             },
#         }

#     except Exception as e:
#         return {
#             "success": False,
#             "error": str(e),
#             "conversation_id": conversation_id,
#             "context_info": {
#                 "total_emails_in_thread": len(email_chain),
#                 "emails_included_in_context": emails_included,
#                 "estimated_prompt_tokens": total_prompt_tokens,
#             },
#         }

# async def generate_email_reply(
#     conversation_id: str,
#     latest_email_content: str,
#     sender_info: dict,
#     config: dict,
#     instructions: str | None = None,
# ) -> dict[str, Any]:
#     """
#     Generate an email reply with BOTH plaintext and HTML.
#     HTML is created server-side from the plaintext reply and optionally wrapped
#     with a light tenant brand (logo/colors/font) for early-stage replies.
#     """
#     # 1) Build thread context for the LLM
#     email_chain = await get_email_chain(conversation_id)
#     formatted_chain, emails_included = await format_chain_for_llm(email_chain)

#     chain_tokens = count_tokens(formatted_chain)
#     latest_email_tokens = count_tokens(latest_email_content)

#     tools = [get_relevant_information, calculate_future_datetime, get_current_datetime]
#     agent_executor = create_react_agent(llm, tools)

#     system_prompt = f"""
#     You are an AI email assistant that helps compose professional email replies. Your tasks are:

#     1. ANALYZE the previous email thread context and the latest email content.
#     2. RETRIEVE relevant company information if needed using the get_relevant_information tool.
#     3. COMPOSE the email reply exactly as it should appear at the moment it will be sent.
#        - Pretend the current date is SCHEDULED_DATE.
#        - Rewrite the timeline so that any events between now and SCHEDULED_DATE are considered already completed.
#        - Do not include phrases implying the message or its contents will be provided later than SCHEDULED_DATE.
#        - INCLUDE DELIVERABLES: If the latest email explicitly requests a deliverable (e.g., "full product list", "report", "pricing", "attachments"), the assistant MUST include the deliverable content directly in the REPLY body as it should appear when sent on SCHEDULED_DATE.
#          - Do NOT reply with an acknowledgement-only message such as "I have noted your request" or "I will send this later."
#          - If the deliverable requires external data, call get_relevant_information and embed the results. If data is still incomplete, include all available content and clearly label any missing/unverified parts without mentioning scheduling.
#     4. DETERMINE if the email mentions scheduling or timing (like "next week", "in a few days", "in a few months", "later this year").
#     5. If the latest email requests a reply or action at a future time (explicitly or with vague terms such as "in a few days", "in a few months", "later this year"), ALWAYS schedule SCHEDULED_DATE in the future accordingly.
#     6. If the email mentions future timing, use calculate_future_datetime to determine when.
#     7. The field in SCHEDULED_DATE should always contain the date in ISO 8601 format (UTC).
#        - If the email should be sent immediately, set SCHEDULED_DATE to 5 minutes from current time
#        - Use the get_current_datetime tool to get the current time and add 5 minutes to it.
#     8. Never include the send time or scheduling details inside the email body; those belong only in SCHEDULED_DATE.
#     9. VALIDATION BEFORE RETURN:
#        - If the latest email requested a deliverable, REPLY must contain a concrete version of it (not just placeholders).
#        - REPLY must not contain scheduling phrases like "I will send", "I have scheduled", "I'll provide later", "noted", "will send in".
#        - If any validation fails, regenerate up to two times to correct the REPLY.
#     10. Keep the tone professional, concise, and aligned with the conversation history.
#     11. Do not write the generated email in markdown.

#     Current sender information:
#     - Name: {sender_info.get("name", "Unknown")}
#     - Email: {sender_info.get("email", "Unknown")}

#     LATEST EMAIL TO REPLY TO ({latest_email_tokens} tokens):
#     {latest_email_content}

#     {"SPECIAL INSTRUCTIONS: " + instructions if instructions else ""}

#     CONTEXT MANAGEMENT NOTE: Due to token limits, {emails_included} out of {len(email_chain)} total emails are shown.
#     Focus on the most recent context while being aware this is part of a longer conversation.

#     Format your final response as:
#     SUBJECT: [email subject line]
#     REPLY: [email content]
#     SCHEDULED_DATE: [the date when this should be sent in ISO 8601 format]
#     REASONING: [brief explanation of your approach and any scheduling decisions]
#     """

#     base_prompt_tokens = count_tokens(system_prompt)
#     total_prompt_tokens = base_prompt_tokens + chain_tokens + latest_email_tokens

#     messages = [
#         SystemMessage(content=system_prompt),
#         HumanMessage(
#             content=f"""
#             Please analyze this email thread and generate an appropriate reply to the latest email.

#             PREVIOUS EMAIL THREAD CONTEXT (This thread has {len(email_chain)} total emails, showing {emails_included} most recent ones.):
#             {formatted_chain}

#             Estimated prompt tokens: {total_prompt_tokens}

#             Latest email content: {latest_email_content}

#             Make sure to:
#             1. Consider the available context of the email thread
#             2. Use company information if relevant to the response
#             3. Provide a professional and helpful reply
#             """
#         ),
#     ]

#     try:
#         response_messages = []
#         async for step in agent_executor.astream(
#             {"messages": messages}, config, stream_mode="values"
#         ):
#             response_messages = step["messages"]

#         final_response = response_messages[-1].content if response_messages else ""
#         reply_data = parse_email_response(final_response)

#         plaintext_reply = reply_data.get("reply", final_response).strip()
#         subject = reply_data.get(
#             "subject",
#             "Re: " + (email_chain[0]["subject"] if email_chain else "Your Email"),
#         )
#         scheduled_date = reply_data.get("scheduled_date")
#         reasoning = reply_data.get("reasoning", "Standard email reply generated")

#         # 2) Create HTML from plaintext (autolink, paragraphs, lists)
#         tenant_id = config.get("configurable", {}).get("tenant_id")
#         try:
#             font_stack, brand_colors, logo_url, show_footer = await get_tenant_reply_theme(tenant_id)
#         except Exception as e:
#             logger.warning("Falling back to default reply theme (tenant=%r). Error: %s", tenant_id, e)
#             font_stack, brand_colors, logo_url, show_footer = (
#                 "Arial, Helvetica, sans-serif", [], None, False
#             )

#         base_html = text_to_html_reply(
#             plaintext_reply,
#             link_color="#0B69FF",
#             font_stack=font_stack or "Arial, Helvetica, sans-serif",
#         )

#         # 3) Optional light brand wrapper (apply on early-stage replies)
#         apply_brand = emails_included <= 2  # keep replies human after the first couple
#         if apply_brand and (brand_colors or logo_url):
#             # Extract inner body from base_html for wrapping
#             inner = base_html.split("<body", 1)[1].split(">", 1)[1].rsplit("</body>", 1)[0]
#             html_reply = wrap_reply_body(
#                 inner_html=inner,
#                 logo_url=logo_url,
#                 font_stack=font_stack or "Arial, Helvetica, sans-serif",
#                 brand_colors=brand_colors or [],
#                 show_footer=bool(show_footer),
#             )
#         else:
#             html_reply = base_html

#         return {
#             "success": True,
#             "subject": subject,
#             "content": plaintext_reply,     # text/plain
#             "html_content": html_reply,     # text/html
#             "scheduled_date": scheduled_date,
#             "reasoning": reasoning,
#             "conversation_id": conversation_id,
#             "full_response": final_response,
#             "context_info": {
#                 "total_emails_in_thread": len(email_chain),
#                 "emails_included_in_context": emails_included,
#                 "estimated_prompt_tokens": total_prompt_tokens,
#                 "chain_tokens": chain_tokens,
#             },
#         }

#     except Exception as e:
#         logger.exception("generate_email_reply failed")
#         return {
#             "success": False,
#             "error": str(e),
#             "conversation_id": conversation_id,
#             "context_info": {
#                 "total_emails_in_thread": len(email_chain),
#                 "emails_included_in_context": emails_included,
#                 "estimated_prompt_tokens": total_prompt_tokens,
#             },
#         }

async def generate_email_reply(
    conversation_id: str,
    latest_email_content: str,
    sender_info: dict,
    config: dict,
    instructions: str | None = None,
) -> dict[str, Any]:
    email_chain = await get_email_chain(conversation_id)
    formatted_chain, emails_included = await format_chain_for_llm(email_chain)

    chain_tokens = count_tokens(formatted_chain)
    latest_email_tokens = count_tokens(latest_email_content)

    tools = [get_relevant_information, calculate_future_datetime, get_current_datetime]
    agent_executor = create_react_agent(llm, tools)

    system_prompt = f"""
    You are an AI email assistant that helps compose professional email replies. Your tasks are:

    1. ANALYZE the previous email thread context and the latest email content.
    2. RETRIEVE relevant company information if needed using the get_relevant_information tool.
    3. COMPOSE the email reply exactly as it should appear at the moment it will be sent.
       - Pretend the current date is SCHEDULED_DATE.
       - Rewrite the timeline so that any events between now and SCHEDULED_DATE are considered already completed.
       - Do not include phrases implying the message or its contents will be provided later than SCHEDULED_DATE.
       - INCLUDE DELIVERABLES: If the latest email explicitly requests a deliverable (e.g., "full product list", "report", "pricing", "attachments"), include the deliverable content directly in the REPLY body as it should appear when sent on SCHEDULED_DATE.
         - Do NOT reply with an acknowledgement-only message.
    4. If the email implies future timing, compute SCHEDULED_DATE with the provided tools.
    5. SCHEDULED_DATE must be ISO 8601 (UTC). If immediate, set to 5 minutes from now via get_current_datetime + 5 minutes.
    6. Do not include scheduling details in the reply body.
    7. Validation: deliverables present if requested; no "I will send later" phrasing.
    8. Tone: professional, concise, aligned with the thread. No markdown.

    Current sender:
    - Name: {sender_info.get("name", "Unknown")}
    - Email: {sender_info.get("email", "Unknown")}

    LATEST EMAIL TO REPLY TO ({latest_email_tokens} tokens):
    {latest_email_content}

    {"SPECIAL INSTRUCTIONS: " + instructions if instructions else ""}

    CONTEXT: {emails_included} of {len(email_chain)} emails shown due to token limits.

    Format your final response as:
    SUBJECT: [email subject line]
    REPLY: [email content]
    SCHEDULED_DATE: [ISO 8601 UTC]
    REASONING: [brief rationale]
    """

    base_prompt_tokens = count_tokens(system_prompt)
    total_prompt_tokens = base_prompt_tokens + chain_tokens + latest_email_tokens

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=f"""
            Analyze this thread and generate a professional reply.

            PREVIOUS EMAIL THREAD (showing {emails_included} of {len(email_chain)}):
            {formatted_chain}

            Estimated prompt tokens: {total_prompt_tokens}

            Latest email content: {latest_email_content}

            Requirements:
            - Consider context
            - Use company details if relevant
            - Provide a concise, helpful reply
            """
        ),
    ]

    try:
        response_messages = []
        async for step in agent_executor.astream(
            {"messages": messages}, config, stream_mode="values"
        ):
            response_messages = step["messages"]

        final_response = response_messages[-1].content if response_messages else ""
        reply_data = parse_email_response(final_response)

        plaintext_reply = (reply_data.get("reply", final_response) or "").strip()
        subject = reply_data.get(
            "subject",
            "Re: " + (email_chain[0]["subject"] if email_chain else "Your Email"),
        )
        scheduled_date = reply_data.get("scheduled_date")
        reasoning = reply_data.get("reasoning", "Standard email reply generated")

        # Build HTML from plaintext
        tenant_id = config.get("configurable", {}).get("tenant_id")
        try:
            font_stack, brand_colors, logo_url, show_footer = await get_tenant_reply_theme(tenant_id)
        except Exception as e:
            logger.warning("Theme fetch failed (tenant=%r). Fallbacks used. %s", tenant_id, e)
            font_stack, brand_colors, logo_url, show_footer = ("Arial, Helvetica, sans-serif", [], None, False)

        base_html = text_to_html_reply(
            plaintext_reply,
            link_color="#0B69FF",
            font_stack=font_stack or "Arial, Helvetica, sans-serif",
        )

        # optional branding only for very early threads
        apply_brand = emails_included <= 2 and (brand_colors or logo_url)
        if apply_brand:
            inner = base_html.split("<body", 1)[1].split(">", 1)[1].rsplit("</body>", 1)[0]
            html_reply = wrap_reply_body(
                inner_html=inner,
                logo_url=logo_url,
                font_stack=font_stack or "Arial, Helvetica, sans-serif",
                brand_colors=brand_colors or [],
                show_footer=bool(show_footer),
            )
        else:
            html_reply = base_html

        return {
            "success": True,
            "subject": subject,
            "content": plaintext_reply,
            "html_content": html_reply,
            "scheduled_date": scheduled_date,
            "reasoning": reasoning,
            "conversation_id": conversation_id,
            "full_response": final_response,
            "context_info": {
                "total_emails_in_thread": len(email_chain),
                "emails_included_in_context": emails_included,
                "estimated_prompt_tokens": total_prompt_tokens,
                "chain_tokens": chain_tokens,
            },
        }

    except Exception as e:
        logger.exception("generate_email_reply failed")
        return {
            "success": False,
            "error": str(e),
            "conversation_id": conversation_id,
            "context_info": {
                "total_emails_in_thread": len(email_chain),
                "emails_included_in_context": emails_included,
                "estimated_prompt_tokens": total_prompt_tokens,
            },
        }

async def handle_email_reply_request(
    conversation_id: str,
    latest_email_content: str,
    sender_info: dict[str, str],
    recipients: list[str],
    tenant_id: str,
    instructions: str | None = None,
) -> dict:
    config = {"configurable": {"tenant_id": tenant_id}}

    reply_result = await generate_email_reply(
        conversation_id=conversation_id,
        latest_email_content=latest_email_content,
        sender_info=sender_info,
        config=config,
        instructions=instructions,
    )

    print("Email reply generation result:", reply_result)

    if not reply_result["success"]:
        return reply_result

    return {**reply_result, "recipients": recipients}

def _pick(obj, *names):
    """Return the first present value among possible attribute or dict keys."""
    for n in names:
        # attribute access
        if hasattr(obj, n):
            val = getattr(obj, n)
            if val is not None:
                return val
        # dict-style access (Prisma client / pydantic models sometimes behave like dicts)
        if isinstance(obj, dict) and n in obj and obj[n] is not None:
            return obj[n]
    return None

def _ensure_color_list(value) -> list:
    """Accept list, JSON string, or anything else -> list or []"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            # Try parsing '["#111","#fff"]'
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            # Try comma-separated string "#111,#fff,#eee"
            parts = [p.strip() for p in value.split(",") if p.strip()]
            return parts if parts else []
    return []

async def get_tenant_reply_theme(tenant_id: Optional[str]) -> Tuple[str, list, Optional[str], bool]:
    """
    Returns (font_stack, brand_colors, logo_url, show_footer).
    Safe defaults if no template or fields missing.
    """
    if not tenant_id:
        return DEFAULT_FONT, DEFAULT_COLORS, DEFAULT_LOGO, DEFAULT_FOOTER

    # Get the most recent template for this tenant (or choose your own selection rule)
    tpl = await db.emailtemplate.find_first(
        where={"tenantId": tenant_id},
        order={"createdAt": "desc"},
    )

    if not tpl:
        return DEFAULT_FONT, DEFAULT_COLORS, DEFAULT_LOGO, DEFAULT_FOOTER

    # Try both snake_case and camelCase
    font_stack  = _pick(tpl, "font_family", "fontFamily", "font_stack", "font") or DEFAULT_FONT
    brand_raw   = _pick(tpl, "brand_colors", "brandColors")
    brand_colors = _ensure_color_list(brand_raw)
    logo_url    = _pick(tpl, "logo_url", "logoUrl", "logo") or DEFAULT_LOGO

    show_footer_val = _pick(tpl, "show_footer", "showFooter")
    show_footer = bool(show_footer_val) if show_footer_val is not None else DEFAULT_FOOTER

    return font_stack, brand_colors, logo_url, show_footer

