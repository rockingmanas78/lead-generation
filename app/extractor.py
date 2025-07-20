import logging
from datetime import datetime
from prisma import Prisma
from typing import List, Dict, Optional
from app.services.database import db
from app.services.shared_processing import process_urls_batch

logger = logging.getLogger(__name__)


class ContactExtractor:
    def __init__(self):
        self.db = db

    async def extract(
        self,
        urls: List[str],
        user_id: str = "",
        job_id: str = "",
        current_generated_count: int = 0,
    ) -> Dict[str, Optional[dict]]:
        try:
            results = await process_urls_batch(
                urls, user_id, job_id, current_generated_count
            )

            await self.db.leadgenerationjob.update(
                where={"id": job_id},
                data={"status": "COMPLETED", "completedAt": datetime.utcnow()},
            )

            return results

        except Exception as e:
            logger.error(f"ContactExtractor class failed: {e}")
            return {}
