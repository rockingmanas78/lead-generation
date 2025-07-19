from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional


class SearchResult(BaseModel):
    title: str
    link: str
    snippet: str
    source: Optional[str] = None
    rank: int


class PromptSearchRequest(BaseModel):
    prompt: str
    num_results: int = 6
    offset: int = 0


class PaginatedSearchResponse(BaseModel):
    results: List[SearchResult]
    pagination: Dict[str, Any]
    query_info: Dict[str, Any]
    session_info: Dict[str, Any]


class MoreResultsRequest(BaseModel):
    session_id: str
    num_results: int = 10


class ContactInfo(BaseModel):
    emails: List[str]
    phones: List[str]
    addresses: List[str]
    company_name: str
    description: str


class CombinedSearchExtractRequest(BaseModel):
    prompt: str
    num_results: int = 6
    offset: int = 0


class CombinedResult(BaseModel):
    search_result: SearchResult
    contact_info: ContactInfo


class CombinedSearchExtractResponse(BaseModel):
    results: List[CombinedResult]
    pagination: Dict[str, Any]
    query_info: Dict[str, Any]
    session_info: Dict[str, Any]


class ExtractSearchResponse(BaseModel):
    job_id: str
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    total_requested: int
    generated_count: int


class EmailSentimentAnalysisRequest(BaseModel):
    subject: str
    body: str


class EmailSentimentAnalysisResponse(BaseModel):
    sentiment: str


class ColdEmailTemplateRequest(BaseModel):
    user_prompt: str


class ColdEmailTemplateResponse(BaseModel):
    template: str


class PersonaliseEmailRequest(BaseModel):
    template: str
    company_contact_info: ContactInfo


class PersonaliseEmailResponse(BaseModel):
    """Personalise the email template"""

    subject: str = Field(description="The subject line of the email")
    email_body: str = Field(description="The body of the email")
