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
        return EmailSentimentAnalysisResponse(sentiment=sentiment)

    async def generate_email_template(self, request: ColdEmailTemplateRequest) -> ColdEmailTemplateResponse:
        template = self.cold_email_template_generator.generate_cold_email_template(request.user_prompt)
        return ColdEmailTemplateResponse(template=template)

    async def personalise_email(self, request: PersonaliseEmailRequest) -> PersonaliseEmailResponse:
        email = self.email_personaliser.personalise_email(
            request.subject,
            request.body,
            request.company_description
        )
        return PersonaliseEmailResponse(email=email)
