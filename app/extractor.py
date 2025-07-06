import logging
from fastapi import HTTPException
from app.services.html_fetcher import HTMLFetcher
from app.services.footer_parser import FooterParser
from app.services.llm_parser import LLMParser
from app.utils import extract_clean_text, merge_data, find_empty_fields, clean_phone_numbers

logger = logging.getLogger(__name__)

class ContactExtractor:
    def __init__(self):
        self.fetcher = HTMLFetcher()
        self.parser = FooterParser()
        self.llm = LLMParser()

    def extract(self, url: str) -> dict:
        try:
            html = self.fetcher.fetch(url)
        except:
            logger.error(f"Could not fetch the URL: {url}")
            raise

        if not html:
            return self.llm.extract_contact_info("")

        footer_text = self.parser.extract_footer(html)

        try:
            contact_info = self.llm.extract_contact_info(footer_text)
            missing_fields = find_empty_fields(contact_info)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Could not extract contact info: {str(e)}")

        if missing_fields:
            contact_links = self.parser.find_contact_links(html, url)
            for link in contact_links:
                contact_page_html = self.fetcher.fetch(link)
                if not contact_page_html:
                    continue

                contact_text = extract_clean_text(contact_page_html)

                try:
                    partial_info = self.llm.extract_missing_fields(contact_text, missing_fields)
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Could not extract missing fields: {str(e)}")

                contact_info = merge_data(contact_info, partial_info)
                if contact_info.get("emails"):
                    contact_info["emails"] = list(set(contact_info["emails"]))
                if contact_info.get("phones"):
                    contact_info["phones"] = clean_phone_numbers(contact_info["phones"])


                missing_fields = find_empty_fields(contact_info)
                if not missing_fields:
                    break

        return contact_info
