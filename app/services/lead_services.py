
from app.services.rag import MultiTenantRAG

from prisma import Prisma
from app.schemas import IngestionSourcesEnum

db = Prisma()

async def calculate_lead_confidence(lead_id: str, our_company: dict, tenant_id: str) -> float | None:
    """Compute confidence for a lead and update DB."""
    lead = await db.lead.find_unique(where={"id": lead_id})
    if not lead:
        return None

    our_text = our_company.get("description", "")
    lead_text = lead.get("description", "")
    print(f"Computing confidence between our text and lead {lead_text} text.")
    print(f"Our text: {our_text}")

    # compute confidence using the MultiTenantRAG instance method
    rag = MultiTenantRAG()
    confidence_str = await rag.compute_confidence(
        question=our_text,
        lead_text=lead_text,
        tenant_id=tenant_id,
        sources=[IngestionSourcesEnum.company_profile, IngestionSourcesEnum.knowledge_documents],
    )

    # convert string confidence to float (if possible)
    try:
        confidence = float(confidence_str)
    except ValueError:
        confidence = None

    await db.lead.update(
        where={"id": lead_id},
        data={"confidence": confidence}  # ✅ use your DB field name
    )

    return confidence