import logging
from datetime import datetime
from prisma import Prisma
from typing import List, Dict, Optional
from app.services.html_fetcher import HTMLFetcher
from app.services.footer_parser import FooterParser
from app.services.llm_parser import LLMParser
from app.utils import extract_clean_text, merge_data, find_empty_fields, clean_phone_numbers

logger = logging.getLogger(__name__)
BATCH_SIZE = 5

async def process_urls_batch(
    urls: List[str],
    tenant_id: str,
    job_id: str,
    current_generated_count: int = 0
) -> Dict[str, Optional[dict]]:
    db = Prisma()
    await db.connect()

    try:
        fetcher = HTMLFetcher()
        parser = FooterParser()
        llm = LLMParser()

        batch_size = min(len(urls), BATCH_SIZE)
        results = {}
        generated_count = current_generated_count

        for i in range(0, len(urls), batch_size):
            batch = urls[i:i + batch_size]

            try:
                html_results = await fetcher.fetch(batch)
            except Exception as e:
                logger.error(f"Failed to fetch batch {batch}: {e}")
                html_results = {url: None for url in batch}

            all_contact_links = {}

            for url in batch:
                html = html_results.get(url)
                if not html:
                    results[url] = await llm.extract_contact_info("")
                    continue

                footer_text = parser.extract_footer(html)

                try:
                    contact_info = await llm.extract_contact_info(footer_text)
                    results[url] = contact_info

                    missing_fields = find_empty_fields(contact_info)
                    if missing_fields:
                        contact_links = parser.find_contact_links(html, url)
                        if contact_links:
                            all_contact_links[url] = contact_links

                except Exception as e:
                    logger.error(f"Failed to parse/extract {url}: {e}")
                    results[url] = {}

            if all_contact_links:
                all_links = []
                link_to_main_url = {}

                for main_url, contact_links in all_contact_links.items():
                    for link in contact_links:
                        all_links.append(link)
                        link_to_main_url[link] = main_url

                try:
                    contact_html_results = await fetcher.fetch(all_links)
                except Exception as e:
                    logger.error(f"Failed to fetch contact pages: {e}")
                    contact_html_results = {link: None for link in all_links}

                for link, contact_page_html in contact_html_results.items():
                    if not contact_page_html:
                        continue

                    main_url = link_to_main_url[link]
                    contact_info = results.get(main_url, {})
                    missing_fields = find_empty_fields(contact_info)

                    if not missing_fields:
                        continue

                    contact_text = extract_clean_text(contact_page_html)

                    try:
                        partial_info = await llm.extract_missing_fields(contact_text, missing_fields)
                        contact_info = merge_data(contact_info, partial_info)

                        if contact_info.get("emails"):
                            contact_info["emails"] = list(set(contact_info["emails"]))
                        if contact_info.get("phones"):
                            contact_info["phones"] = clean_phone_numbers(contact_info["phones"])

                        results[main_url] = contact_info

                    except Exception as e:
                        logger.error(f"Failed to extract from contact page {link}: {e}")

            for url in batch:
                contact = results.get(url)
                if not contact:
                    continue

                try:
                    company_name = contact.get("company_name", url)
                    emails = contact.get("emails") or [""]
                    phones = contact.get("phones") or [""]
                    addresses = contact.get("addresses") or [""]

                    existing_lead = await db.lead.find_first(
                        where={
                            "tenantId": tenant_id,
                            "companyName": company_name
                        }
                    )

                    if not existing_lead:
                        result = await db.lead.create(
                            data={
                                "tenantId": tenant_id,
                                "companyName": company_name,
                                "contactEmail": emails,
                                "contactPhone": phones,
                                "contactAddress": addresses,
                            }
                        )

                    generated_count += 1
                except Exception as e:
                    logger.error(f"Failed to insert lead for {url}: {e}")

            await db.leadgenerationjob.update(
                where={"id": job_id},
                data={"generatedCount": generated_count}
            )

        return results

    finally:
        await db.disconnect()
