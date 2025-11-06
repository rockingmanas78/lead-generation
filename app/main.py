from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import router as api_router
from app.services.process_unfinished_queries import lifespan
from app.logging_config import configure_logging

# Logging configuration
configure_logging()

app = FastAPI(lifespan=lifespan)

# name the real origins you use
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "https://ai-sales-api-poc-staging.up.railway.app",
    "https://dashboard.salefunnel.in",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")
