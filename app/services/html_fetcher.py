import logging
import asyncio
import httpx
from typing import List, Dict, Optional
from app.config import USER_AGENT

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
REQUEST_TIMEOUT_SECONDS = 30.0
RETRY_STATUS_CODES = {403, 408, 429, 500, 502, 503, 504}


class HTMLFetcher:
    async def fetch(self, urls: List[str]) -> Dict[str, Optional[str]]:
        """
        Fetch a list of URLs concurrently with retries and JSON logs.
        """
        headers = {"User-Agent": USER_AGENT}
        async with httpx.AsyncClient(headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True) as client:

            async def fetch_single(url: str) -> tuple[str, Optional[str]]:
                for attempt_number in range(1, MAX_RETRIES + 1):
                    try:
                        response = await client.get(url)
                        if response.status_code in RETRY_STATUS_CODES and attempt_number < MAX_RETRIES:
                            logger.warning("fetch_retry", extra={
                                "url": url, "attempt": attempt_number, "error": f"HTTP {response.status_code}"
                            })
                            await asyncio.sleep(0.4 * attempt_number)
                            continue

                        response.raise_for_status()
                        logger.info("fetch_ok", extra={"url": url, "status": response.status_code})
                        return url, response.text

                    except httpx.HTTPStatusError as status_error:
                        if status_error.response is not None and status_error.response.status_code in RETRY_STATUS_CODES and attempt_number < MAX_RETRIES:
                            logger.warning("fetch_retry", extra={
                                "url": url, "attempt": attempt_number, "error": str(status_error)
                            })
                            await asyncio.sleep(0.4 * attempt_number)
                            continue
                        logger.error("fetch_failed", extra={"url": url, "error": str(status_error)})
                        return url, None
                    except Exception as unexpected_error:
                        if attempt_number < MAX_RETRIES:
                            logger.warning("fetch_retry", extra={
                                "url": url, "attempt": attempt_number, "error": str(unexpected_error)
                            })
                            await asyncio.sleep(0.4 * attempt_number)
                            continue
                        logger.error("fetch_failed", extra={"url": url, "error": str(unexpected_error)})
                        return url, None

                logger.error("fetch_failed", extra={"url": url})
                return url, None

            tasks = [fetch_single(single_url) for single_url in urls]
            results = await asyncio.gather(*tasks)
            return {url: content for url, content in results}



# import logging
# import asyncio
# import httpx
# from typing import List, Dict, Optional
# from app.config import USER_AGENT

# class HTMLFetcher:
#     async def fetch(self, urls: List[str]) -> Dict[str, Optional[str]]:
#         async with httpx.AsyncClient(
#                 headers={"User-Agent": USER_AGENT},
#                 timeout=30.0,
#                 follow_redirects=True
#         ) as client:
#             async def fetch_single(url: str) -> tuple[str, Optional[str]]:
#                 print(f"Requesting URL: {url}")
#                 try:
#                     response = await client.get(url)
#                     response.raise_for_status()
#                     return url, response.text
#                 except Exception as e:
#                     print(f"Failed to fetch {url}: {e}")
#                     return url, None

#             tasks = [fetch_single(url) for url in urls]
#             results = await asyncio.gather(*tasks)

#             return {url: content for url, content in results}
