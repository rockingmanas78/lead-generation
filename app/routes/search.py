from fastapi import APIRouter, HTTPException
from app.services.search_engine import SearchEngine
from app.schemas import PromptSearchRequest, PaginatedSearchResponse, MoreResultsRequest

router = APIRouter(prefix="/search", tags=["search"])

search_engine = SearchEngine()

@router.post("", response_model=PaginatedSearchResponse)
async def search_paginated(request: PromptSearchRequest):
    session_user = "default_user"
    result = await search_engine.search_with_offset(
        prompt=request.prompt,
        user_id=session_user,
        offset=request.offset,
        num_results=request.num_results
    )
    return PaginatedSearchResponse(**result)

@router.post("/more", response_model=PaginatedSearchResponse)
async def get_more_results(request: MoreResultsRequest):
    try:
        result = await search_engine.get_more_results(
            session_id=request.session_id,
            num_results=request.num_results
        )
        return PaginatedSearchResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Search service temporarily unavailable")
