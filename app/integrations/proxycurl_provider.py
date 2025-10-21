import os, aiohttp, asyncio
from typing import Optional, Dict
from .people_provider import PeopleProvider

PROXYCURL_HOST = "https://nubela.co/proxycurl"

class ProxycurlProvider(PeopleProvider):
    def __init__(self, api_key: Optional[str] = None, timeout: int = 20):
        self.api_key = api_key or os.getenv("PROXYCURL_API_KEY")
        self.timeout = timeout
        if not self.api_key:
            raise RuntimeError("PROXYCURL_API_KEY missing")

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    async def _get(self, path: str, params: Dict) -> Optional[Dict]:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as s:
            async with s.get(f"{PROXYCURL_HOST}{path}", headers=self._headers(), params=params) as r:
                if r.status == 200:
                    return await r.json()
                # Soft-fail on 404/204 etc.
                return None

    async def get_person_by_linkedin_url(self, url: str) -> Optional[Dict]:
        # Person Profile Endpoint (v2), request cache where possible
        # Docs and examples show /api/v2/linkedin with url=... and cache flags. 
        # Use conservative params to cut cost/latency.
        params = {
            "url": url,
            "use_cache": "if-present",
            "fallback_to_cache": "on-error",
            # optional: "personal_email":"include" (costlier), enable later if needed
        }
        return await self._get("/api/v2/linkedin", params)

    async def get_company_by_linkedin_url(self, url: str) -> Optional[Dict]:
        # Company Profile Endpoint
        params = {
            "url": url,
            "use_cache": "if-present",
            "fallback_to_cache": "on-error",
        }
        return await self._get("/api/linkedin/company", params)
