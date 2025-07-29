from fastapi import APIRouter, Depends, Request, BackgroundTasks
from app.auth.auth_bearer import JWTBearer
from app.services.scrape_linkedin import LinkedInScraper
from app.schemas import GetCompanySizeRequest, GetCompanySizeResponse

scraper = LinkedInScraper()

router = APIRouter(prefix="/get_company_size", tags=["get_company_size"])


@router.post(
    "", response_model=GetCompanySizeResponse, dependencies=[Depends(JWTBearer())]
)
async def get_company_size(
    request: GetCompanySizeRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
) -> GetCompanySizeResponse:
    token = await JWTBearer()(http_request)
    from app.config import JWT_SECRET, JWT_ALGORITHM
    import jwt

    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    user_id = payload.get("tenantId")

    background_tasks.add_task(
        scraper.scrape_and_store_companies, request.company_names, user_id
    )
    return GetCompanySizeResponse(response="OK")
