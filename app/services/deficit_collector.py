# app/services/deficit_collector.py
import logging
from typing import List, Optional

from app.schemas import SearchResult, CombinedSearchExtractRequest
from app.extractor import ContactExtractor
from app.services.search_engine import SearchEngine
from app.services.database import db

logger = logging.getLogger(__name__)

class DeficitCollector:
    def __init__(self, search_engine: SearchEngine, extractor: ContactExtractor):
        self.search_engine = search_engine
        self.extractor = extractor

    async def collect_until_fulfilled(
        self,
        *,
        user_id: str,
        job_id: str,
        initial_results: List[SearchResult],
        session_id: str,
        request: CombinedSearchExtractRequest,
        region_filters: Optional[List[str]] = None,
        overfetch_factor: float = 2.0,
        max_total_pull: int = 200,
        max_chunk_size: int = 10,
    ) -> None:
        """
        Keeps requesting more results and extracting until we either
        meet request.num_results or exhaust the session / caps.
        Does NOT set job completion; controller remains source of truth.
        """
        results: List[SearchResult] = list(initial_results)
        result_index = 0
        total_consumed = 0

        while True:
            # Authoritative generated count from DB
            job = await db.leadgenerationjob.find_unique(where={"id": job_id})
            current_generated = job.generatedCount if job else 0
            deficit = request.num_results - current_generated

            if deficit <= 0:
                break

            # Ensure we have enough candidates in memory
            if result_index >= len(results):
                if total_consumed >= max_total_pull:
                    logger.info("no_more_results", extra={"job": job_id, "reason": "max_total_pull"})
                    break
                fetch_n = min(max_chunk_size * 2, max(10, int(deficit * overfetch_factor)))
                more = await self.search_engine.get_more_results(session_id=session_id, num_results=fetch_n)
                new_results = more.get("results", [])
                if not new_results:
                    logger.info("no_more_results", extra={"job": job_id, "reason": "session_exhausted"})
                    break
                results.extend(new_results)

            # Size the next chunk for the current deficit
            chunk_size = min(max_chunk_size, max(1, int(deficit * overfetch_factor)))
            current_chunk = results[result_index: result_index + chunk_size]
            result_index += len(current_chunk)
            total_consumed += len(current_chunk)

            urls = [r.link for r in current_chunk]
            pre_job = await db.leadgenerationjob.find_unique(where={"id": job_id})
            pre_count = pre_job.generatedCount if pre_job else 0

            await self.extractor.extract(
                urls=urls,
                user_id=user_id,
                job_id=job_id,
                current_generated_count=pre_count,
                region_filters=region_filters,
            )

            post_job = await db.leadgenerationjob.find_unique(where={"id": job_id})
            post_count = post_job.generatedCount if post_job else pre_count
            accepted_in_chunk = max(0, post_count - pre_count)

            logger.info("chunk_done", extra={
                "job": job_id,
                "chunk_urls": len(urls),
                "accepted": accepted_in_chunk,
                "collected": min(request.num_results, post_count)
            })

            # Loop continues; stop conditions re-evaluated at top
