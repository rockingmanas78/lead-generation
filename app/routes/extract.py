from typing import Dict
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from app.auth.auth_bearer import JWTBearer
from app.controllers.extract import ExtractController
from app.schemas import ContactInfo, CombinedSearchExtractResponse, CombinedSearchExtractRequest

router = APIRouter(prefix="/extract", tags=["extract"])
extract_controller = ExtractController()

class URLListRequest(BaseModel):
    urls: list[str] = Field(..., description="List of URLs to extract contact information from")

@router.post("", response_model=Dict[str, ContactInfo], dependencies=[Depends(JWTBearer())])
def extract_from_urls(request: URLListRequest):
    return extract_controller.extract_contacts_from_urls(request.urls)

@router.post("/search", response_model=CombinedSearchExtractResponse, dependencies=[Depends(JWTBearer())])
async def search_and_extract(request: CombinedSearchExtractRequest, http_request: Request):
    token = await JWTBearer()(http_request)
    from app.config import JWT_SECRET, JWT_ALGORITHM
    import jwt
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    user_id = payload.get("id")

    return await extract_controller.search_and_extract_contacts(request, user_id)
