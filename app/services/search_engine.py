import asyncio
import aiohttp
import hashlib
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain_core.output_parsers.string import StrOutputParser

from app.schemas import SearchResult
from app.config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_MODEL_DIVERSIFY, GOOGLE_API_KEY, GOOGLE_CSE_ID
from app.services.location import extract_locations

logger = logging.getLogger(__name__)

class SearchSession:
    def __init__(self, session_id: str, original_prompt: str, queries: List[str]):
        self.session_id = session_id
        self.original_prompt = original_prompt
        self.queries = queries
        self.results: List[Dict[str, Any]] = []
        self.query_positions = {query: 0 for query in queries}  # number of results walked so far
        self.created_at = datetime.now()
        self.last_accessed = datetime.now()
        self.total_api_calls = 0
        self.is_exhausted = False
        self.last_returned_offset = 0

    def add_results(self, new_results: List[Dict[str, Any]], query: str, fetched_count: int):
        self.results.extend(new_results)
        self.query_positions[query] += fetched_count
        self.last_accessed = datetime.now()
        self.total_api_calls += 1

    def get_results(self, offset: int, limit: int) -> List[Dict[str, Any]]:
        self.last_accessed = datetime.now()
        return self.results[offset: offset + limit]

    def needs_more_results(self, required_count: int) -> bool:
        return len(self.results) < required_count and not self.is_exhausted


class GoogleSearchError(Exception):
    pass


class SearchEngine:
    def __init__(self):
        self.google_api_key = GOOGLE_API_KEY
        self.google_cse_id = GOOGLE_CSE_ID
        self.sessions: Dict[str, SearchSession] = {}
        self.base_url = "https://www.googleapis.com/customsearch/v1"
        self.llm = ChatOpenAI(api_key=OPENAI_API_KEY, model=OPENAI_MODEL)

    def generate_session_id(self, user_id: str, prompt: str) -> str:
        base = f"{user_id}_{prompt}_{datetime.now().date()}"
        return hashlib.md5(base.encode()).hexdigest()

    async def prompt_to_queries(
        self,
        user_prompt: str,
        inferred_locations: Optional[List[str]] = None,
        contact_focus: str = "email",
    ) -> List[str]:
        """
        Use the LLM to craft diverse, high-recall queries targeting contact info.
        Returns up to 5 queries.
        """
        if inferred_locations is None:
            inferred_locations = extract_locations(user_prompt)

        system_prompt = f"""
You are a lead-generation query writer. Produce 4 Google-ready queries (comma-separated, plain text; no numbering, no markdown)
to find company contact details. Optimize for {contact_focus}.

Rules:
- Use diverse phrasings (mix company type + location + "contact", "email", "reach us", "support", etc.)
- Prefer official websites and "Contact", "About", "Support" pages over aggregator/listicle sites.
- Avoid generic "best/top/list of" or directory-only patterns.
- Include locations if present, naturally.

Locations to target: {", ".join(inferred_locations) if inferred_locations else "None"}
User prompt: {user_prompt}
""".strip()

        llm = ChatOpenAI(
        api_key=OPENAI_API_KEY,
        model=OPENAI_MODEL_DIVERSIFY,                 #function uses GPT-4.1
        temperature=0.4
        )
        
        chain = ChatPromptTemplate.from_messages([("system", system_prompt)]) | llm | StrOutputParser()
        output_text = await chain.ainvoke({})

        # Parse back to a flat list from comma/line separated values
        raw_lines = [line.strip().strip('"').strip("'") for line in output_text.strip().split("\n") if line.strip()]
        queries: List[str] = []
        for raw_line in raw_lines:
            parts = [part.strip().strip('"').strip("'") for part in raw_line.split(",") if part.strip()]
            queries.extend(parts)

        # Conservative cap and length filter
        queries = [query for query in queries if len(query) > 5][:5]
        logger.info("llm_queries", extra={"queries": queries})
        return queries

    async def diversify_prompt(
        self,
        user_prompt: str,
        inferred_locations: Optional[List[str]] = None,
        contact_focus: str = "email",
    ) -> List[str]:
        """
        Second-stage fallback LLM function.
        Creates broader, more creative variations of the user prompt
        when Google's search is exhausted. Uses GPT-4.1 only here.
        Returns up to 5 diversified queries.
        """

        if inferred_locations is None:
            inferred_locations = extract_locations(user_prompt)

        system_prompt = f"""
You are an advanced query diversifier. The system failed to find enough Google results,
so your job is to rewrite the user's intent into 5 broader, creative search queries
that still aim to find company contact information.

Rules:
- Keep the queries plain text, comma-separated, no numbering and no markdown.
- Use synonyms like "vendor", "supplier", "business directory", "corporate office", 
"customer service", "email support", "official contact".
- Add wider intent: industry keywords, related services, indirect ways people list contacts.
- Still avoid aggregator spam.
- Use the user's locations naturally.

Locations: {", ".join(inferred_locations) if inferred_locations else "None"}
User Prompt: {user_prompt}
""".strip()

        llm = ChatOpenAI(
            api_key=OPENAI_API_KEY,
            model=OPENAI_MODEL_DIVERSIFY,      #function uses GPT-4.1
            temperature=0.8
        )

        chain = ChatPromptTemplate.from_messages([("system", system_prompt)]) | llm | StrOutputParser()
        output_text = await chain.ainvoke({})

        # Parse back to a clean list
        raw_lines = [
            line.strip().strip('"').strip("'")
            for line in output_text.split("\n")
            if line.strip()
        ]

        diversified: List[str] = []
        for raw_line in raw_lines:
            parts = [
                p.strip().strip('"').strip("'")
                for p in raw_line.split(",")
                if p.strip()
            ]
            diversified.extend(parts)

        diversified = [q for q in diversified if len(q) > 5][:5]

        logger.info("llm_diversified_queries", extra={"queries": diversified})
        return diversified

    def build_query(self, query: str, inferred_locations: Optional[List[str]] = None) -> str:
        """
        Keep aggregator exclusions and optionally append quoted locations.
        """
        aggregator_domains = [
            "justdial.com", "sulekha.com", "indiamart.com", "yellowpages.", "yelp.",
            "tripadvisor.", "zomato.com", "clutch.co", "g2.com", "capterra",
            "goodfirms", "topdevelopers", "serchen.com", "reddit.com"
        ]
        exclusion_terms = ' -"Top" -"Best" -"List of"'
        excluded_sites = " ".join([f"-site:{domain}" for domain in aggregator_domains])

        location_terms = ""
        if inferred_locations:
            quoted_locations = " ".join([f"\"{location}\"" for location in inferred_locations])
            location_terms = f" {quoted_locations}"

        final_query = f"{query}{location_terms} {excluded_sites}{exclusion_terms}".strip()
        return final_query

    async def call_google_search_api(
        self,
        query: str,
        start_index: int = 1,
        results_to_fetch: int = 10,
        inferred_locations: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Call Google CSE. 'start_index' must be 1-based. Returns normalized items.
        """
        print(f"Calling Google CSE for query: {query}, start_index: {start_index}, results_to_fetch: {results_to_fetch}, inferred_locations: {inferred_locations}")
        modified_query = self.build_query(query, inferred_locations)
        safe_num = max(1, min(10, results_to_fetch))
        params = {
            "q": modified_query,
            "key": self.google_api_key,
            "cx": self.google_cse_id,
            "start": start_index,          # CSE is 1-based
            "num": safe_num,
        }

        try:
            async with aiohttp.ClientSession() as http_session:
                async with http_session.get(self.base_url, params=params, timeout=12) as response:
                    if response.status == 200:
                        data = await response.json()
                        items = data.get("items", [])
                        if not items:
                            logger.info("cse_empty", extra={
                                "query": modified_query, "start": start_index, "num": safe_num
                            })
                            return []
                        normalized_results: List[Dict[str, Any]] = []
                        for index, item in enumerate(items):
                            normalized_results.append({
                                "title": item.get("title", ""),
                                "link": item.get("link", ""),
                                "snippet": item.get("snippet", ""),
                                "source": item.get("displayLink", ""),
                                "rank": start_index + index
                            })
                        return normalized_results

                    # Non-200 => detailed error
                    try:
                        error_payload = await response.json()
                    except Exception:
                        error_payload = {"status": response.status}

                    logger.error("cse_error", extra={
                        "status": response.status,
                        "query": modified_query,
                        "start": start_index,
                        "num": safe_num,
                        "error": error_payload
                    })
                    if response.status in (403, 429):
                        print(f"Google CSE error {response.status}: {error_payload}")
                        raise GoogleSearchError("CSE HTTP " + str(response.status))
                    raise GoogleSearchError(f"Search service error {response.status}")

        except asyncio.TimeoutError:
            logger.error("cse_timeout", extra={"query": modified_query})
            raise GoogleSearchError("Search request timed out")
        except aiohttp.ClientError as client_error:
            logger.error("cse_client_error", extra={"error": str(client_error)})
            raise GoogleSearchError(f"Search service unavailable: {client_error}")
        except GoogleSearchError:
            raise
        except Exception as unexpected_error:
            logger.error("cse_unknown_error", extra={"error": str(unexpected_error)})
            raise GoogleSearchError(f"Unexpected search error {unexpected_error}")

    async def fetch_more_results(self, session: SearchSession, target_count: int):
        """
        Fetch more results, cycling queries until we reach target_count or exhaust.
        """
        current_count = len(session.results)
        if current_count >= target_count or session.is_exhausted:
            return

        needed = target_count - current_count
        raw_locations = extract_locations(session.original_prompt)
        inferred_locations = [
            loc for loc in raw_locations
            if loc.replace(",", "").replace(".", "").count(" ") <= 1
            and len(loc) <= 30
            and not loc.lower().startswith("agri")
        ]

        for query in session.queries:
            if needed <= 0:
                break

            current_position = session.query_positions[query]  # how many fetched so far for this query
            if current_position >= 100:  # CSE hard limit
                continue

            batch_size = min(10, needed)
            # start index is 1-based
            new_results = await self.call_google_search_api(
                query=query,
                start_index=current_position + 1,
                results_to_fetch=batch_size,
                inferred_locations=inferred_locations,
            )

            if not new_results:
                continue

            existing_links = {result["link"] for result in session.results}
            filtered_results = [res for res in new_results if res["link"] not in existing_links]

            session.add_results(filtered_results, query, len(new_results))
            needed -= len(filtered_results)

        if len(session.results) == current_count:
            session.is_exhausted = True

        # Summary log (for observability)
        logger.info("cse_summary", extra={
            "session_id": session.session_id,
            "summary": {
                "requested": target_count,
                "returned": len(session.results),
                "overfetched_items": max(0, len(session.results) - target_count),
                "keywords_used": session.queries,
                "discovered_sources": len(session.results),
                "contact_focus": "email",
                "locations_used": inferred_locations,
            }
        })

    async def search_with_offset(
        self, prompt: str, user_id: str, offset: int, num_results: int
    ) -> Dict[str, Any]:
        session_id = self.generate_session_id(user_id, prompt)

        if session_id not in self.sessions:
            raw_locations = extract_locations(prompt)
            inferred_locations = [
                loc for loc in raw_locations
                if loc.replace(",", "").replace(".", "").count(" ") <= 1
                and len(loc) <= 30
                and not loc.lower().startswith("agri")
            ]
            queries = await self.prompt_to_queries(prompt, inferred_locations)
            print(f"Generated queries: {queries} for prompt: {prompt} with locations: {inferred_locations}")
            self.sessions[session_id] = SearchSession(session_id, prompt, queries)
            await self.fetch_more_results(self.sessions[session_id], offset + num_results + 10)

        # FALLBACK: No results → diversify prompt
        if len(self.sessions[session_id].results) == 0:
            print("Primary queries returned no results. Running diversification fallback...")
            
            diversified = await self.diversify_prompt(prompt, inferred_locations)
            print("Diversified queries:", diversified)

            # Replace queries in the session
            self.sessions[session_id].queries = diversified

            # Retry fetching with fallback queries
            await self.fetch_more_results(self.sessions[session_id], offset + num_results + 10)

        session = self.sessions[session_id]

        required_total = offset + num_results
        if session.needs_more_results(required_total):
            await self.fetch_more_results(session, required_total + 10)

        sliced_results = session.get_results(offset, num_results)
        session.last_returned_offset = offset + len(sliced_results)

        has_more = (offset + len(sliced_results)) < len(session.results) or not session.is_exhausted

        return {
            "results": [SearchResult(**r) for r in sliced_results],
            "pagination": {
                "offset": offset,
                "results_returned": len(sliced_results),
                "total_results_available": len(session.results),
                "has_more": has_more,
                "next_offset": offset + len(sliced_results) if has_more else None
            },
            "session_info": {
                "session_id": session.session_id,
                "total_results": len(session.results),
                "created_at": session.created_at,
                "last_accessed": session.last_accessed,
                "is_exhausted": session.is_exhausted,
            },
            "query_info": {
                "original_prompt": session.original_prompt,
                "generated_queries": session.queries,
                "query_positions": session.query_positions,
            }
        }

    async def get_more_results(self, session_id: str, num_results: int) -> Dict[str, Any]:
        if session_id not in self.sessions:
            raise ValueError("Session not found or expired")

        session = self.sessions[session_id]
        current_offset = session.last_returned_offset
        required_total = current_offset + num_results

        if session.needs_more_results(required_total):
            await self.fetch_more_results(session, required_total + 10)

        sliced_results = session.get_results(current_offset, num_results)
        session.last_returned_offset = current_offset + len(sliced_results)

        has_more = session.last_returned_offset < len(session.results) or not session.is_exhausted

        return {
            "results": [SearchResult(**r) for r in sliced_results],
            "pagination": {
                "offset": current_offset,
                "results_returned": len(sliced_results),
                "total_results_available": len(session.results),
                "has_more": has_more,
                "next_offset": session.last_returned_offset if has_more else None
            },
            "session_info": {
                "session_id": session.session_id,
                "total_results_served": session.last_returned_offset,
                "last_accessed": session.last_accessed,
                "is_exhausted": session.is_exhausted
            },
            "query_info": {
                "original_prompt": session.original_prompt,
                "generated_queries": session.queries,
                "query_positions": session.query_positions
            }
        }



# import os
# import hashlib
# import asyncio
# import aiohttp
# import logging
# from datetime import datetime, timedelta
# from typing import List, Dict, Any, Optional
# from langchain_openai import ChatOpenAI
# from langchain.prompts import ChatPromptTemplate
# from langchain_core.output_parsers.string import StrOutputParser
# from app.schemas import SearchResult
# from app.config import OPENAI_API_KEY, OPENAI_MODEL, GOOGLE_API_KEY, GOOGLE_CSE_ID

# logger = logging.getLogger(__name__)

# class SearchSession:
#     def __init__(self, session_id: str, original_prompt: str, queries: List[str]):
#         self.session_id = session_id
#         self.original_prompt = original_prompt
#         self.queries = queries
#         self.results: List[Dict] = []
#         self.query_positions = {query: 0 for query in queries}
#         self.created_at = datetime.now()
#         self.last_accessed = datetime.now()
#         self.total_api_calls = 0
#         self.is_exhausted = False
#         self.last_returned_offset = 0

#     def add_results(self, new_results: List[Dict], query: str, fetched_count: int):
#         self.results.extend(new_results)
#         self.query_positions[query] += fetched_count
#         self.last_accessed = datetime.now()
#         self.total_api_calls += 1

#     def get_results(self, offset: int, limit: int) -> List[Dict]:
#         self.last_accessed = datetime.now()
#         return self.results[offset:offset + limit]

#     def needs_more_results(self, required_count: int) -> bool:
#         return len(self.results) < required_count and not self.is_exhausted

# class GoogleSearchError(Exception):
#     pass

# class SearchEngine:
#     def __init__(self):
#         self.google_api_key = os.getenv("GOOGLE_API_KEY")
#         self.google_cse_id = os.getenv("GOOGLE_CSE_ID")
#         self.sessions: Dict[str, SearchSession] = {}
#         self.base_url = "https://www.googleapis.com/customsearch/v1"
#         self.llm = ChatOpenAI(api_key=OPENAI_API_KEY, model=OPENAI_MODEL)

#     async def prompt_to_queries(self, user_prompt: str) -> List[str]:
#         prompt = ChatPromptTemplate.from_messages([
#             ("system", """
#             You are a lead generation specialist. Generate 2 high-recall search queries to find contact information for the user.

#             Requirements:
#             1. Create diverse queries using different keyword combinations
#             2. Include location-specific terms
#             3. Use industry-specific terminology
#             4. Do not search for aggregator websites.
#             5. Focus on findable contact information


#             Format each query to be Google search-ready.

#             Example patterns to follow:
#             - Direct business type + location + contact
#             - Industry associations + location
#             - Business directories + specific terms
#             - Professional networks + area
#             - Service-specific searches

#             Only generate the queries and nothing else. generate the queries separated by commas but do not write them in markdown, just give me plaintext
#             """),
#             ("human", "{prompt}")
#         ])

#         chain = prompt | self.llm | StrOutputParser()

#         try:
#             output = await chain.ainvoke({"prompt": user_prompt})

#             queries = []
#             for line in output.strip().split('\n'):
#                 clean_line = line.strip()

#                 import re
#                 clean_line = re.sub(r'^\d+[\.\)]\s*', '', clean_line)
#                 clean_line = re.sub(r'^[-*]\s*', '', clean_line)
#                 clean_line = clean_line.strip('"').strip("'")

#                 if clean_line and len(clean_line) > 5:
#                     queries.append(clean_line)

#             if not queries and ',' in output:
#                 queries = [q.strip().strip('"').strip("'") for q in output.split(',') if q.strip()]

#             if not queries:
#                 base_terms = user_prompt.lower()
#                 queries = [
#                     f"{base_terms} contact information",
#                     f"{base_terms} email phone",
#                     f"{base_terms} address contact details"
#                 ]

#             print(f"searching these queries: {queries[:5]}")
#             return queries[:5]

#         except Exception as e:
#             logger.error(f"OpenAI API error in prompt_to_queries: {e}")
#             raise

#     def generate_session_id(self, user_id: str, prompt: str) -> str:
#         base = f"{user_id}_{prompt}_{datetime.now().date()}"
#         return hashlib.md5(base.encode()).hexdigest()

#     def build_query(self, query: str) -> str:
#         AGGREGATOR_KEYWORDS = [
#             "justdial.com", "sulekha.com", "indiamart.com", "yellowpages.in", "yelp.com",
#             "tripadvisor.in", "zomato.com", "magicbricks.com", "99acres.com", "housing.com",
#             "makemytrip.com", "goibibo.com", "trivago.in", "booking.com", "airbnb.com", "hotels.com",
#             "trustpilot.com", "glassdoor.com", "g2.com", "clutch.co", "upcity.com", "designrush.com",
#             "comparisun.com", "bestfirms.com", "businesslist.io", "goodfirms.co", "capterra.in",
#             "topdevelopers.co", "serchen.com", "reddit.com"
#         ]

#         EXCLUDE_KEYWORD = '"Top"'

#         excluded_sites = " ".join([f"-site:{site}" for site in AGGREGATOR_KEYWORDS])

#         return f"{query} {excluded_sites} -{EXCLUDE_KEYWORD}"

#     async def call_google_search_api(self, query: str, start: int = 0, num: int = 10) -> List[Dict]:
#         modified_query = self.build_query(query)
#         num = max(1, min(10, num))

#         params = {
#             "q": modified_query,
#             "key": self.google_api_key,
#             "cx": self.google_cse_id,
#             "start": start,
#             "num": num,
#         }

#         try:
#             async with aiohttp.ClientSession() as session:
#                 async with session.get(self.base_url, params=params, timeout=10) as response:
#                     if response.status == 200:
#                         data = await response.json()
#                         if "items" not in data:
#                             logger.info(f"No search results found for query: {query}")
#                             return []

#                         results = data.get("items", [])
#                         return [
#                             {
#                                 "title": item.get("title", ""),
#                                 "link": item.get("link", ""),
#                                 "snippet": item.get("snippet", ""),
#                                 "source": item.get("displayLink", ""),
#                                 "rank": start + i + 1
#                             }
#                             for i, item in enumerate(results)
#                         ]
#                     else:
#                         error_msg = f"Google API error: HTTP {response.status}"
#                         if response.status == 429:
#                             error_msg += " - Rate limit exceeded"
#                         elif response.status == 403:
#                             error_msg += " - API key invalid or quota exceeded"

#                         logger.error(error_msg)
#                         raise GoogleSearchError(error_msg)

#         except asyncio.TimeoutError:
#             logger.error(f"Google API request timed out for query: {query}")
#             raise GoogleSearchError("Search request timed out")
#         except aiohttp.ClientError as e:
#             logger.error(f"Google API client error: {e}")
#             raise GoogleSearchError(f"Search service unavailable: {e}")
#         except Exception as e:
#             logger.error(f"Unexpected error in Google search: {e}")
#             raise GoogleSearchError(f"Search service error {e}")

#     async def fetch_more_results(self, session: SearchSession, target_count: int):
#         current_count = len(session.results)
#         if current_count >= target_count or session.is_exhausted:
#             return

#         needed = target_count - current_count

#         for query in session.queries:
#             if needed <= 0:
#                 break

#             current_position = session.query_positions[query]
#             if current_position >= 100:
#                 continue

#             batch_size = min(10, needed)
#             new_results = await self.call_google_search_api(query, current_position, batch_size)

#             if not new_results:
#                 continue

#             existing_links = {r["link"] for r in session.results}
#             filtered = [r for r in new_results if r["link"] not in existing_links]

#             session.add_results(filtered, query, len(new_results))
#             needed -= len(filtered)

#         if len(session.results) == current_count:
#             session.is_exhausted = True

#     async def search_with_offset(
#         self, prompt: str, user_id: str, offset: int, num_results: int
#     ) -> Dict[str, Any]:
#         session_id = self.generate_session_id(user_id, prompt)

#         if session_id not in self.sessions:
#             queries = await self.prompt_to_queries(prompt)
#             self.sessions[session_id] = SearchSession(session_id, prompt, queries)
#             await self.fetch_more_results(self.sessions[session_id], offset + num_results + 10)

#         session = self.sessions[session_id]

#         required_total = offset + num_results
#         if session.needs_more_results(required_total):
#             await self.fetch_more_results(session, required_total + 10)

#         results = session.get_results(offset, num_results)
#         session.last_returned_offset = offset + len(results)

#         has_more = (offset + len(results)) < len(session.results) or not session.is_exhausted

#         return {
#             "results": [SearchResult(**r) for r in results],
#             "pagination": {
#                 "offset": offset,
#                 "results_returned": len(results),
#                 "total_results_available": len(session.results),
#                 "has_more": has_more,
#                 "next_offset": offset + len(results) if has_more else None
#             },
#             "session_info": {
#                 "session_id": session.session_id,
#                 "total_results": len(session.results),
#                 "created_at": session.created_at,
#                 "last_accessed": session.last_accessed,
#                 "is_exhausted": session.is_exhausted,
#             },
#             "query_info": {
#                 "original_prompt": session.original_prompt,
#                 "generated_queries": session.queries,
#                 "query_positions": session.query_positions,
#             }
#         }

#     async def get_more_results(self, session_id: str, num_results: int) -> Dict[str, Any]:
#         if session_id not in self.sessions:
#             raise ValueError("Session not found or expired")

#         session = self.sessions[session_id]
#         current_offset = session.last_returned_offset
#         required_total = current_offset + num_results

#         if session.needs_more_results(required_total):
#             await self.fetch_more_results(session, required_total + 10)

#         results = session.get_results(current_offset, num_results)
#         session.last_returned_offset = current_offset + len(results)

#         has_more = session.last_returned_offset < len(session.results) or not session.is_exhausted

#         return {
#             "results": [SearchResult(**r) for r in results],
#             "pagination": {
#                 "offset": current_offset,
#                 "results_returned": len(results),
#                 "total_results_available": len(session.results),
#                 "has_more": has_more,
#                 "next_offset": session.last_returned_offset if has_more else None
#             },
#             "session_info": {
#                 "session_id": session.session_id,
#                 "total_results_served": session.last_returned_offset,
#                 "last_accessed": session.last_accessed,
#                 "is_exhausted": session.is_exhausted
#             },
#             "query_info": {
#                 "original_prompt": session.original_prompt,
#                 "generated_queries": session.queries,
#                 "query_positions": session.query_positions
#             }
#         }
