from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict
from app.extractor import ContactExtractor
from app.schemas import ContactInfo, SearchResult
from app.services.search_engine import SearchEngine
from app.services.email_sentiment_analysis import EmailSentimentAnalysis
from app.services.cold_email_template import ColdEmailTemplateGenerator
from app.services.email_personaliser import PersonaliseEmail
from app.schemas import PromptSearchRequest, PaginatedSearchResponse, MoreResultsRequest, CombinedResult, CombinedSearchExtractResponse, CombinedSearchExtractRequest, EmailSentimentAnalysisRequest, EmailSentimentAnalysisResponse, ColdEmailTemplateResponse, ColdEmailTemplateRequest, PersonaliseEmailResponse, PersonaliseEmailRequest

router = APIRouter()

extractor = ContactExtractor()
search_engine = SearchEngine()
sentiment_analyser = EmailSentimentAnalysis()
cold_email_template_generator = ColdEmailTemplateGenerator()
email_personaliser = PersonaliseEmail()

class PromptRequest(BaseModel):
    prompt: str

class URLListRequest(BaseModel):
    urls: List[str]

@router.post("/search", response_model=PaginatedSearchResponse)
async def search_paginated(request: PromptSearchRequest):
    session_user = "default_user"
    result = await search_engine.search_with_offset(
        prompt=request.prompt,
        user_id=session_user,
        offset=request.offset,
        num_results=request.num_results
    )
    return PaginatedSearchResponse(**result)

@router.post("/search/more", response_model=PaginatedSearchResponse)
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

@router.post("/extract", response_model=Dict[str, ContactInfo])
def extract_from_urls(request: URLListRequest):
    results = {}
    for url in request.urls:
        contact = extractor.extract(url)
        results[url] = ContactInfo(**contact)
    return results

@router.post("/search_and_extract", response_model=CombinedSearchExtractResponse)
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

@router.post("/analyse_email", response_model=EmailSentimentAnalysisResponse)
async def analyse_email(request: EmailSentimentAnalysisRequest):
    sentiment = sentiment_analyser.analyse_sentiment(request.subject, request.body)
    return EmailSentimentAnalysisResponse(sentiment=sentiment)

@router.post("/email_template_generator", response_model=ColdEmailTemplateResponse)
async def email_template_generator(request: ColdEmailTemplateRequest):
    template = cold_email_template_generator.generate_cold_email_template(request.user_prompt)
    return ColdEmailTemplateResponse(template=template)

@router.post("/email_personalise", response_model=PersonaliseEmailResponse)
async def email_personalise(request: PersonaliseEmailRequest):
    email = email_personaliser.personalise_email(request.subject, request.body, request.company_description)
    return PersonaliseEmailResponse(email=email)
