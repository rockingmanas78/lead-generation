import logging
from fastapi import HTTPException
from typing import List, Dict, Optional
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

    async def extract(self, urls: List[str]) -> Dict[str, Optional[dict]]:
        try:
            html_results = await self.fetcher.fetch(urls)
        except Exception as e:
            logger.error(f"Could not fetch URLs: {e}")
            raise

        results = {}
        all_contact_links = {}

        for url in urls:
            html = html_results.get(url)
            if not html:
                results[url] = await self.llm.extract_contact_info("")
                continue

            footer_text = self.parser.extract_footer(html)

            try:
                contact_info = await self.llm.extract_contact_info(footer_text)
                missing_fields = find_empty_fields(contact_info)

                if missing_fields:
                    contact_links = self.parser.find_contact_links(html, url)
                    if contact_links:
                        all_contact_links[url] = contact_links

                results[url] = contact_info

            except Exception as e:
                logger.error(f"Could not extract contact info from {url}: {str(e)}")
                results[url] = {}

        if all_contact_links:
            all_links = []
            link_to_main_url = {}

            for main_url, contact_links in all_contact_links.items():
                for link in contact_links:
                    all_links.append(link)
                    link_to_main_url[link] = main_url

            contact_html_results = await self.fetcher.fetch(all_links)

            for link, contact_page_html in contact_html_results.items():
                if not contact_page_html:
                    continue

                main_url = link_to_main_url[link]
                contact_info = results[main_url]
                missing_fields = find_empty_fields(contact_info)

                if not missing_fields:
                    continue

                contact_text = extract_clean_text(contact_page_html)

                try:
                    partial_info = await self.llm.extract_missing_fields(contact_text, missing_fields)
                    contact_info = merge_data(contact_info, partial_info)

                    if contact_info.get("emails"):
                        contact_info["emails"] = list(set(contact_info["emails"]))
                    if contact_info.get("phones"):
                        contact_info["phones"] = clean_phone_numbers(contact_info["phones"])

                    results[main_url] = contact_info

                except Exception as e:
                    logger.error(f"Could not extract missing fields from {link}: {str(e)}")

        return results
