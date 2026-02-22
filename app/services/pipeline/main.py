from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

from .config import POCSettings, load_settings
from .models import LeadCriteria
from .credential_pools import GoogleCustomSearchCredentialPool
from .pipeline import LeadGenerationPipelinePOC


def build_basic_criteria_from_prompt(user_prompt: str, target_count: int) -> LeadCriteria:
    lower = user_prompt.lower()
    industry = None
    location = None

    if "food" in lower:
        industry = "food"
    if "gurugram" in lower or "gurgaon" in lower:
        location = "Gurugram, India"

    role_keywords = ["sales"]

    return LeadCriteria(
        industry=industry,
        location=location,
        role_keywords=role_keywords,
        target_count=target_count
    )


async def execute_pipeline(prompt: str, target: int):
    settings, google_custom_search_pairs= load_settings()

    if not google_custom_search_pairs:
        raise Exception("No Google CSE pairs found.")

    google_pool = GoogleCustomSearchCredentialPool(google_custom_search_pairs)

    criteria = build_basic_criteria_from_prompt(prompt, target)

    pipeline = LeadGenerationPipelinePOC(
        settings=settings,
        criteria=criteria,
        google_pool=google_pool
    )

    leads = await pipeline.run(
        output_json_path="leads.json",
        state_snapshot_path="run_state.json"
    )

    return leads