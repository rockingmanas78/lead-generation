from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal

# Updated to match your API's exact response labels
ValidationStatus = Literal[
    "verified",
    "not sure", 
    "its not mail"
]

class LeadCriteria(BaseModel):
    industry: Optional[str] = None
    location: Optional[str] = None
    role_keywords: List[str] = Field(default_factory=list)
    target_count: int = 20

class GoogleCustomSearchItem(BaseModel):
    title: Optional[str] = None
    link: Optional[str] = None
    displayLink: Optional[str] = None
    snippet: Optional[str] = None
    htmlSnippet: Optional[str] = None
    pagemap: Optional[Dict[str, Any]] = None

class CompanyState(BaseModel):
    company_domain: str
    seed_url: Optional[str] = None
    person_email_samples: List[str] = Field(default_factory=list)
    learned_email_patterns_ranked: List[str] = Field(default_factory=list)
    people_candidates: List["PersonCandidate"] = Field(default_factory=list)

class PersonCandidate(BaseModel):
    full_name: str
    role_hint: Optional[str] = None
    source_title: Optional[str] = None
    source_snippet: Optional[str] = None
    source_url: Optional[str] = None

class EmailValidationResult(BaseModel):
    address: Optional[str] = None
    # We use Optional[str] here to handle any unexpected API timeouts 
    # while the ValidationStatus above defines our "Success" targets.
    status: Optional[str] = None 
    sub_status: Optional[str] = None
    error: Optional[str] = None
    raw_response: Dict[str, Any] = Field(default_factory=dict)

class Lead(BaseModel):
    company_domain: str
    person_name: str
    role_hint: Optional[str] = None
    email: Optional[str] = None
    verification: Optional[EmailValidationResult] = None 

    status: Literal["confirmed", "probable", "rejected", "unverified"] = "unverified"
    confidence: float = 0.30