from fastapi import APIRouter
from app.routes.search import router as search_router
from app.routes.email import router as email_router
from app.routes.extract import router as extract_router
from app.routes.health import router as health_router
from app.routes.ingest import router as ingest_router
from app.routes.rag import router as rag_router

router = APIRouter()

router.include_router(search_router)
router.include_router(email_router)
router.include_router(extract_router)
router.include_router(health_router)
router.include_router(ingest_router)
router.include_router(rag_router)
