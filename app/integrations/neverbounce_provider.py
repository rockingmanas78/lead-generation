import os, aiohttp, asyncio
from typing import List, Dict
from .email_verifier import EmailVerifier, Verification

BASE = "https://api.neverbounce.com/v4"

NB_MAP = {
    "valid": "valid",
    "invalid": "invalid",
    "disposable": "disposable",
    "catchall": "catchall",
    "unknown": "unknown"
}

class NeverBounceProvider(EmailVerifier):
    def __init__(self, api_key: str | None = None, timeout: int = 25):
        self.key = api_key or os.getenv("NEVERBOUNCE_API_KEY")
        self.timeout = timeout
        if not self.key:
            raise RuntimeError("NEVERBOUNCE_API_KEY missing")

    async def check_single(self, email: str) -> Verification:
        url = f"{BASE}/single/check"
        params = {"key": self.key, "email": email, "timeout": 5}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as s:
            async with s.get(url, params=params) as r:
                data = await r.json()
                return NB_MAP.get(data.get("result","unknown"), "unknown")

    async def bulk_verify(self, emails: List[str]) -> Dict[str, Verification]:
        """
        Create job with inline supplied_input (no CSV hosting), auto_start, poll until done,
        then fetch paginated results. For large lists, split upstream into chunks (e.g., 5k).
        """
        create_url = f"{BASE}/jobs/create"
        payload = {
            "key": self.key,
            "supplied_input": [{"email": e} for e in emails],
            "auto_start": True
        }
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as s:
            async with s.post(create_url, data=payload) as r:
                job = await r.json()
                job_id = job.get("job", {}).get("id") or job.get("id")
                if not job_id:
                    return {e: "unknown" for e in emails}

            # poll status
            status_url = f"{BASE}/jobs/status"
            while True:
                await asyncio.sleep(2.5)
                async with s.get(status_url, params={"key": self.key, "job_id": job_id}) as r2:
                    st = await r2.json()
                    if st.get("job", {}).get("status") in ("completed","failed"):
                        break

            # fetch results (paginated)
            results: Dict[str, Verification] = {}
            page = 1
            while True:
                async with s.get(f"{BASE}/jobs/results", params={
                    "key": self.key, "job_id": job_id, "page": page, "per_page": 500
                }) as r3:
                    res = await r3.json()
                    items = (res.get("results") or {}).get("items", [])
                    for it in items:
                        email = it.get("email") or it.get("address")
                        results[email] = NB_MAP.get(it.get("result","unknown"), "unknown")
                    if not items or len(items) < 500:
                        break
                    page += 1

            return results
