from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

# --- new ---
class ContactFocus(str, Enum):
    email = "email"
    phone = "phone"
    both = "both"

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
    # --- new knobs the service understands ---
    contact_focus: ContactFocus = ContactFocus.email
    exclude_aggregators: bool = False
    domains_hint: Optional[List[str]] = None  # e.g., ["site:.co.uk", "site:.ae"]

class CombinedResult(BaseModel):
    search_result: SearchResult
    contact_info: ContactInfo

class CombinedSearchExtractResponse(BaseModel):
    results: List[CombinedResult]
    pagination: Dict[str, Any]
    query_info: Dict[str, Any]
    session_info: Dict[str, Any]

class IngestionSourcesEnum(str, Enum):
    bulk_snippets = "bulk_snippets"
    company_profile = "company_profile"
    company_qa = "company_qa"
    knowledge_documents = "knowledge_documents"
    product = "product"
    product_qa = "product_qa"
    website_content = "website_content"

class IngestionRequest(BaseModel):
    sources: list[IngestionSourcesEnum] | None = None

class IngestEntityResponse(BaseModel):
    inserted: int
    reused: int
    deactivated: int
    skipped_similar: int

class ReadinessScoreResponse(BaseModel):
    score: int
class IngestionResponse(BaseModel):
    message: str

class RAGRequest(BaseModel):
    question: str
    sources: list[IngestionSourcesEnum] | None

class RAGResponse(BaseModel):
    answer: str

class ExtractSearchResponse(BaseModel):
    job_id: str
    message: str
    job_started_at: datetime

class JobStatusResponse(BaseModel):
    job_id: str
    total_requested: int
    generated_count: int
    status: str

class CombinedJobStatusContactInfoResponse(BaseModel):
    job_status_response: JobStatusResponse
    contact_infos: list[ContactInfo]
    retrieved_at: datetime

class EmailSentimentAnalysisRequest(BaseModel):
    subject: str
    body: str

class EmailSentimentAnalysisResponse(BaseModel):
    sentiment: str

class ColdEmailTemplateRequest(BaseModel):
    user_prompt: str
    # MVP customisation (snake_case)
    logo_url: Optional[str] = None
    brand_colors: List[str] = Field(default_factory=list)  # ordered
    font_family: Optional[str] = None
    show_header: bool = True
    show_footer: bool = True
    preheader: Optional[str] = None
    unsubscribe_url: Optional[str] = None

class ColdEmailTemplateResponse(BaseModel):
    # template: str
    subject: str
    body: str       # FULL compiled HTML (this maps to your Prisma `body`)
    text_part: str  

class EmailContent(BaseModel):
    # Copy blocks (no HTML here; renderer will wrap)
    greeting: str = Field(default="Hi {{contactName}},")
    opener: str
    value_props: List[str] = Field(default_factory=list)   # bullets (3–5)
    body_paragraph: Optional[str] = None                   # optional mid paragraph
    cta_text: Optional[str] = None                         # e.g., "Start free trial"
    cta_url: Optional[str] = None                          # e.g., "https://salefunnel.in/signup"
    closing: str = Field(default="Looking forward to hearing from you,")
    signature: Optional[str] = None                        # e.g., "— Team SalesFunnel"

    # Optional contact lines (used only if present)
    contact_email: Optional[str] = None                    # "mailto:" is added by renderer
    contact_phone: Optional[str] = None  

class PersonaliseEmailRequest(BaseModel):
    template: str
    company_contact_info: ContactInfo

class PersonaliseEmailResponse(BaseModel):
    """Personalise the email template"""
    subject: str = Field(description="The subject line of the email")
    email_body: str = Field(description="The body of the email")

class GetCompanySizeRequest(BaseModel):
    company_names: list[str]

class GetCompanySizeResponse(BaseModel):
    response: str

class SpamRequest(BaseModel):
    email_body: str

class SpamResponse(BaseModel):
    score: int

class GeneratedEmailResponse(BaseModel):
    response: str

class GeneratedEmailRequest(BaseModel):
    conversation_id: str
    campaign_id: str
    latest_email: str
    sender_name: str
    sender_email: str
    recipient_emails: list[str]
    lead_id: str

# class SearchResult(BaseModel):
#     title: str
#     link: str
#     snippet: str
#     source: Optional[str] = None
#     rank: int


# class PromptSearchRequest(BaseModel):
#     prompt: str
#     num_results: int = 6
#     offset: int = 0


# class PaginatedSearchResponse(BaseModel):
#     results: List[SearchResult]
#     pagination: Dict[str, Any]
#     query_info: Dict[str, Any]
#     session_info: Dict[str, Any]


# class MoreResultsRequest(BaseModel):
#     session_id: str
#     num_results: int = 10


# class ContactInfo(BaseModel):
#     emails: List[str]
#     phones: List[str]
#     addresses: List[str]
#     company_name: str
#     description: str


# class CombinedSearchExtractRequest(BaseModel):
#     prompt: str
#     num_results: int = 6
#     offset: int = 0


# class CombinedResult(BaseModel):
#     search_result: SearchResult
#     contact_info: ContactInfo


# class CombinedSearchExtractResponse(BaseModel):
#     results: List[CombinedResult]
#     pagination: Dict[str, Any]
#     query_info: Dict[str, Any]
#     session_info: Dict[str, Any]


# class IngestionSourcesEnum(str, Enum):
#     bulk_snippets = "bulk_snippets"
#     company_profile = "company_profile"
#     company_qa = "company_qa"
#     knowledge_documents = "knowledge_documents"
#     product = "product"
#     product_qa = "product_qa"
#     website_content = "website_content"


# class IngestionRequest(BaseModel):
#     sources: list[IngestionSourcesEnum] | None


# class IngestionResponse(BaseModel):
#     message: str


# class RAGRequest(BaseModel):
#     question: str
#     sources: list[IngestionSourcesEnum] | None


# class RAGResponse(BaseModel):
#     answer: str


# class ExtractSearchResponse(BaseModel):
#     job_id: str
#     message: str
#     job_started_at: datetime


# class JobStatusResponse(BaseModel):
#     job_id: str
#     total_requested: int
#     generated_count: int


# class CombinedJobStatusContactInfoResponse(BaseModel):
#     job_status_response: JobStatusResponse
#     contact_infos: list[ContactInfo]
#     retrieved_at: datetime


# class EmailSentimentAnalysisRequest(BaseModel):
#     subject: str
#     body: str


# class EmailSentimentAnalysisResponse(BaseModel):
#     sentiment: str


# class ColdEmailTemplateRequest(BaseModel):
#     user_prompt: str


# class ColdEmailTemplateResponse(BaseModel):
#     template: str


# class PersonaliseEmailRequest(BaseModel):
#     template: str
#     company_contact_info: ContactInfo


# class PersonaliseEmailResponse(BaseModel):
#     """Personalise the email template"""

#     subject: str = Field(description="The subject line of the email")
#     email_body: str = Field(description="The body of the email")


# class GetCompanySizeRequest(BaseModel):
#     company_names: list[str]


# class GetCompanySizeResponse(BaseModel):
#     response: str


# class SpamRequest(BaseModel):
#     email_body: str


# class SpamResponse(BaseModel):
#     score: int


# class GeneratedEmailResponse(BaseModel):
#     response: str


# class GeneratedEmailRequest(BaseModel):
#     conversation_id: str
#     campaign_id: str
#     latest_email: str
#     sender_name: str
#     sender_email: str
#     recipient_emails: list[str]
#     lead_id: str
