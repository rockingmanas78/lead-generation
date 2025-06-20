from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])

@router.get("", response_model=str)
def get_health_status():
    return "healthy"
