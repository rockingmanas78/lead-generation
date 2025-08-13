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
        campaign_id=req.campaign_id,
        latest_email_content=req.latest_email,
        sender_info=sender_info,
        recipients=req.recipient_emails,
        tenant_id=tenant_id,
        instructions="",
    )

    if not reply_result["success"]:
        logger.error("Could not generate the email reply.")
        raise

    try:
        scheduled_date = None
        if reply_result.get("scheduled_date"):
            try:
                scheduled_date = datetime.fromisoformat(reply_result["scheduled_date"])
            except Exception as e:
                logger.info(
                    f"Could not parse the scheduled date to isoformat, scheduled_date: {reply_result['scheduled_date']}, {e}"
                )
                raise

        reply_email_log = await db.emaillog.create(
            {
                "tenantId": tenant_id,
                "campaignId": req.campaign_id,
                "leadId": req.lead_id,
                "senderName": sender_info["name"],
                "senderEmail": sender_info["email"],
                "recipientEmails": req.recipient_emails,
                "subject": reply_result["subject"],
                "content": reply_result["content"],
                "createdAt": datetime.now(),
                "emailType": "AI_GENERATED",
            }
        )

        generated_email = await db.generatedemail.create(
            {
                "emailLogId": reply_email_log.id,
                "subject": reply_result["subject"],
                "content": reply_result["content"],
                "scheduledDate": scheduled_date,
            }
        )

        bulk_job = await db.bulkemailjob.create(
            {
                "tenantId": tenant_id,
                "campaignId": req.campaign_id,
                "rateLimit": 1,
                "total": 1,
                "nextProcessTime": scheduled_date,
                "createdAt": datetime.now(),
            }
        )

        await db.bulkemailjoblead.create(
            {
                "jobId": bulk_job.id,
                "leadId": req.lead_id,
            }
        )

        return GeneratedEmailResponse(response="Reply generated")

    except Exception as e:
        logger.error(f"Could not store the email in the db {e}")
        raise
