import json
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers.string import StrOutputParser
from app.config import OPENAI_MODEL

class PersonaliseEmail:
    def __init__(self):
        self.llm = ChatOpenAI(model=OPENAI_MODEL)
        self.chain = self.llm | StrOutputParser()

    def personalise_email(self, subject: str, body: str, description: str) -> str:
        prompt = f"""
        Take the user's subject line, rough email draft, and target company information.

        1.Correct all grammatical and stylistic issues.
        2.Personalize the email using the company description provided to suit the company’s context.
        3.Make the language sound natural and human, avoiding overly formal or robotic tone.
        5.Keep the email concise, friendly, and professional.

        email subject: {subject}
        email body: {body}
        company description: {description}
        """

        try:
            response = self.chain.invoke(prompt)
            return response
        except Exception:
            return "Could not generate the email"
