from fastapi import APIRouter, Depends, Request
from app.auth.auth_bearer import JWTBearer
from app.controllers.email import EmailController
from app.services.email_reply.database_storage import store_generated_email
from app.schemas import (
    EmailSentimentAnalysisRequest,
    EmailSentimentAnalysisResponse,
    ColdEmailTemplateRequest,
    ColdEmailTemplateResponse,
    PersonaliseEmailRequest,
    PersonaliseEmailResponse,
    GeneratedEmailResponse,
    GeneratedEmailRequest,
)

router = APIRouter(prefix="/email", tags=["email"])
email_controller = EmailController()


@router.post(
    "/analyse",
    response_model=EmailSentimentAnalysisResponse,
    dependencies=[Depends(JWTBearer())],
)
async def analyse_email(request: EmailSentimentAnalysisRequest):
    return await email_controller.analyse_email_sentiment(request)


@router.post(
    "/template",
    response_model=ColdEmailTemplateResponse,
    dependencies=[Depends(JWTBearer())],
)
async def email_template_generator(request: ColdEmailTemplateRequest):
    return await email_controller.generate_email_template(request)


@router.post(
    "/personalise",
    response_model=PersonaliseEmailResponse,
    dependencies=[Depends(JWTBearer())],
)
async def email_personalise(request: PersonaliseEmailRequest):
    return await email_controller.personalise_email(request)


@router.post(
    "/generate",
    response_model=GeneratedEmailResponse,
    dependencies=[Depends(JWTBearer())],
)
async def generate_email(request: GeneratedEmailRequest, http_request: Request):
    token = await JWTBearer()(http_request)
    from app.config import JWT_SECRET, JWT_ALGORITHM
    import jwt

    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    user_id = payload.get("tenantId")
    return await store_generated_email(request, user_id)
