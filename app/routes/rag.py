from fastapi import APIRouter, Depends, Request
from app.auth.auth_bearer import JWTBearer
from app.services.rag import MultiTenantRAG
from app.schemas import RAGRequest, RAGResponse

rag = MultiTenantRAG()

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("", response_model=RAGResponse, dependencies=[Depends(JWTBearer())])
async def ask(request: RAGRequest, http_request: Request) -> RAGResponse:
    token = await JWTBearer()(http_request)
    from app.config import JWT_SECRET, JWT_ALGORITHM
    import jwt

    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    user_id = payload.get("tenantId")

    answer = await rag.query_llm(request.question, user_id, request.sources)
    return RAGResponse(answer=answer)
