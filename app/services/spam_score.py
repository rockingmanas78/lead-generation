import logging
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from app.config import OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)


class SpamAnalyser:
    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=OPENAI_API_KEY, model=OPENAI_MODEL, temperature=0.2
        )

    async def get_spam_score(self, email_body: str) -> int:
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a spam classifier bot, that rates a given email on a scale of 0 (not spammy) to 10 (extremely spammy). You should only output the final score between 0 to 10 and nothing else.",
                ),
                ("human", "Email Body: {email_body}"),
            ]
        )

        chain = prompt | self.llm

        try:
            response = await chain.ainvoke({"email_body": email_body})
        except Exception as e:
            logger.error(f"Could not generate spam score: {e}")
            raise

        try:
            return int(response.content)
        except Exception as e:
            logger.error(
                f"Could not convert the response {response.content} to int: {e}"
            )
            raise
