import logging
from datetime import datetime
from app.services.database import db
from app.schemas import GeneratedEmailRequest, GeneratedEmailResponse
from .email_generator import handle_email_reply_request

logger = logging.getLogger(__name__)

async def store_generated_email(
    req: GeneratedEmailRequest,
    tenant_id: str,
) -> GeneratedEmailResponse:
    sender_info = {"name": req.sender_name, "email": req.sender_email}

    reply_result = await handle_email_reply_request(
        conversation_id=req.conversation_id,
        latest_email_content=req.latest_email,
        sender_info=sender_info,
        recipients=req.recipient_emails,
        tenant_id=tenant_id,
        instructions="",
    )

    if not reply_result.get("success"):
        logger.error("Could not generate the email reply: %s", reply_result.get("error"))
        raise RuntimeError("AI reply generation failed")

    # Parse/normalize scheduled_date (best-effort; leave None if parse fails)
    scheduled_date = None
    raw_dt = reply_result.get("scheduled_date")
    if raw_dt:
        try:
            # supports "YYYY-MM-DDTHH:MM:SS[.ffffff][+/-HH:MM]"
            scheduled_date = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
        except Exception as e:
            logger.info("scheduled_date parse failed (%r): %s", raw_dt, e)
            # If your business logic requires strict scheduling, raise 400:
            # raise HTTPException(status_code=400, detail="Invalid scheduled_date")
            scheduled_date = None

    # Fetch conversation (plusToken/threadKey)
    conv = await db.conversation.find_unique(where={"id": req.conversation_id})
    plus_token = getattr(conv, "threadKey", None) if conv else None

    # ---- FK guards (campaign, lead) -----------------------------------------
    # If these are REQUIRED in your Prisma schema, raise a 400 if missing.
    # If OPTIONAL, we simply omit the field when we can't validate.
    campaign_id_to_use = None
    if req.campaign_id:
        campaign = await db.emailcampaign.find_first(
            where={"id": req.campaign_id, "tenantId": tenant_id}
        )
        if campaign:
            campaign_id_to_use = req.campaign_id
        else:
            logger.warning("Campaign %r not found for tenant %r; omitting.", req.campaign_id, tenant_id)
            # If required -> raise:
            # raise HTTPException(status_code=400, detail="Invalid campaign_id")

    lead_id_to_use = None
    if req.lead_id:
        lead = await db.lead.find_first(
            where={"id": req.lead_id, "tenantId": tenant_id}
        )
        if lead:
            lead_id_to_use = req.lead_id
        else:
            logger.warning("Lead %r not found for tenant %r; omitting.", req.lead_id, tenant_id)
            # If required -> raise:
            # raise HTTPException(status_code=400, detail="Invalid lead_id")

    # Build data dict conditionally to avoid FK violations
    email_data = {
        "tenantId": tenant_id,
        "conversationId": req.conversation_id,
        "direction": "OUTBOUND",
        "plusToken": plus_token,
        "providerMessageId": f"generated-{datetime.now().isoformat()}",
        "subject": reply_result["subject"],
        "from_": [sender_info["email"]],
        "to": req.recipient_emails,
        "cc": [],
        "bcc": [],
        "text": reply_result.get("content") or "",
        "html": reply_result.get("html_content"),  # optional html part
        "sentAt": scheduled_date,
        "createdAt": datetime.now(),
    }

    if campaign_id_to_use is not None:
        email_data["campaignId"] = campaign_id_to_use
    if lead_id_to_use is not None:
        email_data["leadId"] = lead_id_to_use

    # Create the email message
    email_message = await db.emailmessage.create(email_data)

    # GeneratedEmail record (no FKs here beyond emailMessageId)
    await db.generatedemail.create(
        {
            "emailMessageId": email_message.id,
            "subject": reply_result["subject"],
            "content": reply_result.get("content") or "",
            "scheduledDate": scheduled_date,
        }
    )

    # Bulk job only if campaign is valid (else skip)
    if campaign_id_to_use is not None:
        bulk_job = await db.bulkemailjob.create(
            {
                "tenantId": tenant_id,
                "campaignId": campaign_id_to_use,
                "rateLimit": 1,
                "total": 1,
                "nextProcessTime": scheduled_date,
                "createdAt": datetime.now(),
            }
        )
        # Only create join row if we have a valid lead too
        if lead_id_to_use is not None:
            await db.bulkemailjoblead.create(
                {
                    "jobId": bulk_job.id,
                    "leadId": lead_id_to_use,
                }
            )

    # Touch conversation timestamp
    await db.conversation.update(
        where={"id": req.conversation_id},
        data={"lastMessageAt": datetime.now()},
    )

    return GeneratedEmailResponse(response="Reply generated")

# async def store_generated_email(
#     req: GeneratedEmailRequest,
#     tenant_id: str,
# ) -> GeneratedEmailResponse:
#     """
#     Persists the generated reply as an EmailMessage + GeneratedEmail rows.
#     Stores BOTH text and html parts (multipart/alternative downstream).
#     """
#     sender_info = {"name": req.sender_name, "email": req.sender_email}

#     reply_result = await handle_email_reply_request(
#         conversation_id=req.conversation_id,
#         latest_email_content=req.latest_email,
#         sender_info=sender_info,
#         recipients=req.recipient_emails,
#         tenant_id=tenant_id,
#         instructions="",
#     )

#     if not reply_result.get("success"):
#         logger.error("Could not generate the email reply: %s", reply_result.get("error"))
#         raise RuntimeError("AI reply generation failed")

#     # Parse scheduled_date (if present)
#     scheduled_date = None
#     if reply_result.get("scheduled_date"):
#         try:
#             scheduled_date = datetime.fromisoformat(reply_result["scheduled_date"])
#         except Exception as e:
#             logger.info(
#                 "Could not parse scheduled_date to isoformat, scheduled_date=%r, error=%s",
#                 reply_result["scheduled_date"], e
#             )
#             # Decide: either ignore (send immediately) or raise. Keeping your behavior = raise:
#             raise

#     # Fetch conversation to derive plusToken (threadKey)
#     conv = await db.conversation.find_unique(where={"id": req.conversation_id})
#     plus_token = getattr(conv, "threadKey", None) if conv else None

#     # Create EmailMessage (store BOTH text and html)
#     email_message = await db.emailmessage.create(
#         {
#             "tenantId": tenant_id,
#             "conversationId": req.conversation_id,
#             "direction": "OUTBOUND",
#             "plusToken": plus_token,
#             "providerMessageId": f"generated-{datetime.now().isoformat()}",
#             "subject": reply_result["subject"],
#             "from_": [sender_info["email"]],
#             "to": req.recipient_emails,
#             "cc": [],
#             "bcc": [],
#             "text": reply_result.get("content") or "",        # plaintext
#             "html": reply_result.get("html_content"),         # HTML (may be None)
#             "sentAt": scheduled_date,
#             "createdAt": datetime.now(),
#             "campaignId": req.campaign_id,
#             "leadId": req.lead_id,
#         }
#     )

#     # Create GeneratedEmail record
#     await db.generatedemail.create(
#         {
#             "emailMessageId": email_message.id,
#             "subject": reply_result["subject"],
#             "content": reply_result.get("content") or "",
#             "scheduledDate": scheduled_date,
#         }
#     )

#     # Create a tiny bulk job scaffolding (as in your code)
#     bulk_job = await db.bulkemailjob.create(
#         {
#             "tenantId": tenant_id,
#             "campaignId": req.campaign_id,
#             "rateLimit": 1,
#             "total": 1,
#             "nextProcessTime": scheduled_date,
#             "createdAt": datetime.now(),
#         }
#     )

#     await db.bulkemailjoblead.create({"jobId": bulk_job.id, "leadId": req.lead_id})

#     await db.conversation.update(
#         where={"id": req.conversation_id}, data={"lastMessageAt": datetime.now()}
#     )

#     return GeneratedEmailResponse(response="Reply generated")
# # async def store_generated_email(
#     req: GeneratedEmailRequest,
#     tenant_id: str,
# ) -> GeneratedEmailResponse:
#     sender_info = {"name": req.sender_name, "email": req.sender_email}

#     reply_result = await handle_email_reply_request(
#         conversation_id=req.conversation_id,
#         latest_email_content=req.latest_email,
#         sender_info=sender_info,
#         recipients=req.recipient_emails,
#         tenant_id=tenant_id,
#         instructions="",
#     )

#     if not reply_result["success"]:
#         logger.error("Could not generate the email reply.")
#         raise RuntimeError("AI reply generation failed")

#     try:
#         scheduled_date = None
#         if reply_result.get("scheduled_date"):
#             try:
#                 scheduled_date = datetime.fromisoformat(reply_result["scheduled_date"])
#             except Exception as e:
#                 logger.info(
#                     f"Could not parse the scheduled date to isoformat, scheduled_date: {reply_result['scheduled_date']}, {e}"
#                 )
#                 raise

#         # Fetch conversation to derive plusToken (threadKey)
#         conv = await db.conversation.find_unique(
#             where={"id": req.conversation_id}
#         )
#         plus_token = getattr(conv, "threadKey", None) if conv else None

#         email_message = await db.emailmessage.create(
#             {
#                 "tenantId": tenant_id,
#                 "conversationId": req.conversation_id,
#                 "direction": "OUTBOUND",
#                 "plusToken": plus_token,
#                 "providerMessageId": f"generated-{datetime.now().isoformat()}",
#                 "subject": reply_result["subject"],
#                 "from_": [sender_info["email"]],
#                 "to": req.recipient_emails,
#                 "cc": [],
#                 "bcc": [],
#                 "text": reply_result["content"],
#                 "html": None,
#                 "sentAt": scheduled_date,
#                 "createdAt": datetime.now(),
#                 "campaignId": req.campaign_id,
#                 "leadId": req.lead_id,
#             }
#         )

#         await db.generatedemail.create(
#             {
#                 "emailMessageId": email_message.id,
#                 "subject": reply_result["subject"],
#                 "content": reply_result["content"],
#                 "scheduledDate": scheduled_date,
#             }
#         )

#         bulk_job = await db.bulkemailjob.create(
#             {
#                 "tenantId": tenant_id,
#                 "campaignId": req.campaign_id,
#                 "rateLimit": 1,
#                 "total": 1,
#                 "nextProcessTime": scheduled_date,
#                 "createdAt": datetime.now(),
#             }
#         )

#         await db.bulkemailjoblead.create(
#             {
#                 "jobId": bulk_job.id,
#                 "leadId": req.lead_id,
#             }
#         )

#         await db.conversation.update(
#             where={"id": req.conversation_id}, data={"lastMessageAt": datetime.now()}
#         )

#         return GeneratedEmailResponse(response="Reply generated")

#     except Exception as e:
#         logger.error(f"Could not store the email in the db {e}")
#         raise

# import logging
# from datetime import datetime
# from app.services.database import db
# from app.schemas import GeneratedEmailRequest, GeneratedEmailResponse
# from .email_generator import handle_email_reply_request

# logger = logging.getLogger(__name__)


# async def store_generated_email(
#     req: GeneratedEmailRequest,
#     tenant_id: str,
# ) -> GeneratedEmailResponse:
#     sender_info = {"name": req.sender_name, "email": req.sender_email}
#     reply_result = await handle_email_reply_request(
#         conversation_id=req.conversation_id,
#         latest_email_content=req.latest_email,
#         sender_info=sender_info,
#         recipients=req.recipient_emails,
#         tenant_id=tenant_id,
#         instructions="",
#     )

#     if not reply_result["success"]:
#         logger.error("Could not generate the email reply.")
#         raise

#     try:
#         scheduled_date = None
#         if reply_result.get("scheduled_date"):
#             try:
#                 scheduled_date = datetime.fromisoformat(reply_result["scheduled_date"])
#             except Exception as e:
#                 logger.info(
#                     f"Could not parse the scheduled date to isoformat, scheduled_date: {reply_result['scheduled_date']}, {e}"
#                 )
#                 raise

#         email_message = await db.emailmessage.create(
#             {
#                 "tenantId": tenant_id,
#                 "conversationId": req.conversation_id,
#                 "direction": "OUTBOUND",
#                 "providerMessageId": f"generated-{datetime.now().isoformat()}",
#                 "subject": reply_result["subject"],
#                 "from_": [sender_info["email"]],
#                 "to": req.recipient_emails,
#                 "cc": [],
#                 "bcc": [],
#                 "text": reply_result["content"],
#                 "html": None,
#                 "sentAt": scheduled_date,
#                 "createdAt": datetime.now(),
#                 "campaignId": req.campaign_id,
#                 "leadId": req.lead_id,
#             }
#         )

#         reply_email_log = await db.emaillog.create(
#             {
#                 "tenantId": tenant_id,
#                 "campaignId": req.campaign_id,
#                 "leadId": req.lead_id,
#                 "senderName": sender_info["name"],
#                 "senderEmail": sender_info["email"],
#                 "recipientEmails": req.recipient_emails,
#                 "subject": reply_result["subject"],
#                 "content": reply_result["content"],
#                 "createdAt": datetime.now(),
#                 "emailType": "AI_GENERATED",
#                 "providerMessageId": email_message.providerMessageId,
#                 "outboundMessageId": email_message.id,
#             }
#         )

#         await db.emailmessage.update(
#             where={"id": email_message.id}, data={"emailLogId": reply_email_log.id}
#         )

#         generated_email = await db.generatedemail.create(
#             {
#                 "emailLogId": reply_email_log.id,
#                 "subject": reply_result["subject"],
#                 "content": reply_result["content"],
#                 "scheduledDate": scheduled_date,
#             }
#         )

#         bulk_job = await db.bulkemailjob.create(
#             {
#                 "tenantId": tenant_id,
#                 "campaignId": req.campaign_id,
#                 "rateLimit": 1,
#                 "total": 1,
#                 "nextProcessTime": scheduled_date,
#                 "createdAt": datetime.now(),
#             }
#         )

#         await db.bulkemailjoblead.create(
#             {
#                 "jobId": bulk_job.id,
#                 "leadId": req.lead_id,
#             }
#         )

#         await db.conversation.update(
#             where={"id": req.conversation_id}, data={"lastMessageAt": datetime.now()}
#         )

#         return GeneratedEmailResponse(response="Reply generated")

#     except Exception as e:
#         logger.error(f"Could not store the email in the db {e}")
#         raise
