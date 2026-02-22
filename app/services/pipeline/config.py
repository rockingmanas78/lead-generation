from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Tuple, Optional

@dataclass(frozen=True)
class POCSettings:
    # Budgets / limits (POC safety)
    maximum_google_custom_search_requests: int = 250
    maximum_company_domains_to_process: int = 20
    maximum_people_candidates_per_company_domain: int = 10

    maximum_zerobounce_validations: int = 400

    # HTTP
    http_timeout_seconds: int = 15
    http_user_agent: str = "LeadGenerationPOC/0.1"

    # Google CSE paging constraints
    google_custom_search_results_per_page: int = 10  # max 10 by API
    google_custom_search_maximum_start_index: int = 91  # last safe start for num=10 is 91 (91+10=101 -> guarded)

    # Retry/backoff
    transient_error_retry_attempts: int = 2
    transient_error_initial_backoff_seconds: float = 0.7

def _read_indexed_environment_variables(prefix: str) -> List[str]:
    values: List[str] = []
    index = 1
    while True:
        value = os.environ.get(f"{prefix}{index}")
        if value is None:
            break
        value = value.strip()
        if value:
            values.append(value)
        index += 1
    return values

def load_google_custom_search_credential_pairs() -> List[Tuple[str, str]]:
    """Reads GOOGLE_CUSTOM_SEARCH_API_KEY_i and GOOGLE_CUSTOM_SEARCH_ENGINE_ID_i pairs."""
    pairs: List[Tuple[str, str]] = []
    index = 1
    while True:
        api_key = os.environ.get(f"GOOGLE_CUSTOM_SEARCH_API_KEY_{index}")
        engine_id = os.environ.get(f"GOOGLE_CUSTOM_SEARCH_ENGINE_ID_{index}")
        if api_key is None and engine_id is None:
            break
        api_key = (api_key or "").strip()
        engine_id = (engine_id or "").strip()

        if api_key and engine_id:
            pairs.append((api_key, engine_id))
        index += 1

    return pairs


def load_settings() -> Tuple[POCSettings, List[Tuple[str, str]], List[str]]:
    settings = POCSettings()

    zerobounce_api_base_url = os.environ.get("ZEROBOUNCE_API_BASE_URL")
    if zerobounce_api_base_url and zerobounce_api_base_url.strip():
        settings = POCSettings(
            maximum_google_custom_search_requests=settings.maximum_google_custom_search_requests,
            maximum_company_domains_to_process=settings.maximum_company_domains_to_process,
            maximum_people_candidates_per_company_domain=settings.maximum_people_candidates_per_company_domain,
            maximum_zerobounce_validations=settings.maximum_zerobounce_validations,
            http_timeout_seconds=settings.http_timeout_seconds,
            http_user_agent=settings.http_user_agent,
            google_custom_search_results_per_page=settings.google_custom_search_results_per_page,
            google_custom_search_maximum_start_index=settings.google_custom_search_maximum_start_index,
            zerobounce_api_base_url=zerobounce_api_base_url.strip().rstrip("/"),
            zerobounce_point_of_entry_timeout_seconds=settings.zerobounce_point_of_entry_timeout_seconds,
            transient_error_retry_attempts=settings.transient_error_retry_attempts,
            transient_error_initial_backoff_seconds=settings.transient_error_initial_backoff_seconds,
        )

    google_pairs = load_google_custom_search_credential_pairs()

    return settings, google_pairs
