import logging
import uuid
from datetime import datetime
from prisma import Prisma
from typing import List, Dict, Optional
from app.services.shared_processing import process_urls_batch

logger = logging.getLogger(__name__)

class ContactExtractor:
    def __init__(self):
        pass

    async def extract(self, urls: List[str], user_id: str = "") -> Dict[str, Optional[dict]]:
        db = Prisma()
        await db.connect()

        try:
            job_id = str(uuid.uuid4())
            total_requested = len(urls)

            await db.leadgenerationjob.create({
                "id": job_id,
                "tenantId": user_id,
                "status": "PROCESSING",
                "totalRequested": total_requested,
                "urls": urls
            })

            results = await process_urls_batch(urls, user_id, job_id, 0)

            await db.leadgenerationjob.update(
                where={"id": job_id},
                data={
                    "status": "COMPLETED",
                    "completedAt": datetime.utcnow()
                }
            )

            return results

        finally:
            await db.disconnect()
