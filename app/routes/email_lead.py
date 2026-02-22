from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.services.pipeline.main import execute_pipeline

router = APIRouter()

class LeadRequest(BaseModel):
    prompt: str
    target: int = 20


@router.post("/lead/search")
async def search_leads(request: LeadRequest):
    try:
        leads = await execute_pipeline(
            prompt=request.prompt,
            target=request.target
        )

        return {
            "total": len(leads),
            "confirmed": sum(1 for l in leads if l.status == "confirmed"),
            "leads": leads
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))