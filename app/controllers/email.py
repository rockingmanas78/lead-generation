import re
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
from app.utils import render_email_html, strip_html, expand_font_stack, derive_palette
from app.schemas import EmailContent

ALLOWED_VARS = {"contactName", "companyName", "contactEmail", "contactPhone", "contactAddress"}
VAR_PATTERN = re.compile(r"\{\{\s*([A-Za-z][A-Za-z0-9_]*)\s*\}\}")
GENERIC_PHRASES = [
  "cutting-edge", "synergy", "state-of-the-art", "best-in-class",
  "world-class", "innovative solution", "revolutionary", "paradigm shift",
  "unlock your potential", "game-changing"
]

def _deflake(text: str) -> str:
    t = text or ""
    for g in GENERIC_PHRASES:
        t = re.sub(rf"\b{re.escape(g)}\b", "", t, flags=re.I)
    return re.sub(r"\s{2,}", " ", t).strip()

class EmailController:
    def __init__(self):
        self.sentiment_analyser = EmailSentimentAnalysis()
        self.cold_email_template_generator = ColdEmailTemplateGenerator()
        self.email_personaliser = PersonaliseEmail()

    async def analyse_email_sentiment(self, request: EmailSentimentAnalysisRequest) -> EmailSentimentAnalysisResponse:
        sentiment = await self.sentiment_analyser.analyse_sentiment(request.subject, request.body)
        try:
            return EmailSentimentAnalysisResponse(sentiment=sentiment)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Could not analyse email sentiment: {str(e)}")

    def _validate_vars(self, text: str, offenders: set[str]) -> None:
        for m in VAR_PATTERN.finditer(text or ""):
            token = m.group(1)
            if token not in ALLOWED_VARS:
                offenders.add(token)



    async def generate_email_template(self, request: ColdEmailTemplateRequest) -> ColdEmailTemplateResponse:
        # 1) Generate subject + structured content JSON (no HTML)
        subject, content_dict = await self.cold_email_template_generator.generate_subject_and_content(
            user_prompt=request.user_prompt,
            brand_colors=request.brand_colors,
            font_family=request.font_family,
            show_header=request.show_header,
            show_footer=request.show_footer,
            preheader=request.preheader,
        )

        # 2) Parse & validate variables across ALL content fields
        content = EmailContent(**content_dict)

        # ── De-flake/anti-buzzword clean-up BEFORE validation ─────────────────
        content.opener         = _deflake(content.opener or "")                     # NEW
        content.body_paragraph = _deflake(content.body_paragraph or "") if content.body_paragraph else None  # NEW
        content.value_props    = [_deflake(v) for v in (content.value_props or [])] # NEW
        offenders: set[str] = set()
        self._validate_vars(content.greeting, offenders)
        self._validate_vars(content.opener, offenders)
        for vp in (content.value_props or []):
            self._validate_vars(vp, offenders)
        self._validate_vars(content.body_paragraph or "", offenders)
        self._validate_vars(content.closing, offenders)
        self._validate_vars(content.signature or "", offenders)
        self._validate_vars(content.contact_email or "", offenders)
        self._validate_vars(content.contact_phone or "", offenders)

        if offenders:
            raise HTTPException(
                status_code=400,
                detail=f"Disallowed template variables: {sorted(offenders)}. Allowed: {sorted(ALLOWED_VARS)}"
            )

        # 3) Derive theme + font
        palette    = derive_palette(request.brand_colors)
        font_stack = expand_font_stack(request.font_family)

        print("Generated email template with subject:", subject)

        # 4) Render full HTML with brand colors, header/footer, bulletproof CTA
        full_html = render_email_html(
            subject=subject,
            content=content,
            logo_url=request.logo_url,
            palette=palette,
            font_stack=font_stack,
            show_header=request.show_header,
            show_footer=request.show_footer,
            preheader=request.preheader,
            unsubscribe_url=request.unsubscribe_url,
        )

        # 5) Plain text
        text_part = strip_html(full_html)

        return ColdEmailTemplateResponse(
            subject=subject,
            body=full_html,       # store into Prisma `body`
            text_part=text_part,  # store into Prisma `text_part`
        )

    async def personalise_email(self, request: PersonaliseEmailRequest) -> PersonaliseEmailResponse:
        try:
            return await self.email_personaliser.personalise_email(
                request.template,
                request.company_contact_info
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Could not personalise email: {str(e)}")
