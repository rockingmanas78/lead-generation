import logging
import aiohttp
import asyncio
import random
from typing import Any
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from prisma import Prisma
from app.user_agents import USER_AGENTS
from app.services.database import db
from app.config import GOOGLE_API_KEY, GOOGLE_CSE_ID

logger = logging.getLogger(__name__)


class GoogleSearchError(Exception):
    pass


class LinkedInScrapingError(Exception):
    pass


class LinkedInScraper:
    def __init__(self):
        self.db: Prisma = db
        self.google_api_key: str | None = GOOGLE_API_KEY
        self.google_cse_id: str | None = GOOGLE_CSE_ID
        self.base_url: str = "https://www.googleapis.com/customsearch/v1"
        self.browser: Browser | None = None
        self.contexts: list[BrowserContext] = []
        self.max_concurrent_pages: int = 3
        self.request_delays: tuple[int, int] = (2, 8)

    async def __aenter__(self):
        await self._init_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._cleanup_browser()

    async def _init_browser(self):
        if self.browser:
            return

        playwright = await async_playwright().start()

        self.browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-extensions",
                "--disable-plugins",
                "--disable-images",
                "--disable-javascript",
                "--user-agent=" + random.choice(USER_AGENTS),
            ],
        )

        print("Browser initialized successfully")

    async def _cleanup_browser(self):
        for context in self.contexts:
            try:
                await context.close()
            except Exception as e:
                logger.warning(f"Error closing context: {e}")

        if self.browser:
            try:
                await self.browser.close()
                print("Browser closed successfully")
            except Exception as e:
                logger.warning(f"Error closing browser: {e}")

    async def _create_stealth_context(self) -> BrowserContext:
        user_agent = random.choice(USER_AGENTS)

        context = await self.browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            permissions=["geolocation"],
            geolocation={"latitude": 40.7128, "longitude": -74.0060},
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Cache-Control": "max-age=0",
            },
        )

        await context.add_init_script("""
            // Remove webdriver property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });

            // Mock chrome object
            window.chrome = {
                runtime: {},
            };

            // Mock permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
            );

            // Mock plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });

            // Mock languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en'],
            });
        """)

        self.contexts.append(context)
        return context

    async def get_company_linkedin_links(
        self, company_list: list[str]
    ) -> dict[str, str]:
        semaphore = asyncio.Semaphore(5)

        async def fetch(company_name: str) -> tuple[str, str]:
            async with semaphore:
                try:
                    link = await self._search_linkedin_link(company_name)
                    await asyncio.sleep(random.uniform(*self.request_delays))
                    return company_name, link
                except GoogleSearchError as e:
                    logger.warning(
                        f"Failed to retrieve LinkedIn link for '{company_name}': {e}"
                    )
                    return company_name, ""

        results = await asyncio.gather(*[fetch(name) for name in company_list])
        result_dict = {name: link for name, link in results if link}

        final_results: dict[str, str] = {}
        for name, url in result_dict.items():
            existing = await self.db.lead.find_unique(where={"linkedInUrl": url})
            if not existing:
                final_results[name] = url
            else:
                print(f"Skipping '{name}' - LinkedIn URL already exists in DB.")

        return final_results

    async def _search_linkedin_link(self, company_name: str) -> str:
        query = f"{company_name} site:linkedin.com/company"
        params = {
            "q": query,
            "key": self.google_api_key,
            "cx": self.google_cse_id,
            "start": 0,
            "num": 5,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.base_url, params=params, timeout=10
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "items" not in data:
                            print(f"No search results found for query: {query}")
                            raise GoogleSearchError("No search results found")

                        results = data.get("items", [])
                        for result in results:
                            link = result.get("link", "")
                            if "/company/" in link and not "/posts" in link:
                                return link

                        if results:
                            return results[0].get("link", "")

                        raise GoogleSearchError("No valid LinkedIn company page found")
                    else:
                        error_msg = f"Google API error: HTTP {response.status}"
                        if response.status == 429:
                            error_msg += " - Rate limit exceeded"
                        elif response.status == 403:
                            error_msg += " - API key invalid or quota exceeded"
                        logger.error(error_msg)
                        raise GoogleSearchError(error_msg)
        except asyncio.TimeoutError:
            logger.error(f"Google API request timed out for query: {query}")
            raise GoogleSearchError("Search request timed out")
        except aiohttp.ClientError as e:
            logger.error(f"Google API client error: {e}")
            raise GoogleSearchError(f"Search service unavailable: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in Google search: {e}")
            raise GoogleSearchError(f"Search service error: {e}")

    async def scrape_linkedin_about_sections(
        self, linkedin_urls: dict[str, str]
    ) -> dict[str, dict[str, int]]:
        if not self.browser:
            await self._init_browser()

        semaphore = asyncio.Semaphore(self.max_concurrent_pages)
        results = {}

        async def scrape_single_company(company_name: str, url: str) -> tuple[str, int]:
            async with semaphore:
                try:
                    data = await self._scrape_linkedin_about(url)
                    await asyncio.sleep(random.uniform(*self.request_delays))
                    return company_name, data
                except LinkedInScrapingError as e:
                    logger.warning(f"Failed to scrape '{company_name}': {e}")
                    return company_name, -1

        batch_size = 5
        url_items = list(linkedin_urls.items())

        for i in range(0, len(url_items), batch_size):
            batch = url_items[i : i + batch_size]
            print(f"Processing batch {i // batch_size + 1}: {len(batch)} companies")

            batch_results = await asyncio.gather(
                *[scrape_single_company(name, url) for name, url in batch]
            )

            for company_name, data in batch_results:
                if data:
                    results[company_name] = data

            if i + batch_size < len(url_items):
                await asyncio.sleep(random.uniform(10, 20))

        return results

    async def _scrape_linkedin_about(self, linkedin_url: str) -> int:
        context = await self._create_stealth_context()

        try:
            page = await context.new_page()

            await page.set_extra_http_headers(
                {
                    "Referer": "https://www.google.com/",
                    "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                }
            )

            response = await page.goto(
                linkedin_url, wait_until="domcontentloaded", timeout=30000
            )

            if not response or response.status >= 400:
                raise LinkedInScrapingError(
                    f"Failed to load page: HTTP {response.status if response else 'No response'}"
                )

            await page.wait_for_timeout(random.randint(2000, 4000))

            if await page.locator('input[name="session_key"]').count() > 0:
                logger.warning("Hit LinkedIn login wall")
                response = await page.goto(
                    linkedin_url, wait_until="domcontentloaded", timeout=30000
                )
                await page.wait_for_timeout(random.randint(2000, 4000))

            company_size = await self._extract_company_data(page)

            try:
                company_size = company_size.rstrip(" employees")
                if company_size.endswith("+"):
                    company_size = company_size.rstrip("+")
                    company_size = company_size.replace(",", "")
                else:
                    company_size = company_size.split("-")[1]
                    company_size = company_size.replace(",", "")
            except Exception:
                logger.error("Could not parse the company_size string")

            print(
                f"Successfully scraped data for: {linkedin_url}, company_size={company_size}"
            )

            try:
                return int(company_size)
            except Exception:
                logger.error("Could not convert the string to int")
                return -1

        except Exception as e:
            logger.error(f"Error scraping {linkedin_url}: {e}")
            raise LinkedInScrapingError(f"Failed to scrape LinkedIn page: {e}")
        finally:
            await context.close()

    async def _extract_company_data(self, page: Page) -> str:
        company_size = ""

        try:
            size_element = await page.wait_for_selector(
                '[data-test-id="about-us__size"] dd', timeout=3000
            )
            if size_element:
                company_size = await size_element.inner_text()

            print(f"Extracted company_size {company_size}")
            return company_size.strip()

        except Exception as e:
            logger.error(f"Error extracting company data: {e}")
            return company_size

    async def scrape_and_store_companies(
        self, company_list: list[str], user_id: str
    ) -> dict[str, Any]:
        results = {
            "searched": len(company_list),
            "linkedin_urls_found": 0,
            "successfully_scraped": 0,
            "failed_scrapes": 0,
            "companies_data": {},
        }

        try:
            print(f"Searching LinkedIn URLs for {len(company_list)} companies")
            linkedin_urls = await self.get_company_linkedin_links(company_list)
            results["linkedin_urls_found"] = len(linkedin_urls)

            if not linkedin_urls:
                logger.warning("No LinkedIn URLs found")
                return results

            print(f"Scraping data for {len(linkedin_urls)} companies")
            scraped_data = await self.scrape_linkedin_about_sections(linkedin_urls)

            for company_name, data in scraped_data.items():
                if data:
                    results["successfully_scraped"] += 1
                    results["companies_data"][company_name] = data

                    try:
                        await self._store_company_data(
                            company_name, linkedin_urls[company_name], data
                        )
                    except Exception as e:
                        logger.error(f"Failed to store data for {company_name}: {e}")
                else:
                    results["failed_scrapes"] += 1

            print(
                f"Pipeline completed. Successfully scraped: {results['successfully_scraped']}, Failed: {results['failed_scrapes']}"
            )
            return results

        except Exception as e:
            logger.error(f"Error in scrape_and_store_companies: {e}")
            raise

    async def _store_company_data(self, company_name: str, url: str, data: int):
        try:
            await self.db.lead.update(
                where={"linkedInUrl": url}, data={"companySize": data}
            )
            print(f"Updated data for {company_name} in database")
        except Exception as e:
            logger.error(f"Database error for {company_name}: {e}")
            raise
