import uuid
import asyncio
import logging
from datetime import datetime
from typing import Dict, List

from fastapi import HTTPException

from app.extractor import ContactExtractor
from app.schemas import (
    CombinedJobStatusContactInfoResponse,
    ContactInfo,
    ExtractSearchResponse,
    JobStatusResponse,
    CombinedSearchExtractRequest,
)
from app.services.database import db
from app.services.search_engine import SearchEngine, GoogleSearchError
from app.services.location import extract_locations

logger = logging.getLogger(__name__)


class ExtractController:
    def __init__(self):
        self.extractor = ContactExtractor()
        self.search_engine = SearchEngine()
        self.db = db

    async def extract_contacts_from_urls(
        self, urls: List[str]
    ) -> Dict[str, ContactInfo]:
        try:
            contact_results = await self.extractor.extract(urls)
            filtered_results: Dict[str, ContactInfo] = {}
            for url, contact in contact_results.items():
                if contact and (contact.get("emails") or contact.get("phones")):
                    try:
                        filtered_results[url] = ContactInfo(**contact)
                    except Exception as validation_error:
                        logger.warning(f"Error creating ContactInfo for {url}: {validation_error}")
                else:
                    logger.info(f"No contact info found for {url}, skipping...")

            return filtered_results

        except Exception as unexpected_error:
            logger.error(f"Error in batch extraction: {unexpected_error}")
            raise HTTPException(status_code=500, detail=f"Error in batch extraction {unexpected_error}")

    async def search_and_extract_contacts(
        self, request: CombinedSearchExtractRequest, user_id: str
    ) -> ExtractSearchResponse:
        job_id = str(uuid.uuid4())

        await self.db.leadgenerationjob.create(
            {
                "id": job_id,
                "tenantId": user_id,
                "status": "PROCESSING",
                "totalRequested": request.num_results,
                "prompt": request.prompt,
            }
        )
        logger.info("job_created", extra={
            "job": job_id, "tenant": user_id, "requested": request.num_results, "focus": "email"
        })

        # Background job
        asyncio.create_task(self._run_extraction_job(request, user_id, job_id))

        return ExtractSearchResponse(
            job_id=job_id,
            message="Started processing job",
            job_started_at=datetime.utcnow(),
        )

    async def _run_extraction_job(
        self, request: CombinedSearchExtractRequest, user_id: str, job_id: str
    ):
        collected = 0
        result_index = 0
        offset = request.offset
        required_count = request.num_results
        current_generated_count = 0

        # infer locations from the user prompt — used downstream as a soft region filter
        inferred_locations = extract_locations(request.prompt)

        try:
            raw_search_response = await self.search_engine.search_with_offset(
                prompt=request.prompt,
                user_id=user_id,
                offset=offset,
                num_results=required_count,
            )

            session_id = raw_search_response["session_info"]["session_id"]
            results = raw_search_response["results"]

            logger.info("search_kickoff", extra={
                "job": job_id,
                "session": session_id,
                "initial_results": len(results),
                "summary": {
                    "requested": required_count,
                    "returned": len(results),
                    "overfetched_items": max(0, len(results) - required_count),
                    "keywords_used": raw_search_response["query_info"]["generated_queries"],
                    "discovered_sources": raw_search_response["session_info"]["total_results"],
                    "contact_focus": "email",
                    "locations_used": inferred_locations
                }
            })

            while collected < required_count:
                if result_index >= len(results):
                    more = await self.search_engine.get_more_results(
                        session_id=session_id, num_results=10
                    )
                    new_results = more.get("results", [])
                    if not new_results:
                        logger.info("no_more_results", extra={"job": job_id})
                        break
                    results.extend(new_results)

                remaining_needed = required_count - collected
                current_chunk = []
                chunk_urls: List[str] = []

                while result_index < len(results) and len(current_chunk) < remaining_needed:
                    result = results[result_index]
                    current_chunk.append(result)
                    chunk_urls.append(result.link)
                    result_index += 1

                contact_results = await self.extractor.extract(
                    urls=chunk_urls,
                    user_id=user_id,
                    job_id=job_id,
                    current_generated_count=current_generated_count,
                    region_filters=inferred_locations,  # << pass dynamic locations
                )

                accepted_in_chunk = 0
                for index_in_chunk, result in enumerate(current_chunk):
                    url = chunk_urls[index_in_chunk]
                    contact = contact_results.get(url)
                    if contact and (contact.get("emails") or contact.get("phones")):
                        try:
                            collected += 1
                            current_generated_count += 1
                            accepted_in_chunk += 1
                        except Exception as validation_error:
                            logger.warning(f"Skipping bad contact info for {url}: {validation_error}")
                    else:
                        logger.info(f"No contact info for {url}")

                logger.info("chunk_done", extra={
                    "job": job_id, "chunk_urls": len(chunk_urls), "accepted": accepted_in_chunk, "collected": collected
                })

            await self.db.leadgenerationjob.update(
                where={"id": job_id},
                data={"status": "COMPLETED", "completedAt": datetime.utcnow()},
            )
            logger.info("job_completed", extra={"job": job_id, "generated": current_generated_count})

        except GoogleSearchError as cse_error:
            logger.error("job_failed_cse", extra={"job": job_id, "error": str(cse_error)})
            await self.db.leadgenerationjob.update(
                where={"id": job_id},
                data={"status": "FAILED"},
            )
        except Exception as unexpected_error:
            logger.error(f"Job {job_id} failed: {unexpected_error}")
            await self.db.leadgenerationjob.update(
                where={"id": job_id},
                data={"status": "FAILED"},
            )

    async def get_job_update(
        self, job_id: str, tenant_id: str, since
    ) -> CombinedJobStatusContactInfoResponse:
        try:
            job = await self.db.leadgenerationjob.find_unique(where={"id": job_id})

            if not job:
                raise HTTPException(status_code=404, detail="Job not found")

            if job.tenantId != tenant_id:
                raise HTTPException(status_code=403, detail="Unauthorized access to this job")

            if since is None:
                leads = await self.db.lead.find_many(
                    where={"tenantId": tenant_id, "jobId": job_id},
                    order={"createdAt": "desc"},
                )
            else:
                leads = await self.db.lead.find_many(
                    where={
                        "tenantId": tenant_id,
                        "jobId": job_id,
                        "createdAt": {"gte": since},
                    },
                    order={"createdAt": "desc"},
                )

            contact_infos: List[ContactInfo] = []
            for lead in leads:
                contact_info = ContactInfo(
                    emails=lead.contactEmail,
                    phones=lead.contactPhone,
                    addresses=lead.contactAddress,
                    company_name=lead.companyName,
                    description="",
                )
                contact_infos.append(contact_info)

            job_status_response = JobStatusResponse(
                job_id=job.id,
                total_requested=job.totalRequested,
                generated_count=job.generatedCount,
                status=job.status,
            )

            return CombinedJobStatusContactInfoResponse(
                job_status_response=job_status_response,
                contact_infos=contact_infos,
                retrieved_at=datetime.utcnow(),
            )

        except Exception as unexpected_error:
            logger.error(f"get_job_update function failed: {unexpected_error}")
            raise



# Good ALgorithm so far
# import uuid
# import asyncio
# import logging
# from datetime import datetime
# from typing import Dict, List

# from fastapi import HTTPException

# from app.extractor import ContactExtractor
# from app.schemas import (
#     CombinedJobStatusContactInfoResponse,
#     ContactInfo,
#     ExtractSearchResponse,
#     JobStatusResponse,
#     CombinedSearchExtractRequest,
# )
# from app.services.database import db
# from app.services.search_engine import SearchEngine, GoogleSearchError
# from app.services.location import extract_locations

# logger = logging.getLogger(__name__)

# class ExtractController:
#     def __init__(self):
#         self.extractor = ContactExtractor()
#         self.search_engine = SearchEngine()
#         self.db = db

#     async def extract_contacts_from_urls(
#         self, urls: List[str]
#     ) -> Dict[str, ContactInfo]:
#         try:
#             contact_results = await self.extractor.extract(urls)
#             filtered_results: Dict[str, ContactInfo] = {}
#             for url, contact in contact_results.items():
#                 if contact and (contact.get("emails") or contact.get("phones")):
#                     try:
#                         filtered_results[url] = ContactInfo(**contact)
#                     except Exception as validation_error:
#                         logger.warning(f"Error creating ContactInfo for {url}: {validation_error}")
#                 else:
#                     logger.info(f"No contact info found for {url}, skipping...")

#             return filtered_results

#         except Exception as unexpected_error:
#             logger.error(f"Error in batch extraction: {unexpected_error}")
#             raise HTTPException(status_code=500, detail=f"Error in batch extraction {unexpected_error}")

#     async def search_and_extract_contacts(
#         self, request: CombinedSearchExtractRequest, user_id: str
#     ) -> ExtractSearchResponse:
#         job_id = str(uuid.uuid4())

#         await self.db.leadgenerationjob.create(
#             {
#                 "id": job_id,
#                 "tenantId": user_id,
#                 "status": "PROCESSING",
#                 "totalRequested": request.num_results,
#                 "prompt": request.prompt,
#             }
#         )
#         logger.info("job_created", extra={
#             "job": job_id, "tenant": user_id, "requested": request.num_results, "focus": "email"
#         })

#         # Start background task
#         asyncio.create_task(self._run_extraction_job(request, user_id, job_id))

#         return ExtractSearchResponse(
#             job_id=job_id,
#             message="Started processing job",
#             job_started_at=datetime.utcnow(),
#         )

#     async def _run_extraction_job(
#         self, request: CombinedSearchExtractRequest, user_id: str, job_id: str
#     ):
#         collected = 0
#         result_index = 0
#         offset = request.offset
#         required_count = request.num_results
#         current_generated_count = 0

#         inferred_locations = extract_locations(request.prompt)

#         try:
#             raw_search_response = await self.search_engine.search_with_offset(
#                 prompt=request.prompt,
#                 user_id=user_id,
#                 offset=offset,
#                 num_results=required_count,
#             )

#             session_id = raw_search_response["session_info"]["session_id"]
#             results = raw_search_response["results"]

#             logger.info("search_kickoff", extra={
#                 "job": job_id,
#                 "session": session_id,
#                 "initial_results": len(results),
#                 "summary": {
#                     "requested": required_count,
#                     "returned": len(results),
#                     "overfetched_items": max(0, len(results) - required_count),
#                     "keywords_used": raw_search_response["query_info"]["generated_queries"],
#                     "discovered_sources": raw_search_response["session_info"]["total_results"],
#                     "contact_focus": "email",
#                     "locations_used": inferred_locations
#                 }
#             })

#             while collected < required_count:
#                 if result_index >= len(results):
#                     more = await self.search_engine.get_more_results(
#                         session_id=session_id, num_results=10
#                     )
#                     new_results = more.get("results", [])
#                     if not new_results:
#                         logger.info("no_more_results", extra={"job": job_id})
#                         break
#                     results.extend(new_results)

#                 remaining_needed = required_count - collected
#                 current_chunk = []
#                 chunk_urls: List[str] = []

#                 while result_index < len(results) and len(current_chunk) < remaining_needed:
#                     result = results[result_index]
#                     current_chunk.append(result)
#                     chunk_urls.append(result.link)
#                     result_index += 1

#                 contact_results = await self.extractor.extract(
#                     urls=chunk_urls,
#                     user_id=user_id,
#                     job_id=job_id,
#                     current_generated_count=current_generated_count,
#                 )

#                 accepted_in_chunk = 0
#                 for index_in_chunk, result in enumerate(current_chunk):
#                     url = chunk_urls[index_in_chunk]
#                     contact = contact_results.get(url)
#                     if contact and (contact.get("emails") or contact.get("phones")):
#                         try:
#                             collected += 1
#                             current_generated_count += 1
#                             accepted_in_chunk += 1
#                         except Exception as validation_error:
#                             logger.warning(f"Skipping bad contact info for {url}: {validation_error}")
#                     else:
#                         logger.info(f"No contact info for {url}")

#                 logger.info("chunk_done", extra={
#                     "job": job_id, "chunk_urls": len(chunk_urls), "accepted": accepted_in_chunk, "collected": collected
#                 })

#             await self.db.leadgenerationjob.update(
#                 where={"id": job_id},
#                 data={"status": "COMPLETED", "completedAt": datetime.utcnow()},
#             )
#             logger.info("job_completed", extra={"job": job_id, "generated": current_generated_count})

#         except GoogleSearchError as cse_error:
#             logger.error("job_failed_cse", extra={"job": job_id, "error": str(cse_error)})
#             await self.db.leadgenerationjob.update(
#                 where={"id": job_id},
#                 data={"status": "FAILED"},
#             )
#         except Exception as unexpected_error:
#             logger.error(f"Job {job_id} failed: {unexpected_error}")
#             await self.db.leadgenerationjob.update(
#                 where={"id": job_id},
#                 data={"status": "FAILED"},
#             )

#     async def get_job_update(
#         self, job_id: str, user_id: str, since
#     ) -> CombinedJobStatusContactInfoResponse:
#         try:
#             job = await self.db.leadgenerationjob.find_unique(where={"id": job_id})

#             if not job:
#                 raise HTTPException(status_code=404, detail="Job not found")

#             if job.tenantId != user_id:
#                 raise HTTPException(status_code=403, detail="Unauthorized access to this job")

#             if since is None:
#                 leads = await self.db.lead.find_many(
#                     where={"tenantId": user_id, "jobId": job_id},
#                     order={"createdAt": "desc"},
#                 )
#             else:
#                 leads = await self.db.lead.find_many(
#                     where={
#                         "tenantId": user_id,
#                         "jobId": job_id,
#                         "createdAt": {"gte": since},
#                     },
#                     order={"createdAt": "desc"},
#                 )

#             contact_infos: List[ContactInfo] = []
#             for lead in leads:
#                 contact_info = ContactInfo(
#                     emails=lead.contactEmail,
#                     phones=lead.contactPhone,
#                     addresses=lead.contactAddress,
#                     company_name=lead.companyName,
#                     description="",
#                 )
#                 contact_infos.append(contact_info)

#             job_status_response = JobStatusResponse(
#                 job_id=job.id,
#                 total_requested=job.totalRequested,
#                 generated_count=job.generatedCount,
#             )

#             return CombinedJobStatusContactInfoResponse(
#                 job_status_response=job_status_response,
#                 contact_infos=contact_infos,
#                 retrieved_at=datetime.utcnow(),
#             )

#         except Exception as unexpected_error:
#             logger.error(f"get_job_update function failed: {unexpected_error}")
#             raise


# import uuid
# from datetime import datetime
# import asyncio
# import logging
# from fastapi import HTTPException
# from typing import Dict, List

# from app.extractor import ContactExtractor
# from app.schemas import (
#     CombinedJobStatusContactInfoResponse,
#     ContactInfo,
#     ExtractSearchResponse,
#     JobStatusResponse,
#     CombinedSearchExtractRequest,
# )
# from app.services.database import db
# from app.services.search_engine import SearchEngine, GoogleSearchError

# logger = logging.getLogger(__name__)

# class ExtractController:
#     def __init__(self):
#         self.extractor = ContactExtractor()
#         self.search_engine = SearchEngine()
#         self.db = db

#     async def extract_contacts_from_urls(
#         self, urls: List[str]
#     ) -> Dict[str, ContactInfo]:
#         try:
#             # default to both when using direct URLs endpoint
#             contact_results = await self.extractor.extract(urls, contact_focus="both")
#             filtered_results = {}
#             for url, contact in contact_results.items():
#                 if contact and (contact.get("emails") or contact.get("phones")):
#                     try:
#                         filtered_results[url] = ContactInfo(**contact)
#                     except Exception as e:
#                         logger.warning("contactinfo_pydantic_error", extra={"json": {"url": url, "error": str(e)}})
#                 else:
#                     logger.info("no_contact_info", extra={"json": {"url": url}})
#             return filtered_results

#         except Exception as e:
#             logger.error("batch_extraction_error", extra={"json": {"error": str(e)}})
#             raise HTTPException(status_code=500, detail=f"Error in batch extraction {e}")

#     async def search_and_extract_contacts(
#         self, request: CombinedSearchExtractRequest, user_id: str
#     ) -> ExtractSearchResponse:
#         job_id = str(uuid.uuid4())

#         await self.db.leadgenerationjob.create(
#             {
#                 "id": job_id,
#                 "tenantId": user_id,
#                 "status": "PROCESSING",
#                 "totalRequested": request.num_results,
#                 "prompt": request.prompt,
#             }
#         )
#         logger.info("job_created", extra={"json": {"job": job_id, "tenant": user_id, "requested": request.num_results, "focus": request.contact_focus}})

#         asyncio.create_task(self._run_extraction_job(request, user_id, job_id))

#         return ExtractSearchResponse(
#             job_id=job_id,
#             message="Started processing job",
#             job_started_at=datetime.utcnow(),
#         )

#     async def _run_extraction_job(
#         self, request: CombinedSearchExtractRequest, user_id: str, job_id: str
#     ):
#         collected = 0
#         result_index = 0
#         offset = request.offset
#         required_count = request.num_results
#         current_generated_count = 0

#         try:
#             raw = await self.search_engine.search_with_offset(
#                 prompt=request.prompt,
#                 user_id=user_id,
#                 offset=offset,
#                 num_results=required_count,
#                 location=None,  # or from request if you have it
#                 industry=None,
#                 contact_focus=request.contact_focus,
#                 exclude_aggregators=request.exclude_aggregators,
#                 domains_hint=request.domains_hint,
#             )
#             session = raw["session_info"]["session_id"]
#             results = raw["results"]

#             logger.info("search_kickoff", extra={"json": {
#                 "job": job_id,
#                 "session": session,
#                 "initial_results": len(results),
#                 "summary": raw.get("summary", {})
#             }})

#             while collected < required_count:
#                 if result_index >= len(results):
#                     more = await self.search_engine.get_more_results(
#                         session_id=session, num_results=min(10, required_count - collected)
#                     )
#                     new_results = more.get("results", [])
#                     if not new_results:
#                         logger.info("no_more_results", extra={"json": {"job": job_id}})
#                         break
#                     results.extend(new_results)

#                 remaining = required_count - collected
#                 chunk = []
#                 chunk_urls = []

#                 while result_index < len(results) and len(chunk) < remaining:
#                     res = results[result_index]
#                     chunk.append(res)
#                     chunk_urls.append(res.link)
#                     result_index += 1

#                 contact_results = await self.extractor.extract(
#                     chunk_urls,
#                     user_id,
#                     job_id,
#                     current_generated_count,
#                     contact_focus=request.contact_focus.value,
#                 )

#                 # Only count leads accepted & inserted (shared_processing enforces)
#                 # Here we count what came back as non-empty payloads by focus rule
#                 accepted = sum(
#                     1 for u in chunk_urls
#                     if contact_results.get(u)
#                     and (
#                         (request.contact_focus == request.contact_focus.email and (contact_results[u].get("emails") or []))
#                         or (request.contact_focus == request.contact_focus.phone and (contact_results[u].get("phones") or []))
#                         or (request.contact_focus == request.contact_focus.both and ((contact_results[u].get("emails") or []) or (contact_results[u].get("phones") or [])))
#                     )
#                 )
#                 collected += accepted
#                 current_generated_count += accepted

#                 logger.info("chunk_done", extra={"json": {
#                     "job": job_id,
#                     "chunk_urls": len(chunk_urls),
#                     "accepted": accepted,
#                     "collected": collected,
#                 }})

#             await self.db.leadgenerationjob.update(
#                 where={"id": job_id},
#                 data={"status": "COMPLETED", "completedAt": datetime.utcnow()},
#             )
#             logger.info("job_completed", extra={"json": {"job": job_id, "generated": current_generated_count}})

#         except GoogleSearchError as e:
#             logger.error("job_failed_cse", extra={"json": {"job": job_id, "error": str(e)}})
#             await self.db.leadgenerationjob.update(
#                 where={"id": job_id},
#                 data={"status": "FAILED"},
#             )
#         except Exception as e:
#             logger.error("job_failed", extra={"json": {"job": job_id, "error": str(e)}})
#             await self.db.leadgenerationjob.update(
#                 where={"id": job_id},
#                 data={"status": "FAILED"},
#             )

#     async def get_job_update(
#         self, job_id: str, user_id: str, since: datetime | None
#     ) -> CombinedJobStatusContactInfoResponse:
#         try:
#             job = await self.db.leadgenerationjob.find_unique(where={"id": job_id})
#             if not job:
#                 raise HTTPException(status_code=404, detail="Job not found")
#             if job.tenantId != user_id:
#                 raise HTTPException(status_code=403, detail="Unauthorized access to this job")

#             if since is None:
#                 leads = await self.db.lead.find_many(
#                     where={"tenantId": user_id, "jobId": job_id},
#                     order={"createdAt": "desc"},
#                 )
#             else:
#                 leads = await self.db.lead.find_many(
#                     where={
#                         "tenantId": user_id,
#                         "jobId": job_id,
#                         "createdAt": {"gte": since},
#                     },
#                     order={"createdAt": "desc"},
#                 )

#             contact_infos: list[ContactInfo] = []
#             for lead in leads:
#                 contact_info = ContactInfo(
#                     emails=lead.contactEmail,
#                     phones=lead.contactPhone,
#                     addresses=lead.contactAddress,
#                     company_name=lead.companyName,
#                     description="",
#                 )
#                 contact_infos.append(contact_info)

#             job_status_response = JobStatusResponse(
#                 job_id=job.id,
#                 total_requested=job.totalRequested,
#                 generated_count=job.generatedCount,
#             )

#             return CombinedJobStatusContactInfoResponse(
#                 job_status_response=job_status_response,
#                 contact_infos=contact_infos,
#                 retrieved_at=datetime.utcnow(),
#             )
#         except Exception as e:
#             logger.error("get_job_update_failed", extra={"json": {"job": job_id, "error": str(e)}})
#             raise

# import uuid
# from prisma import Prisma
# from datetime import datetime
# import asyncio
# import logging
# from fastapi import HTTPException
# from typing import Dict, List

# from app.extractor import ContactExtractor
# from app.schemas import (
#     CombinedJobStatusContactInfoResponse,
#     ContactInfo,
#     ExtractSearchResponse,
#     JobStatusResponse,
#     CombinedSearchExtractRequest,
# )
# from app.services.database import db
# from app.services.search_engine import SearchEngine, GoogleSearchError

# logger = logging.getLogger(__name__)


# class ExtractController:
#     def __init__(self):
#         self.extractor = ContactExtractor()
#         self.search_engine = SearchEngine()
#         self.db = db

#     async def extract_contacts_from_urls(
#         self, urls: List[str]
#     ) -> Dict[str, ContactInfo]:
#         try:
#             contact_results = await self.extractor.extract(urls)
#             filtered_results = {}
#             for url, contact in contact_results.items():
#                 if contact and (contact.get("emails") or contact.get("phones")):
#                     try:
#                         filtered_results[url] = ContactInfo(**contact)
#                     except Exception as e:
#                         logger.warning(f"Error creating ContactInfo for {url}: {e}")
#                 else:
#                     logger.info(f"No contact info found for {url}, skipping...")

#             return filtered_results

#         except Exception as e:
#             logger.error(f"Error in batch extraction: {e}")
#             raise HTTPException(
#                 status_code=500, detail=f"Error in batch extraction {e}"
#             )

#     async def search_and_extract_contacts(
#         self, request: CombinedSearchExtractRequest, user_id: str
#     ) -> ExtractSearchResponse:
#         job_id = str(uuid.uuid4())

#         await self.db.leadgenerationjob.create(
#             {
#                 "id": job_id,
#                 "tenantId": user_id,
#                 "status": "PROCESSING",
#                 "totalRequested": request.num_results,
#                 "prompt": request.prompt,
#             }
#         )

#         # Start background task
#         asyncio.create_task(self._run_extraction_job(request, user_id, job_id))

#         return ExtractSearchResponse(
#             job_id=job_id,
#             message="Started processing job",
#             job_started_at=datetime.utcnow(),
#         )

#     async def _run_extraction_job(
#         self, request: CombinedSearchExtractRequest, user_id: str, job_id: str
#     ):
#         collected = 0
#         result_index = 0
#         offset = request.offset
#         required_count = request.num_results
#         current_generated_count = 0

#         try:
#             raw = await self.search_engine.search_with_offset(
#                 prompt=request.prompt,
#                 user_id=user_id,
#                 offset=offset,
#                 num_results=required_count,
#             )

#             session = raw["session_info"]["session_id"]
#             results = raw["results"]

#             while collected < required_count:
#                 if result_index >= len(results):
#                     more = await self.search_engine.get_more_results(
#                         session_id=session, num_results=10
#                     )
#                     new_results = more.get("results", [])
#                     if not new_results:
#                         break
#                     results.extend(new_results)

#                 remaining = required_count - collected
#                 chunk = []
#                 chunk_urls = []

#                 while result_index < len(results) and len(chunk) < remaining:
#                     res = results[result_index]
#                     chunk.append(res)
#                     chunk_urls.append(res.link)
#                     result_index += 1

#                 contact_results = await self.extractor.extract(
#                     chunk_urls, user_id, job_id, current_generated_count
#                 )

#                 for i, res in enumerate(chunk):
#                     url = chunk_urls[i]
#                     contact = contact_results.get(url)
#                     if contact and (contact.get("emails") or contact.get("phones")):
#                         try:
#                             # Save result to DB via process_urls_batch already
#                             collected += 1
#                             current_generated_count += 1
#                         except Exception as e:
#                             logger.warning(f"Skipping bad contact info for {url}: {e}")
#                     else:
#                         logger.info(f"No contact info for {url}")

#             await self.db.leadgenerationjob.update(
#                 where={"id": job_id},
#                 data={"status": "COMPLETED", "completedAt": datetime.utcnow()},
#             )

#         except Exception as e:
#             logger.error(f"Job {job_id} failed: {e}")
#             await self.db.leadgenerationjob.update(
#                 where={"id": job_id},
#                 data={"status": "FAILED"},
#             )

#     async def get_job_update(
#         self, job_id: str, user_id: str, since: datetime | None
#     ) -> CombinedJobStatusContactInfoResponse:
#         try:
#             job = await self.db.leadgenerationjob.find_unique(where={"id": job_id})

#             if not job:
#                 raise HTTPException(status_code=404, detail="Job not found")

#             if job.tenantId != user_id:
#                 raise HTTPException(
#                     status_code=403, detail="Unauthorized access to this job"
#                 )

#             leads = []
#             if since is None:
#                 leads = await self.db.lead.find_many(
#                     where={"tenantId": user_id, "jobId": job_id},
#                     order={"createdAt": "desc"},
#                 )
#             else:
#                 leads = await self.db.lead.find_many(
#                     where={
#                         "tenantId": user_id,
#                         "jobId": job_id,
#                         "createdAt": {"gte": since},
#                     },
#                     order={"createdAt": "desc"},
#                 )

#             contact_infos: list[ContactInfo] = []
#             for lead in leads:
#                 contact_info = ContactInfo(
#                     emails=lead.contactEmail,
#                     phones=lead.contactPhone,
#                     addresses=lead.contactAddress,
#                     company_name=lead.companyName,
#                     description="",
#                 )
#                 contact_infos.append(contact_info)

#             job_status_response = JobStatusResponse(
#                 job_id=job.id,
#                 total_requested=job.totalRequested,
#                 generated_count=job.generatedCount,
#             )

#             return CombinedJobStatusContactInfoResponse(
#                 job_status_response=job_status_response,
#                 contact_infos=contact_infos,
#                 retrieved_at=datetime.utcnow(),
#             )

#         except Exception as e:
#             logger.error(f"get_job_update function failed: {e}")
#             raise
