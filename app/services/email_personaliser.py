import json
from langchain_openai import ChatOpenAI
from app.config import OPENAI_MODEL
from app.schemas import PersonaliseEmailResponse, ContactInfo

class PersonaliseEmail:
    def __init__(self):
        self.llm = ChatOpenAI(model=OPENAI_MODEL)

    def personalise_email(self, template: str, contact_info: ContactInfo) -> str:
        prompt = f"""
        Take the email template and target company information.

        1. Fill up all of the placeholder values in the template with the appropriate company-specific info.
        1.Correct all grammatical and stylistic issues.
        2.Personalize the email using the company description provided to suit the company’s context.
        3.Make the language sound natural and human, avoiding overly formal or robotic tone.
        5.Keep the email concise, friendly, and professional.

        email template: {template}
        company name: {contact_info.company_name}
        company email: {contact_info.emails}
        company mobile numbers: {contact_info.phones}
        company description: {contact_info.description}
        """

        try:
            structured_llm = self.llm.with_structured_output(PersonaliseEmailResponse, method="function_calling")
            response = structured_llm.invoke(prompt)
            return response
        except Exception:
            return PersonaliseEmailResponse(body="Could not generate the email")
