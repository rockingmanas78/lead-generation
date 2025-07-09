import json
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers.string import StrOutputParser
from app.config import OPENAI_MODEL

class ColdEmailTemplateGenerator:
    def __init__(self):
        self.llm = ChatOpenAI(model=OPENAI_MODEL)
        self.chain = self.llm | StrOutputParser()

    async def generate_cold_email_template(self, user_prompt: str) -> str:
        prompt = f"""
        Generate a professional and engaging cold sales email template based on the user's business description and target audience. The email should be concise, personalized, and optimized for conversions. Include:

        1. A compelling subject line
        2. A personalized greeting
        3. A clear value proposition
        4. A call-to-action

        user prompt: {user_prompt}
        """

        try:
            response = await self.chain.ainvoke(prompt)
            return response
        except Exception:
            raise
