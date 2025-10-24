
from app.services.rag import MultiTenantRAG

from prisma import Prisma
from app.schemas import IngestionSourcesEnum
from app.services.database import db
rag = MultiTenantRAG()

async def calculate_lead_confidence(lead_id: str, tenant_id: str) -> float | None:
    """Compute confidence for a lead and update DB."""
    # pass lead object, rather than fetching from api
    lead = await db.lead.find_unique(where={"id": lead_id})
    print(f"Calculating confidence for lead ID: {lead_id}")
    if not lead:
        return None

    lead_text = lead.description or ""
    print(f"Computing confidence between our text and lead {lead_text} text.")

    # compute confidence using the MultiTenantRAG instance method

    confidence_str = await rag.compute_confidence(
        lead_text=lead_text,
        tenant_id=tenant_id,
        sources=[IngestionSourcesEnum.company_profile, IngestionSourcesEnum.knowledge_documents],
    )

    print(f"Raw confidence string from LLM: {confidence_str}")

    # convert string confidence to float (if possible)
    try:
        confidence = float(confidence_str)
    except ValueError:
        confidence = None

    print(f"Parsed confidence value: {confidence}")

    updated_lead = await db.lead.update(
        where={"id": lead_id},
        data={"confidence": confidence}  # ✅ use your DB field name
    )

    print(f"Updated lead ID {updated_lead} with confidence: {confidence}")

    return confidence