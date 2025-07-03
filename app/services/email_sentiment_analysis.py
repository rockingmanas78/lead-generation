import json
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers.string import StrOutputParser
from app.config import OPENAI_MODEL

class EmailSentimentAnalysis:
    def __init__(self):
        self.llm = ChatOpenAI(model=OPENAI_MODEL)
        self.chain = self.llm | StrOutputParser()

    def analyse_sentiment(self, subject: str, body: str) -> str:
        prompt = f"""
        You are a helpful assistant for a sales agent. Your task is to analyze the subject and body of an email reply from a lead, and classify the email into one of the following four categories based on their intent and urgency:

        INTERESTED – The lead expresses interest in the product or service, wants more information, or is positive about moving forward.

        NOT INTERESTED – The lead explicitly states they are not interested or no longer wish to continue the conversation.

        FOLLOW UP – The lead shows potential interest but is not ready yet, requests to be contacted later, or postpones the discussion.

        IMMEDIATE ACTION REQUIRED – The lead is ready to proceed, asks for a call/demo/quote urgently, or requires fast follow-up to close the deal.

        Classify the following email into one of the four categories. Respond only with the category name.

        Subject: {subject}
        Body: {body}
        """

        try:
            response = self.chain.invoke(prompt)
            return response
        except Exception:
            raise
