import asyncio
import logging
from fastapi import HTTPException
from typing import Dict, List

from app.extractor import ContactExtractor
from app.schemas import ContactInfo, CombinedSearchExtractResponse, CombinedSearchExtractRequest, CombinedResult
from app.services.search_engine import SearchEngine, GoogleSearchError

logger = logging.getLogger(__name__)

class ExtractController:
    def __init__(self):
        self.extractor = ContactExtractor()
        self.search_engine = SearchEngine()

    async def extract_contacts_from_urls(self, urls: List[str]) -> Dict[str, ContactInfo]:
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
            raise HTTPException(status_code=500, detail=f"Error in batch extraction {e}")

    async def search_and_extract_contacts(self, request: CombinedSearchExtractRequest, user_id: str) -> CombinedSearchExtractResponse:
        required_count = request.num_results
        offset = request.offset
        collected = 0
        result_index = 0
        combined_results: List[CombinedResult] = []

        try:
            raw = await self.search_engine.search_with_offset(
                prompt=request.prompt,
                user_id=user_id,
                offset=offset,
                num_results=required_count
            )
        except GoogleSearchError as e:
            logger.error(f"Google Search Error: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
        except Exception as e:
            logger.error(f"Search error: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

        session = raw["session_info"]["session_id"]
        results = raw["results"]

        while collected < required_count:
            if result_index >= len(results):
                try:
                    more = await self.search_engine.get_more_results(session_id=session, num_results=10)
                    new_results = more.get("results", [])
                    if not new_results:
                        break
                    results.extend(new_results)
                except GoogleSearchError as e:
                    logger.error(f"Google Search Error: {str(e)}")
                    break
                except Exception as e:
                    logger.error(f"Error fetching more results: {e}")
                    break

            remaining = required_count - collected
            chunk = []
            chunk_urls = []

            while result_index < len(results) and len(chunk) < remaining:
                res = results[result_index]
                chunk.append(res)
                chunk_urls.append(res.link)
                result_index += 1

            try:
                contact_results = await self.extractor.extract(chunk_urls)

                for i, res in enumerate(chunk):
                    url = chunk_urls[i]
                    contact = contact_results.get(url)

                    if contact and (contact.get("emails") or contact.get("phones")):
                        try:
                            combined_results.append(CombinedResult(
                                search_result=res,
                                contact_info=ContactInfo(**contact)
                            ))
                            collected += 1
                            if collected >= required_count:
                                break
                        except Exception as e:
                            logger.warning(f"Error creating result for {url}: {e}")
                    else:
                        logger.info(f"No contact info for {url}")

            except Exception as e:
                logger.error(f"Error in batch extraction for chunk: {e}")
                raise HTTPException(status_code=500, detail=f"Error in batch extraction {e}")

        return CombinedSearchExtractResponse(
            results=combined_results,
            pagination={
                "offset": offset,
                "results_returned": len(combined_results),
                "total_results_available": len(results),
                "has_more": result_index < len(results),
                "next_offset": offset + len(combined_results)
            },
            session_info=raw["session_info"],
            query_info=raw["query_info"]
        )
