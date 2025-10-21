import logging
from datetime import datetime
from typing import List, Dict, Optional
import re
from app.services.html_fetcher import HTMLFetcher
from app.services.footer_parser import FooterParser
from app.services.llm_parser import LLMParser
from app.services.database import db
from app.utils import (
    extract_clean_text,
    merge_data,
    find_empty_fields,
    clean_phone_numbers,
    clean_emails,
    unique_preserve_order,
)

## confidence logic
from app.services.lead_services import calculate_lead_confidence


logger = logging.getLogger(__name__)

BATCH_SIZE = 3
CONTACT_FOCUS = "email"  # current product focus; can be parameterized later if needed

def normalize_locations(locations: Optional[List[str]]) -> List[str]:
    if not locations:
        return []
    normalized: List[str] = []
    seen_lower: set[str] = set()
    for raw_location in locations:
        if not isinstance(raw_location, str):
            continue
        cleaned = re.sub(r"\s+", " ", raw_location).strip(" ,")
        key = cleaned.lower()
        if cleaned and key not in seen_lower:
            seen_lower.add(key)
            normalized.append(cleaned)
    return normalized


def compile_location_patterns(locations: List[str]) -> List[re.Pattern]:
    r"""
    Build regex patterns with word boundaries, allowing flexible whitespace inside multi-word locations.
    e.g., "New Delhi" -> r'\bNew\s+Delhi\b' (case-insensitive)
    """
    patterns: List[re.Pattern] = []
    for location_value in locations:
        # Escape then allow whitespace variability between tokens
        tokenized = re.escape(location_value).replace(r"\ ", r"\s+")
        try:
            compiled = re.compile(rf"(?i)\b{tokenized}\b")
            patterns.append(compiled)
        except re.error:
            # Fallback: simple case-insensitive substring search via regex
            compiled = re.compile(re.escape(location_value), flags=re.IGNORECASE)
            patterns.append(compiled)
    return patterns


def text_matches_any_location(text: str, location_patterns: List[re.Pattern]) -> bool:
    if not location_patterns:
        return True
    if not text:
        return False
    for compiled_pattern in location_patterns:
        if compiled_pattern.search(text):
            return True
    return False


async def process_urls_batch(
    urls: List[str], tenant_id: str, job_id: str, current_generated_count: int = 0,
    region_filters: Optional[List[str]] = None,
) -> Dict[str, Optional[dict]]:
    """
    Best-effort contact extraction for a list of URLs.
    - Fetch HTML with retries
    - Parse footer + JSON-LD
    - Fill missing fields from '/contact' style pages if present
    - Validate & dedupe emails/phones
    - Persist accepted leads (respecting CONTACT_FOCUS)
    - Update generatedCount only for accepted leads
    """
    try:
        html_fetcher = HTMLFetcher()
        footer_parser = FooterParser()
        llm_parser = LLMParser()

        # Prepare region filter
        normalized_locations = normalize_locations(region_filters)
        location_patterns = compile_location_patterns(normalized_locations)

        batch_size = min(len(urls), BATCH_SIZE) if len(urls) > 0 else 1
        results: Dict[str, Optional[dict]] = {}

        # Hold texts to evaluate region relevance later
        main_page_text_map: Dict[str, str] = {}
        footer_text_map: Dict[str, str] = {}
        supplemental_texts_map: Dict[str, List[str]] = {}

        generated_count = current_generated_count

        for batch_start in range(0, len(urls), batch_size):
            batch_urls = urls[batch_start: batch_start + batch_size]

            try:
                html_results = await html_fetcher.fetch(batch_urls)
            except Exception as fetch_error:
                logger.error(f"Failed to fetch batch {batch_urls}: {fetch_error}")
                html_results = {url: None for url in batch_urls}

            contact_links_lookup: Dict[str, List[str]] = {}
            for url in batch_urls:
                html_text = html_results.get(url)

                if not html_text:
                    # Try to keep structure consistent; empty HTML -> empty parse
                    contact_info = await llm_parser.extract_contact_info("")
                    results[url] = contact_info
                    main_page_text_map[url] = ""
                    footer_text_map[url] = ""
                    continue

                # capture main page cleaned text for location scoring
                cleaned_main_text = extract_clean_text(html_text)
                main_page_text_map[url] = cleaned_main_text

                footer_text = footer_parser.extract_footer(html_text)
                footer_text_map[url] = footer_text
                json_ld_info = footer_parser.extract_from_json_ld(html_text)

                try:
                    contact_info = await llm_parser.extract_contact_info(footer_text)
                    # merge JSON-LD into LLM output where missing
                    contact_info = merge_data(contact_info, json_ld_info)

                    results[url] = contact_info

                    missing_fields = find_empty_fields(contact_info)
                    if missing_fields:
                        possible_contact_links = footer_parser.find_contact_links(html_text, url)
                        if possible_contact_links:
                            contact_links_lookup[url] = possible_contact_links

                except Exception as parse_error:
                    logger.error(f"Failed to parse/extract {url}: {parse_error}")
                    results[url] = {}

            if contact_links_lookup:
                all_contact_links: List[str] = []
                link_to_main_url: Dict[str, str] = {}

                for main_url, link_list in contact_links_lookup.items():
                    for contact_link in link_list:
                        all_contact_links.append(contact_link)
                        link_to_main_url[contact_link] = main_url

                try:
                    contact_html_results = await html_fetcher.fetch(all_contact_links)
                except Exception as fetch_error:
                    logger.error(f"Failed to fetch contact pages: {fetch_error}")
                    contact_html_results = {link: None for link in all_contact_links}

                for contact_link, contact_page_html in contact_html_results.items():
                    if not contact_page_html:
                        continue

                    main_url = link_to_main_url[contact_link]
                    contact_info_existing = results.get(main_url, {}) or {}

                    missing_fields = find_empty_fields(contact_info_existing)
                    if not missing_fields:
                        # still record text for location matching
                        supplemental_texts_map.setdefault(main_url, []).append("")
                        continue

                    contact_page_text = extract_clean_text(contact_page_html)
                    supplemental_texts_map.setdefault(main_url, []).append(contact_page_text)
                    json_ld_from_contact_page = FooterParser().extract_from_json_ld(contact_page_html)

                    try:
                        partial_info = await llm_parser.extract_missing_fields(
                            contact_page_text, missing_fields
                        )
                        partial_info = merge_data(partial_info, json_ld_from_contact_page)

                        merged_info = merge_data(contact_info_existing, partial_info)

                        # validation & cleanup
                        if merged_info.get("emails"):
                            merged_info["emails"] = clean_emails(unique_preserve_order(merged_info["emails"]))
                        if merged_info.get("phones"):
                            merged_info["phones"] = clean_phone_numbers(unique_preserve_order(merged_info["phones"]))

                        results[main_url] = merged_info

                    except Exception as extract_error:
                        logger.error(f"Failed to extract from contact page {contact_link}: {extract_error}")

            # Persist accepted leads from this batch
            for url in batch_urls:
                contact = results.get(url)
                if not contact:
                    continue

                # Clean before decision
                emails_clean = clean_emails(contact.get("emails") or [])
                phones_clean = clean_phone_numbers(contact.get("phones") or [])
                addresses_list = contact.get("addresses") or []
                company_name_value = contact.get("company_name", url) or url

                # Focus rule: require email when CONTACT_FOCUS == 'email'
                if CONTACT_FOCUS == "email" and not emails_clean:
                    logger.info("lead_rejected_by_focus", extra={"url": url, "contact_focus": CONTACT_FOCUS})
                    continue

                # Soft region gating based ONLY on user-provided locations
                if location_patterns:
                    aggregate_text_for_location = " ".join([
                        company_name_value or "",
                        footer_text_map.get(url, "") or "",
                        main_page_text_map.get(url, "") or "",
                        " ".join(addresses_list) or "",
                        " ".join(supplemental_texts_map.get(url, [])) or "",
                    ])

                    if not text_matches_any_location(aggregate_text_for_location, location_patterns):
                        logger.info(
                            "lead_rejected_by_region",
                            extra={"url": url, "locations": normalized_locations}
                        )
                        continue

                try:
                    existing_lead = await db.lead.find_first(
                        where={"tenantId": tenant_id, "companyName": company_name_value}
                    )

                    if not existing_lead:
                        # create lead and capture returned record (Prisma returns the created object)
                        created_lead = await db.lead.create(
                            data={
                                "tenantId": tenant_id,
                                "jobId": job_id,
                                "companyName": company_name_value,
                                "contactEmail": emails_clean or [""],
                                "contactPhone": phones_clean or [""],
                                "contactAddress": addresses_list or [""],
                            }
                        )

                        # log insertion with context
                        logger.info("lead_inserted", extra={
                            "tenant": tenant_id,
                            "job": job_id,
                            "url": url,
                            "company": company_name_value,
                            "emails": emails_clean,
                            "phones": phones_clean,
                            "locations": normalized_locations,
                        })
                        print(created_lead)
                        print(created_lead.id, "created lead id")

                        # Prepare inputs for confidence calculation
                        lead_id = getattr(created_lead, "id", None) or created_lead.get("id") if isinstance(created_lead, dict) else None
                        our_company = {"description": company_name_value}

                        if lead_id:
                            try:
                                confidence = await calculate_lead_confidence(lead_id, our_company, tenant_id)
                                logger.info("lead_confidence_computed", extra={"lead_id": lead_id, "confidence": confidence})
                                
                            except Exception as conf_err:
                                logger.error(f"Failed to compute confidence for lead {lead_id}: {conf_err}")

                        generated_count += 1
                        


                    
                except Exception as persist_error:
                    logger.error(f"Failed to insert lead for {url}: {persist_error}")
                    # do not increment on failure

            await db.leadgenerationjob.update(
                where={"id": job_id}, data={"generatedCount": generated_count}
            )
            logger.info("batch_generated_progress", extra={"job": job_id, "generated_count": generated_count})

        return results

    except Exception as unexpected_error:
        logger.error(f"process_urls_batch function failed: {unexpected_error}")
        return {}

# import logging
# from datetime import datetime
# from prisma import Prisma
# from typing import List, Dict, Optional
# from app.services.html_fetcher import HTMLFetcher
# from app.services.footer_parser import FooterParser
# from app.services.llm_parser import LLMParser
# from app.services.database import db
# from app.utils import (
#     extract_clean_text,
#     merge_data,
#     find_empty_fields,
#     clean_phone_numbers,
# )

# logger = logging.getLogger(__name__)
# BATCH_SIZE = 3


# async def process_urls_batch(
#     urls: List[str], tenant_id: str, job_id: str, current_generated_count: int = 0
# ) -> Dict[str, Optional[dict]]:
#     try:
#         fetcher = HTMLFetcher()
#         parser = FooterParser()
#         llm = LLMParser()

#         batch_size = min(len(urls), BATCH_SIZE)
#         if batch_size == 0:
#             batch_size = 1
#         results = {}
#         generated_count = current_generated_count

#         for i in range(0, len(urls), batch_size):
#             batch = urls[i : i + batch_size]

#             try:
#                 html_results = await fetcher.fetch(batch)
#             except Exception as e:
#                 logger.error(f"Failed to fetch batch {batch}: {e}")
#                 html_results = {url: None for url in batch}

#             all_contact_links = {}

#             for url in batch:
#                 html = html_results.get(url)
#                 if not html:
#                     results[url] = await llm.extract_contact_info("")
#                     continue

#                 footer_text = parser.extract_footer(html)

#                 try:
#                     contact_info = await llm.extract_contact_info(footer_text)
#                     results[url] = contact_info

#                     missing_fields = find_empty_fields(contact_info)
#                     if missing_fields:
#                         contact_links = parser.find_contact_links(html, url)
#                         if contact_links:
#                             all_contact_links[url] = contact_links

#                 except Exception as e:
#                     logger.error(f"Failed to parse/extract {url}: {e}")
#                     results[url] = {}

#             if all_contact_links:
#                 all_links = []
#                 link_to_main_url = {}

#                 for main_url, contact_links in all_contact_links.items():
#                     for link in contact_links:
#                         all_links.append(link)
#                         link_to_main_url[link] = main_url

#                 try:
#                     contact_html_results = await fetcher.fetch(all_links)
#                 except Exception as e:
#                     logger.error(f"Failed to fetch contact pages: {e}")
#                     contact_html_results = {link: None for link in all_links}

#                 for link, contact_page_html in contact_html_results.items():
#                     if not contact_page_html:
#                         continue

#                     main_url = link_to_main_url[link]
#                     contact_info = results.get(main_url, {})
#                     missing_fields = find_empty_fields(contact_info)

#                     if not missing_fields:
#                         continue

#                     contact_text = extract_clean_text(contact_page_html)

#                     try:
#                         partial_info = await llm.extract_missing_fields(
#                             contact_text, missing_fields
#                         )
#                         contact_info = merge_data(contact_info, partial_info)

#                         if contact_info.get("emails"):
#                             contact_info["emails"] = list(set(contact_info["emails"]))
#                         if contact_info.get("phones"):
#                             contact_info["phones"] = clean_phone_numbers(
#                                 contact_info["phones"]
#                             )

#                         results[main_url] = contact_info

#                     except Exception as e:
#                         logger.error(f"Failed to extract from contact page {link}: {e}")

#             for url in batch:
#                 contact = results.get(url)
#                 if not contact:
#                     continue

#                 try:
#                     company_name = contact.get("company_name", url)
#                     emails = contact.get("emails") or [""]
#                     phones = contact.get("phones") or [""]
#                     addresses = contact.get("addresses") or [""]

#                     existing_lead = await db.lead.find_first(
#                         where={"tenantId": tenant_id, "companyName": company_name}
#                     )

#                     if not existing_lead:
#                         result = await db.lead.create(
#                             data={
#                                 "tenantId": tenant_id,
#                                 "jobId": job_id,
#                                 "companyName": company_name,
#                                 "contactEmail": emails,
#                                 "contactPhone": phones,
#                                 "contactAddress": addresses,
#                             }
#                         )

#                     generated_count += 1
#                 except Exception as e:
#                     logger.error(f"Failed to insert lead for {url}: {e}")
#                     generated_count -= 1

#             await db.leadgenerationjob.update(
#                 where={"id": job_id}, data={"generatedCount": generated_count}
#             )
#             print(f"generated {generated_count} leads")

#         return results

#     except Exception as e:
#         logger.error(f"process_url_batch function failed: {e}")
#         return {}
