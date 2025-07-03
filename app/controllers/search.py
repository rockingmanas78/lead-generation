from fastapi import HTTPException
from app.services.search_engine import SearchEngine, GoogleSearchError
from app.schemas import PromptSearchRequest, PaginatedSearchResponse, MoreResultsRequest

class SearchController:
    def __init__(self):
        self.search_engine = SearchEngine()

    async def search_with_pagination(self, request: PromptSearchRequest) -> PaginatedSearchResponse:
        session_user = "default_user"

        try:
            result = await self.search_engine.search_with_offset(
                prompt=request.prompt,
                user_id=session_user,
                offset=request.offset,
                num_results=request.num_results
            )
        except GoogleSearchError as e:
            raise HTTPException(status_code=500, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

        return PaginatedSearchResponse(**result)

    async def get_additional_results(self, request: MoreResultsRequest) -> PaginatedSearchResponse:
        try:
            result = await self.search_engine.get_more_results(
                session_id=request.session_id,
                num_results=request.num_results
            )
            return PaginatedSearchResponse(**result)
        except GoogleSearchError as e:
            raise HTTPException(status_code=500, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
