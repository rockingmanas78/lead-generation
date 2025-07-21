from fastapi import APIRouter, Depends, Request, BackgroundTasks
from app.auth.auth_bearer import JWTBearer
from app.services.ingest import Ingest
from app.schemas import IngestionRequest, IngestionResponse

ingest_service = Ingest()

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("", response_model=IngestionResponse, dependencies=[Depends(JWTBearer())])
async def start_ingestion(
    request: IngestionRequest, http_request: Request, background_tasks: BackgroundTasks
) -> IngestionResponse:
    token = await JWTBearer()(http_request)
    from app.config import JWT_SECRET, JWT_ALGORITHM
    import jwt

    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    user_id = payload.get("tenantId")
    background_tasks.add_task(ingest_service.run_ingestion, request.sources, user_id)
    return IngestionResponse(message="Ingestion process started in background")
