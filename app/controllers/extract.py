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

    def extract_contacts_from_urls(self, urls: List[str]) -> Dict[str, ContactInfo]:
        results = {}
        for url in urls:
            contact = self.extractor.extract(url)
            results[url] = ContactInfo(**contact)
        return results

    async def search_and_extract_contacts(self, request: CombinedSearchExtractRequest, user_id: str) -> CombinedSearchExtractResponse:
        session_user = user_id
        required_count = request.num_results
        collected = 0
        offset = request.offset
        combined_results = []

        try:
            raw = await self.search_engine.search_with_offset(
                prompt=request.prompt,
                user_id=session_user,
                offset=offset,
                num_results=required_count
            )
        except GoogleSearchError as e:
            logger.error(f"Google Search Error {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
        except Exception as e:
            logger.error(f"Search endpoint error: {e}")
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

        session = raw["session_info"]["session_id"]
        total_available = raw["pagination"]["total_results_available"]

        results = raw["results"]
        result_index = 0

        while collected < required_count:
            if result_index >= len(results):
                try:
                    more = await self.search_engine.get_more_results(session_id=session, num_results=10)
                except GoogleSearchError as e:
                    logger.error(f"Google Search Error {str(e)}")
                    raise HTTPException(status_code=500, detail=str(e))
                except Exception as e:
                    logger.error(f"Search endpoint error: {e}")
                    raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

                new_results = more["results"]
                if not new_results:
                    break
                results.extend(new_results)

            res = results[result_index]
            result_index += 1

            contact = self.extractor.extract(res.link)
            if not contact or (not contact.get("emails") and not contact.get("phones")):
                logger.info(f"No contact info found for {res.link} Skipping...")
                continue
            combined_results.append(
                CombinedResult(
                    search_result=res,
                    contact_info=ContactInfo(**contact)
                )
            )
            collected += 1

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
