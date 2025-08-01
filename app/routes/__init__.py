from fastapi import APIRouter
from app.routes.search import router as search_router
from app.routes.email import router as email_router
from app.routes.extract import router as extract_router
from app.routes.health import router as health_router
from app.routes.ingest import router as ingest_router
from app.routes.rag import router as rag_router
from app.routes.spam_score import router as spam_score_router
from app.routes.get_company_size import router as get_company_size_router

router = APIRouter()

router.include_router(search_router)
router.include_router(email_router)
router.include_router(extract_router)
router.include_router(health_router)
router.include_router(ingest_router)
router.include_router(rag_router)
router.include_router(spam_score_router)
router.include_router(get_company_size_router)
