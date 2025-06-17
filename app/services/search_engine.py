import os
import hashlib
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import List, Dict, Any
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain_core.output_parsers.string import StrOutputParser
from app.schemas import SearchResult
from app.config import OPENAI_API_KEY, OPENAI_MODEL

class SearchSession:
    def __init__(self, session_id: str, original_prompt: str, queries: List[str]):
        self.session_id = session_id
        self.original_prompt = original_prompt
        self.queries = queries
        self.results: List[Dict] = []
        self.query_positions = {query: 0 for query in queries}
        self.created_at = datetime.now()
        self.last_accessed = datetime.now()
        self.total_api_calls = 0
        self.is_exhausted = False
        self.last_returned_offset = 0

    def add_results(self, new_results: List[Dict], query: str, fetched_count: int):
        self.results.extend(new_results)
        self.query_positions[query] += fetched_count
        self.last_accessed = datetime.now()
        self.total_api_calls += 1

    def get_results(self, offset: int, limit: int) -> List[Dict]:
        self.last_accessed = datetime.now()
        return self.results[offset:offset + limit]

    def needs_more_results(self, required_count: int) -> bool:
        return len(self.results) < required_count and not self.is_exhausted

class SearchEngine:
    def __init__(self):
        self.serp_api_key = os.getenv("SERPAPI_KEY")
        self.sessions: Dict[str, SearchSession] = {}
        self.base_url = "https://serpapi.com/search.json"
        self.llm = ChatOpenAI(api_key=OPENAI_API_KEY, model=OPENAI_MODEL)

    async def prompt_to_queries(self, user_prompt: str) -> List[str]:
        prompt = ChatPromptTemplate.from_messages([
            ("system", """
            You are a lead generation specialist. Generate 4-5 high-recall search queries to find contact information for the user.

            Requirements:
            1. Create diverse queries using different keyword combinations
            2. Include location-specific terms
            3. Use industry-specific terminology
            4. Do not search for aggregator websites.
            5. Focus on findable contact information


            Format each query to be Google search-ready.

            Example patterns to follow:
            - Direct business type + location + contact
            - Industry associations + location
            - Business directories + specific terms
            - Professional networks + area
            - Service-specific searches

            Only generate the queries and nothing else. generate the queries separated by commas but do not write them in markdown, just give me plaintext
            """),
            ("human", "{prompt}")
        ])

        chain = prompt | self.llm | StrOutputParser()
        output = await chain.ainvoke({"prompt": user_prompt})
        return [q.strip() for q in output.split(",") if q.strip()]

    def generate_session_id(self, user_id: str, prompt: str) -> str:
        base = f"{user_id}_{prompt}_{datetime.now().date()}"
        return hashlib.md5(base.encode()).hexdigest()

    def build_query(self, query: str) -> str:
        AGGREGATOR_KEYWORDS = [
            "justdial.com", "sulekha.com", "indiamart.com", "yellowpages.in", "yelp.com",
            "tripadvisor.in", "zomato.com", "magicbricks.com", "99acres.com", "housing.com",
            "makemytrip.com", "goibibo.com", "trivago.in", "booking.com", "airbnb.com", "hotels.com",
            "trustpilot.com", "glassdoor.com", "g2.com", "clutch.co", "upcity.com", "designrush.com",
            "comparisun.com", "bestfirms.com", "businesslist.io", "goodfirms.co", "capterra.in",
            "topdevelopers.co", "serchen.com"
        ]

        EXCLUDE_KEYWORD = '"Top"'

        excluded_sites = " ".join([f"-site:{site}" for site in AGGREGATOR_KEYWORDS])

        return f"{query} {excluded_sites} -{EXCLUDE_KEYWORD}"

    async def call_serp_api(self, query: str, start: int = 0, num: int = 10) -> List[Dict]:
        modified_query = self.build_query(query)

        params = {
            "q": modified_query,
            "api_key": self.serp_api_key,
            "engine": "google",
            "start": start,
            "num": num,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.base_url, params=params, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        results = data.get("organic_results", [])
                        return [
                            {
                                "title": r.get("title", ""),
                                "link": r.get("link", ""),
                                "snippet": r.get("snippet", ""),
                                "source": r.get("displayed_link", ""),
                                "rank": start + i + 1
                            }
                            for i, r in enumerate(results)
                        ]
        except Exception as e:
            print(f"SERP API error: {e}")
        return []

    async def fetch_more_results(self, session: SearchSession, target_count: int):
        current_count = len(session.results)
        if current_count >= target_count or session.is_exhausted:
            return

        needed = target_count - current_count

        for query in session.queries:
            if needed <= 0:
                break

            current_position = session.query_positions[query]
            if current_position >= 100:
                continue

            batch_size = min(10, needed)
            new_results = await self.call_serp_api(query, current_position, batch_size)

            if not new_results:
                continue

            existing_links = {r["link"] for r in session.results}
            filtered = [r for r in new_results if r["link"] not in existing_links]

            session.add_results(filtered, query, len(new_results))
            needed -= len(filtered)

        if len(session.results) == current_count:
            session.is_exhausted = True

    async def search_with_offset(
        self, prompt: str, user_id: str, offset: int, num_results: int
    ) -> Dict[str, Any]:
        session_id = self.generate_session_id(user_id, prompt)

        if session_id not in self.sessions:
            queries = await self.prompt_to_queries(prompt)
            self.sessions[session_id] = SearchSession(session_id, prompt, queries)
            await self.fetch_more_results(self.sessions[session_id], offset + num_results + 10)

        session = self.sessions[session_id]

        required_total = offset + num_results
        if session.needs_more_results(required_total):
            await self.fetch_more_results(session, required_total + 10)

        results = session.get_results(offset, num_results)
        session.last_returned_offset = offset + len(results)

        has_more = (offset + len(results)) < len(session.results) or not session.is_exhausted

        return {
            "results": [SearchResult(**r) for r in results],
            "pagination": {
                "offset": offset,
                "results_returned": len(results),
                "total_results_available": len(session.results),
                "has_more": has_more,
                "next_offset": offset + len(results) if has_more else None
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

        results = session.get_results(current_offset, num_results)
        session.last_returned_offset = current_offset + len(results)

        has_more = session.last_returned_offset < len(session.results) or not session.is_exhausted

        return {
            "results": [SearchResult(**r) for r in results],
            "pagination": {
                "offset": current_offset,
                "results_returned": len(results),
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
