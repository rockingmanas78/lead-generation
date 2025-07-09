import logging
import asyncio
import httpx
from typing import List, Dict, Optional
from app.config import USER_AGENT

class HTMLFetcher:
    async def fetch(self, urls: List[str]) -> Dict[str, Optional[str]]:
        async with httpx.AsyncClient(
                headers={"User-Agent": USER_AGENT},
                timeout=30.0,
                follow_redirects=True
        ) as client:
            async def fetch_single(url: str) -> tuple[str, Optional[str]]:
                print(f"Requesting URL: {url}")
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    return url, response.text
                except Exception as e:
                    print(f"Failed to fetch {url}: {e}")
                    return url, None

            tasks = [fetch_single(url) for url in urls]
            results = await asyncio.gather(*tasks)

            return {url: content for url, content in results}
