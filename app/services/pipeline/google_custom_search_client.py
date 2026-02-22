from __future__ import annotations

import re
import requests
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .models import GoogleCustomSearchItem
from .credential_pools import GoogleCustomSearchCredentialPool

GOOGLE_CUSTOM_SEARCH_ENDPOINT_URL = "https://www.googleapis.com/customsearch/v1"


# ---------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------

@dataclass
class GoogleCustomSearchErrorClassification:
    is_permanent: bool
    should_cooldown: bool
    cooldown_seconds: float
    human_message: str


def _classify_google_custom_search_error(
    http_status_code: int,
    response_json: Optional[Dict[str, Any]],
) -> GoogleCustomSearchErrorClassification:
    """Safe classification for Google Custom Search errors."""

    if response_json is None:
        return GoogleCustomSearchErrorClassification(
            is_permanent=False,
            should_cooldown=True,
            cooldown_seconds=30.0,
            human_message=f"HTTP {http_status_code} (non-JSON error)",
        )

    error = response_json.get("error", {})
    message = error.get("message", "Unknown error")
    errors = error.get("errors") or []
    reason = errors[0].get("reason") if errors else None

    # Rate limit
    if http_status_code == 429:
        return GoogleCustomSearchErrorClassification(
            is_permanent=False,
            should_cooldown=True,
            cooldown_seconds=60.0,
            human_message=f"Rate limited: {message}",
        )

    # Quota / permission
    if http_status_code == 403:
        if reason in ("dailyLimitExceeded", "quotaExceeded"):
            return GoogleCustomSearchErrorClassification(
                is_permanent=False,
                should_cooldown=True,
                cooldown_seconds=6 * 60 * 60,
                human_message=f"Quota exceeded",
            )

        return GoogleCustomSearchErrorClassification(
            is_permanent=True,
            should_cooldown=False,
            cooldown_seconds=0.0,
            human_message=f"Forbidden: {message}",
        )

    # 🔑 400 = bad query → STOP, do not retry
    if http_status_code == 400:
        return GoogleCustomSearchErrorClassification(
            is_permanent=False,
            should_cooldown=False,
            cooldown_seconds=0.0,
            human_message=f"Bad query: {message}",
        )

    # Invalid key
    if http_status_code == 401:
        return GoogleCustomSearchErrorClassification(
            is_permanent=True,
            should_cooldown=False,
            cooldown_seconds=0.0,
            human_message=f"Unauthorized: {message}",
        )

    return GoogleCustomSearchErrorClassification(
        is_permanent=False,
        should_cooldown=True,
        cooldown_seconds=30.0,
        human_message=f"HTTP {http_status_code}: {message}",
    )


# ---------------------------------------------------------------------
# Google Custom Search client
# ---------------------------------------------------------------------

class GoogleCustomSearchClientWithRotation:
    def __init__(
        self,
        credential_pool: GoogleCustomSearchCredentialPool,
        http_timeout_seconds: int,
    ) -> None:
        self.credential_pool = credential_pool
        self.http_timeout_seconds = http_timeout_seconds

    def _sanitize_query(self, query: str) -> str:
        """Google-safe query sanitizer."""
        query = query.strip()
        query = re.sub(r"[^\w\s\-\.]", " ", query)
        query = re.sub(r"\s+", " ", query)
        return query[:2048]

    def search(
        self,
        query: str,
        start_index: int,
        number_of_results: int,
    ) -> List[GoogleCustomSearchItem]:

        # Google limits
        number_of_results = max(1, min(10, number_of_results))
        start_index = max(1, start_index)

        if start_index + number_of_results - 1 > 100:
            return []

        query = self._sanitize_query(query)
        if not query:
            return []

        last_error: Optional[Exception] = None

        for _ in range(5):
            credential = self.credential_pool.acquire()
            if credential is None:
                return []  # no creds left → stop safely

            idx, api_key, cx = credential

            try:
                response = requests.get(
                    GOOGLE_CUSTOM_SEARCH_ENDPOINT_URL,
                    params={
                        "key": api_key,
                        "cx": cx,
                        "q": query,
                        "start": start_index,
                        "num": number_of_results,
                    },
                    timeout=self.http_timeout_seconds,
                )

                if response.status_code >= 400:
                    try:
                        response_json = response.json()
                    except Exception:
                        response_json = None

                    classification = _classify_google_custom_search_error(
                        response.status_code,
                        response_json,
                    )

                    if classification.is_permanent:
                        self.credential_pool.disable(idx, classification.human_message)
                    elif classification.should_cooldown:
                        self.credential_pool.cooldown(
                            idx,
                            classification.cooldown_seconds,
                            classification.human_message,
                        )

                    # ⛔ BAD QUERY → stop immediately
                    return []

                response_json = response.json()
                items = response_json.get("items") or []

                self.credential_pool.success(idx)

                if not items:
                    return []  # 🔥 CRITICAL: prevents infinite loop

                return [GoogleCustomSearchItem(**item) for item in items]

            except requests.RequestException as exc:
                self.credential_pool.cooldown(idx, 15.0, f"Network error: {exc}")
                last_error = exc

        return []
