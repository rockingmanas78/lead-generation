import json
from typing import List, Dict
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers.string import StrOutputParser
from app.config import OPENAI_MODEL

class LLMParser:
    def __init__(self):
        self.llm = ChatOpenAI(model=OPENAI_MODEL)
        self.chain = self.llm | StrOutputParser()

    def extract_contact_info(self, content: str) -> Dict:
        prompt = f"""
        Please extract contact information from the following text. 
        Look for and extract:
        1. Email addresses
        2. Phone/telephone numbers
        3. Physical addresses
        4. Company name
        5. Company description

        Text to analyze:
        {content}

        Respond in JSON:
        {{
            "emails": [],
            "phones": [],
            "addresses": [],
            "company_name": "",
            "description": ""
        }}
        Only respond with JSON.
        """

        try:
            response = self.chain.invoke(prompt)
            return json.loads(response)
        except Exception:
            return {
                "emails": [],
                "phones": [],
                "addresses": [],
                "company_name": "",
                "description": ""
            }

    def extract_missing_fields(self, content: str, missing_fields: List[str]) -> Dict:
        field_map = {
            "emails": "Email addresses",
            "phones": "Phone numbers",
            "addresses": "Physical addresses",
            "company_name": "Company name",
            "description": "Company description"
        }

        requested = [f"- {field_map[f]}" for f in missing_fields if f in field_map]
        if not requested:
            return {}

        prompt = f"""
        Please extract ONLY the following missing contact information from the text:
        {'\\n'.join(requested)}

        Text to analyze:
        {content}

        Respond in JSON format with only these fields:
        {{
            {', '.join([f'"{f}": []' if f in ["emails", "phones", "addresses"] else f'"{f}": ""' for f in missing_fields if f in field_map])}
        }}
        Only respond with JSON.
        """

        try:
            response = self.chain.invoke(prompt)
            return json.loads(response)
        except Exception:
            return {f: [] if f in ["emails", "phones", "addresses"] else "" for f in missing_fields}
