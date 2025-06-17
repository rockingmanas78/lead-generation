from fastapi import APIRouter
from typing import Dict, List
from pydantic import BaseModel
from app.extractor import ContactExtractor
from app.schemas import ContactInfo, CombinedSearchExtractResponse, CombinedSearchExtractRequest, CombinedResult
from app.services.search_engine import SearchEngine

router = APIRouter(prefix="/extract", tags=["extract"])

extractor = ContactExtractor()
search_engine = SearchEngine()

class URLListRequest(BaseModel):
    urls: List[str]

@router.post("", response_model=Dict[str, ContactInfo])
def extract_from_urls(request: URLListRequest):
    results = {}
    for url in request.urls:
        contact = extractor.extract(url)
        results[url] = ContactInfo(**contact)
    return results

@router.post("/search", response_model=CombinedSearchExtractResponse)
async def search_and_extract(request: CombinedSearchExtractRequest):
    session_user = "default_user"

    raw = await search_engine.search_with_offset(
        prompt=request.prompt,
        user_id=session_user,
        offset=request.offset,
        num_results=request.num_results
    )

    combined_results = []
    for res in raw["results"]:
        contact = extractor.extract(res.link)
        combined_results.append(CombinedResult(search_result=res, contact_info=ContactInfo(**contact)))

    return CombinedSearchExtractResponse(
        results=combined_results,
        pagination=raw["pagination"],
        session_info=raw["session_info"],
        query_info=raw["query_info"]
    )
