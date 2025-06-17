from fastapi import APIRouter
from typing import Dict
from pydantic import BaseModel, Field
from app.controllers.extract import ExtractController
from app.schemas import ContactInfo, CombinedSearchExtractResponse, CombinedSearchExtractRequest

router = APIRouter(prefix="/extract", tags=["extract"])
extract_controller = ExtractController()

class URLListRequest(BaseModel):
    urls: list[str] = Field(..., description="List of URLs to extract contact information from")

@router.post("", response_model=Dict[str, ContactInfo])
def extract_from_urls(request: URLListRequest):
    return extract_controller.extract_contacts_from_urls(request.urls)

@router.post("/search", response_model=CombinedSearchExtractResponse)
async def search_and_extract(request: CombinedSearchExtractRequest):
    return await extract_controller.search_and_extract_contacts(request)
