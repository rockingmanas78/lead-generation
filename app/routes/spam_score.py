from fastapi import APIRouter, Depends
from app.auth.auth_bearer import JWTBearer
from app.services.spam_score import SpamAnalyser
from app.schemas import SpamRequest, SpamResponse

spam_analyser = SpamAnalyser()

router = APIRouter(prefix="/get_spam_score", tags=["get_spam_score"])


@router.post("", response_model=SpamResponse, dependencies=[Depends(JWTBearer())])
async def get_spam_score(request: SpamRequest) -> SpamResponse:
    score = await spam_analyser.get_spam_score(request.email_body)
    return SpamResponse(score=score)
