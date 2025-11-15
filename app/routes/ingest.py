# app/controllers/ingest_controller.py
from fastapi import APIRouter, Depends, Request, BackgroundTasks, HTTPException
from pydantic import BaseModel
import jwt
from app.auth.auth_bearer import JWTBearer
from app.services.database import db
from app.services.ingest import Ingest
from app.services.readiness import GenericReadiness
from app.config import JWT_SECRET, JWT_ALGORITHM
from app.schemas import IngestionRequest, IngestionResponse, IngestEntityResponse, ReadinessScoreResponse, IngestionSourcesEnum

ingest_service = Ingest()
readiness_service = GenericReadiness()

router = APIRouter(prefix="/ingest", tags=["ingest"])

# -----------------------
# Helpers
# -----------------------
async def _tenant_id_from_request(http_request: Request) -> str:
    token = await JWTBearer()(http_request)
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        print("Decoded JWT payload:", payload)
        tenant_id = payload.get("tenantId")
        if not tenant_id:
            print("tenantId missing in token payload.")
            raise HTTPException(status_code=403, detail="tenantId missing in token.")
        # Set RLS guard per request (Postgres GUC)
        await db.query_raw('SELECT set_config(\'app.tenant_id\', $1, false)', tenant_id)
        return tenant_id
    except Exception:
        print("Failed to decode JWT token.")
        raise HTTPException(status_code=403, detail="Invalid token.")

# -----------------------
# Routes
# ----------------------
@router.post("", response_model=IngestionResponse, dependencies=[Depends(JWTBearer())])
async def start_ingestion(request: IngestionRequest, http_request: Request, background_tasks: BackgroundTasks) -> IngestionResponse:
    tenant_id = await _tenant_id_from_request(http_request)

    # convert enums to their string values for the service
    source_values = [s.value for s in request.sources] if request.sources else [e.value for e in IngestionSourcesEnum]

    background_tasks.add_task(ingest_service.run_ingestion, source_values, tenant_id)
    return IngestionResponse(message="Ingestion started")

@router.post("/company-profile/{profile_id}", response_model=IngestEntityResponse, dependencies=[Depends(JWTBearer())])
async def ingest_company_profile(profile_id: str, http_request: Request) -> IngestEntityResponse:
    tenant_id = await _tenant_id_from_request(http_request)
    result = await ingest_service.ingest_company_profile_by_id(tenant_id, profile_id)
    return IngestEntityResponse(**result)

@router.post("/company-qa/{qa_id}", response_model=IngestEntityResponse, dependencies=[Depends(JWTBearer())])
async def ingest_company_qa(qa_id: str, http_request: Request) -> IngestEntityResponse:
    tenant_id = await _tenant_id_from_request(http_request)
    result = await ingest_service.ingest_company_qa_by_id(tenant_id, qa_id)
    return IngestEntityResponse(**result)

@router.post("/product/{product_id}", response_model=IngestEntityResponse, dependencies=[Depends(JWTBearer())])
async def ingest_product(product_id: str, http_request: Request) -> IngestEntityResponse:
    tenant_id = await _tenant_id_from_request(http_request)
    result = await ingest_service.ingest_product_by_id(tenant_id, product_id)
    return IngestEntityResponse(**result)

@router.post("/product-qa/{qa_id}", response_model=IngestEntityResponse, dependencies=[Depends(JWTBearer())])
async def ingest_product_qa(qa_id: str, http_request: Request) -> IngestEntityResponse:
    tenant_id = await _tenant_id_from_request(http_request)
    result = await ingest_service.ingest_product_qa_by_id(tenant_id, qa_id)
    return IngestEntityResponse(**result)

@router.post("/knowledge-document/{document_id}", response_model=IngestEntityResponse, dependencies=[Depends(JWTBearer())])
async def ingest_knowledge_document(document_id: str, http_request: Request) -> IngestEntityResponse:
    tenant_id = await _tenant_id_from_request(http_request)
    result = await ingest_service.ingest_knowledge_document_by_id(tenant_id, document_id)
    return IngestEntityResponse(**result)

@router.post("/website-content/{website_id}", response_model=IngestEntityResponse, dependencies=[Depends(JWTBearer())])
async def ingest_website_content(website_id: str, http_request: Request) -> IngestEntityResponse:
    tenant_id = await _tenant_id_from_request(http_request)
    result = await ingest_service.ingest_website_content_by_id(tenant_id, website_id)
    return IngestEntityResponse(**result)

@router.post("/readiness", response_model=ReadinessScoreResponse, dependencies=[Depends(JWTBearer())])
async def compute_generic_readiness(http_request: Request) -> ReadinessScoreResponse:
    tenant_id = await _tenant_id_from_request(http_request)
    print("Tenant ID for readiness computation:", tenant_id)
    result = await readiness_service.compute_and_store(tenant_id)
    return ReadinessScoreResponse(**result)



# from fastapi import APIRouter, Depends, Request, BackgroundTasks
# from app.auth.auth_bearer import JWTBearer
# from app.services.ingest import Ingest
# from app.schemas import IngestionRequest, IngestionResponse

# ingest_service = Ingest()

# router = APIRouter(prefix="/ingest", tags=["ingest"])


# @router.post("", response_model=IngestionResponse, dependencies=[Depends(JWTBearer())])
# async def start_ingestion(
#     request: IngestionRequest, http_request: Request, background_tasks: BackgroundTasks
# ) -> IngestionResponse:
#     token = await JWTBearer()(http_request)
#     from app.config import JWT_SECRET, JWT_ALGORITHM
#     import jwt

#     payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
#     user_id = payload.get("tenantId")
#     background_tasks.add_task(ingest_service.run_ingestion, request.sources, user_id)
#     return IngestionResponse(message="Ingestion process started in background")
