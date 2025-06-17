from fastapi import APIRouter
from app.controllers.email import EmailController
from app.schemas import (
    EmailSentimentAnalysisRequest,
    EmailSentimentAnalysisResponse,
    ColdEmailTemplateRequest,
    ColdEmailTemplateResponse,
    PersonaliseEmailRequest,
    PersonaliseEmailResponse
)

router = APIRouter(prefix="/email", tags=["email"])
email_controller = EmailController()

@router.post("/analyse", response_model=EmailSentimentAnalysisResponse)
async def analyse_email(request: EmailSentimentAnalysisRequest):
    return await email_controller.analyse_email_sentiment(request)

@router.post("/template", response_model=ColdEmailTemplateResponse)
async def email_template_generator(request: ColdEmailTemplateRequest):
    return await email_controller.generate_email_template(request)

@router.post("/personalise", response_model=PersonaliseEmailResponse)
async def email_personalise(request: PersonaliseEmailRequest):
    return await email_controller.personalise_email(request)
