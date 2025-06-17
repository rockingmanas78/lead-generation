from typing import Dict, List
from app.extractor import ContactExtractor
from app.schemas import ContactInfo, CombinedSearchExtractResponse, CombinedSearchExtractRequest, CombinedResult
from app.services.search_engine import SearchEngine

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

    async def search_and_extract_contacts(self, request: CombinedSearchExtractRequest) -> CombinedSearchExtractResponse:
        session_user = "default_user"

        raw = await self.search_engine.search_with_offset(
            prompt=request.prompt,
            user_id=session_user,
            offset=request.offset,
            num_results=request.num_results
        )

        combined_results = []
        for res in raw["results"]:
            contact = self.extractor.extract(res.link)
            combined_results.append(
                CombinedResult(
                    search_result=res,
                    contact_info=ContactInfo(**contact)
                )
            )

        return CombinedSearchExtractResponse(
            results=combined_results,
            pagination=raw["pagination"],
            session_info=raw["session_info"],
            query_info=raw["query_info"]
        )
