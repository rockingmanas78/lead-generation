from fastapi import HTTPException
from app.services.email_sentiment_analysis import EmailSentimentAnalysis
from app.services.cold_email_template import ColdEmailTemplateGenerator
from app.services.email_personaliser import PersonaliseEmail
from app.schemas import (
    EmailSentimentAnalysisRequest,
    EmailSentimentAnalysisResponse,
    ColdEmailTemplateRequest,
    ColdEmailTemplateResponse,
    PersonaliseEmailRequest,
    PersonaliseEmailResponse
)

class EmailController:
    def __init__(self):
        self.sentiment_analyser = EmailSentimentAnalysis()
        self.cold_email_template_generator = ColdEmailTemplateGenerator()
        self.email_personaliser = PersonaliseEmail()

    async def analyse_email_sentiment(self, request: EmailSentimentAnalysisRequest) -> EmailSentimentAnalysisResponse:
        sentiment = self.sentiment_analyser.analyse_sentiment(request.subject, request.body)
        try:
            return EmailSentimentAnalysisResponse(sentiment=sentiment)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Could not analyse email sentiment: {str(e)}")

    async def generate_email_template(self, request: ColdEmailTemplateRequest) -> ColdEmailTemplateResponse:
        template = self.cold_email_template_generator.generate_cold_email_template(request.user_prompt)
        try:
            return ColdEmailTemplateResponse(template=template)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Could not generate cold email template: {str(e)}")

    async def personalise_email(self, request: PersonaliseEmailRequest) -> PersonaliseEmailResponse:
        try:
            return self.email_personaliser.personalise_email(
                request.template,
                request.company_contact_info
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Could not personalise email: {str(e)}")
