from fastapi import APIRouter
from app.services.email_sentiment_analysis import EmailSentimentAnalysis
from app.services.cold_email_template import ColdEmailTemplateGenerator
from app.services.email_personaliser import PersonaliseEmail
from app.schemas import (
    EmailSentimentAnalysisRequest,
    EmailSentimentAnalysisResponse,
    ColdEmailTemplateRequest,
    ColdEmailTemplateResponse,
    PersonaliseEmailRequest,
    PersonaliseEmailResponse
)

router = APIRouter(prefix="/email", tags=["email"])

sentiment_analyser = EmailSentimentAnalysis()
cold_email_template_generator = ColdEmailTemplateGenerator()
email_personaliser = PersonaliseEmail()

@router.post("/analyse", response_model=EmailSentimentAnalysisResponse)
async def analyse_email(request: EmailSentimentAnalysisRequest):
    sentiment = sentiment_analyser.analyse_sentiment(request.subject, request.body)
    return EmailSentimentAnalysisResponse(sentiment=sentiment)

@router.post("/template", response_model=ColdEmailTemplateResponse)
async def email_template_generator(request: ColdEmailTemplateRequest):
    template = cold_email_template_generator.generate_cold_email_template(request.user_prompt)
    return ColdEmailTemplateResponse(template=template)

@router.post("/personalise", response_model=PersonaliseEmailResponse)
async def email_personalise(request: PersonaliseEmailRequest):
    email = email_personaliser.personalise_email(request.subject, request.body, request.company_description)
    return PersonaliseEmailResponse(email=email)
