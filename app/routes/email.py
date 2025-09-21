# app/routes/email.py
from fastapi import APIRouter, Depends, Request, HTTPException
from app.auth.auth_bearer import JWTBearer
from app.auth.internal_or_jwt import InternalOrJWTBearer
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

# Only these two paths can use the internal secret
internal_or_jwt = InternalOrJWTBearer(allowed_internal_paths={"/api/email/analyse", "/api/email/generate"})


@router.post(
    "/analyse",
    response_model=EmailSentimentAnalysisResponse,
    dependencies=[Depends(internal_or_jwt)],   # <- changed
)
async def analyse_email(request: EmailSentimentAnalysisRequest, http_request: Request):
    # If needed, you can check mode here:
    # mode = getattr(http_request.state, "auth", {}).get("mode")
    return await email_controller.analyse_email_sentiment(request)


@router.post(
    "/template",
    response_model=ColdEmailTemplateResponse,
    dependencies=[Depends(JWTBearer())],       # unchanged
)
async def email_template_generator(request: ColdEmailTemplateRequest):
    return await email_controller.generate_email_template(request)


@router.post(
    "/personalise",
    response_model=PersonaliseEmailResponse,
    dependencies=[Depends(JWTBearer())],       # unchanged
)
async def email_personalise(request: PersonaliseEmailRequest):
    return await email_controller.personalise_email(request)


@router.post(
    "/generate",
    response_model=GeneratedEmailResponse,
    dependencies=[Depends(internal_or_jwt)],   # <- changed
)
async def generate_email(request: GeneratedEmailRequest, http_request: Request):
    """
    In JWT mode: pull tenantId from the JWT (existing behavior).
    In internal mode: read x-tenant-id header (fallback) to keep downstream storage logic intact.
    """
    auth = getattr(http_request.state, "auth", {})
    mode = auth.get("mode")

    tenant_id = None
    if mode == "jwt":
        payload = auth.get("payload") or {}
        tenant_id = payload.get("tenantId")
    elif mode == "internal":
        # If your internal caller can pass tenant, read it here (minimal change):
        tenant_id = http_request.headers.get("tenant-id")
        if not tenant_id:
            # If you prefer hard-fail when tenantId is missing in internal mode:
            raise HTTPException(status_code=400, detail="x-tenant-id header required for internal calls.")
    else:
        # Shouldn't happen, but guard anyway
        raise HTTPException(status_code=403, detail="Unauthorized")

    return await store_generated_email(request, tenant_id)

# async def generate_email(request: GeneratedEmailRequest, http_request: Request):
#     token = await JWTBearer()(http_request)
#     from app.config import JWT_SECRET, JWT_ALGORITHM
#     import jwt

#     payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
#     user_id = payload.get("tenantId")
#     return await store_generated_email(request, user_id)


# from fastapi import APIRouter, Depends, Request
# from app.auth.auth_bearer import JWTBearer
# from app.controllers.email import EmailController
# from app.services.email_reply.database_storage import store_generated_email
# from app.schemas import (
#     EmailSentimentAnalysisRequest,
#     EmailSentimentAnalysisResponse,
#     ColdEmailTemplateRequest,
#     ColdEmailTemplateResponse,
#     PersonaliseEmailRequest,
#     PersonaliseEmailResponse,
#     GeneratedEmailResponse,
#     GeneratedEmailRequest,
# )

# router = APIRouter(prefix="/email", tags=["email"])
# email_controller = EmailController()


# @router.post(
#     "/analyse",
#     response_model=EmailSentimentAnalysisResponse,
#     dependencies=[Depends(JWTBearer())],
# )
# async def analyse_email(request: EmailSentimentAnalysisRequest):
#     return await email_controller.analyse_email_sentiment(request)


# @router.post(
#     "/template",
#     response_model=ColdEmailTemplateResponse,
#     dependencies=[Depends(JWTBearer())],
# )
# async def email_template_generator(request: ColdEmailTemplateRequest):
#     return await email_controller.generate_email_template(request)


# @router.post(
#     "/personalise",
#     response_model=PersonaliseEmailResponse,
#     dependencies=[Depends(JWTBearer())],
# )
# async def email_personalise(request: PersonaliseEmailRequest):
#     return await email_controller.personalise_email(request)


# @router.post(
#     "/generate",
#     response_model=GeneratedEmailResponse,
#     dependencies=[Depends(JWTBearer())],
# )
# async def generate_email(request: GeneratedEmailRequest, http_request: Request):
#     token = await JWTBearer()(http_request)
#     from app.config import JWT_SECRET, JWT_ALGORITHM
#     import jwt

#     payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
#     user_id = payload.get("tenantId")
#     return await store_generated_email(request, user_id)
