from fastapi import APIRouter
from app.controllers.search import SearchController
from app.schemas import PromptSearchRequest, PaginatedSearchResponse, MoreResultsRequest

router = APIRouter(prefix="/search", tags=["search"])
search_controller = SearchController()

@router.post("", response_model=PaginatedSearchResponse)
async def search_paginated(request: PromptSearchRequest):
    return await search_controller.search_with_pagination(request)

@router.post("/more", response_model=PaginatedSearchResponse)
async def get_more_results(request: MoreResultsRequest):
    return await search_controller.get_additional_results(request)
