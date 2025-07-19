import uuid
from prisma import Prisma
from datetime import datetime
import asyncio
import logging
from fastapi import HTTPException
from typing import Dict, List

from app.extractor import ContactExtractor
from app.schemas import (
    ContactInfo,
    ExtractSearchResponse,
    JobStatusResponse,
    CombinedSearchExtractRequest,
)
from app.services.search_engine import SearchEngine, GoogleSearchError

logger = logging.getLogger(__name__)


class ExtractController:
    def __init__(self):
        self.extractor = ContactExtractor()
        self.search_engine = SearchEngine()

    async def extract_contacts_from_urls(
        self, urls: List[str]
    ) -> Dict[str, ContactInfo]:
        try:
            contact_results = await self.extractor.extract(urls)
            filtered_results = {}
            for url, contact in contact_results.items():
                if contact and (contact.get("emails") or contact.get("phones")):
                    try:
                        filtered_results[url] = ContactInfo(**contact)
                    except Exception as e:
                        logger.warning(f"Error creating ContactInfo for {url}: {e}")
                else:
                    logger.info(f"No contact info found for {url}, skipping...")

            return filtered_results

        except Exception as e:
            logger.error(f"Error in batch extraction: {e}")
            raise HTTPException(
                status_code=500, detail=f"Error in batch extraction {e}"
            )

    async def search_and_extract_contacts(
        self, request: CombinedSearchExtractRequest, user_id: str
    ) -> ExtractSearchResponse:
        job_id = str(uuid.uuid4())

        # Immediately insert job in DB
        db = Prisma()
        await db.connect()
        await db.leadgenerationjob.create(
            {
                "id": job_id,
                "tenantId": user_id,
                "status": "PROCESSING",
                "totalRequested": request.num_results,
            }
        )
        await db.disconnect()

        # Start background task
        asyncio.create_task(self._run_extraction_job(request, user_id, job_id))

        return ExtractSearchResponse(job_id=job_id, message="Started processing job")

    async def _run_extraction_job(
        self, request: CombinedSearchExtractRequest, user_id: str, job_id: str
    ):
        db = Prisma()
        await db.connect()
        collected = 0
        result_index = 0
        offset = request.offset
        required_count = request.num_results
        current_generated_count = 0

        try:
            raw = await self.search_engine.search_with_offset(
                prompt=request.prompt,
                user_id=user_id,
                offset=offset,
                num_results=required_count,
            )

            session = raw["session_info"]["session_id"]
            results = raw["results"]

            while collected < required_count:
                if result_index >= len(results):
                    more = await self.search_engine.get_more_results(
                        session_id=session, num_results=10
                    )
                    new_results = more.get("results", [])
                    if not new_results:
                        break
                    results.extend(new_results)

                remaining = required_count - collected
                chunk = []
                chunk_urls = []

                while result_index < len(results) and len(chunk) < remaining:
                    res = results[result_index]
                    chunk.append(res)
                    chunk_urls.append(res.link)
                    result_index += 1

                contact_results = await self.extractor.extract(
                    chunk_urls, user_id, job_id, current_generated_count
                )

                for i, res in enumerate(chunk):
                    url = chunk_urls[i]
                    contact = contact_results.get(url)
                    if contact and (contact.get("emails") or contact.get("phones")):
                        try:
                            # Save result to DB via process_urls_batch already
                            collected += 1
                            current_generated_count += 1
                        except Exception as e:
                            logger.warning(f"Skipping bad contact info for {url}: {e}")
                    else:
                        logger.info(f"No contact info for {url}")

            await db.leadgenerationjob.update(
                where={"id": job_id},
                data={"status": "COMPLETED", "completedAt": datetime.utcnow()},
            )

        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}")
            await db.leadgenerationjob.update(
                where={"id": job_id},
                data={"status": "FAILED"},
            )

        finally:
            await db.disconnect()

    async def get_job_update(self, job_id: str, user_id: str) -> JobStatusResponse:
        db = Prisma()
        await db.connect()

        try:
            job = await db.leadgenerationjob.find_unique(where={"id": job_id})
            print(f"gen count: {job.generatedCount}")

            if not job:
                raise HTTPException(status_code=404, detail="Job not found")

            if job.tenantId != user_id:
                raise HTTPException(
                    status_code=403, detail="Unauthorized access to this job"
                )

            return JobStatusResponse(
                job_id=job.id,
                total_requested=job.totalRequested,
                generated_count=job.generatedCount,
            )

        finally:
            await db.disconnect()
