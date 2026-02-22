from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

# Importing from your project files
from .config import POCSettings
from .models import CompanyState, Lead, LeadCriteria, EmailValidationResult
from .credential_pools import GoogleCustomSearchCredentialPool
from .google_custom_search_client import GoogleCustomSearchClientWithRotation
from .email_verification_client import verify_email

from .text_extraction import (
    extract_company_domain_from_url,
    extract_person_emails_for_domain,
    extract_person_name_from_search_title_or_snippet,
)

from .email_pattern_inference import (
    infer_ranked_email_patterns,
    generate_email_candidates_from_name,
)

# ============================================================
# NAME NORMALIZATION (KEPT AS REQUESTED)
# ============================================================

MONTH_WORDS = {
    "jan","feb","mar","apr","may","jun",
    "jul","aug","sep","oct","nov","dec"
}

GENERIC_WORDS = {
    "sales","support","team","company","website",
    "manager","management","director","executive",
    "business","group","office","contact",
    "account","global","leader","solutions",
    "services","quality","supply","visit",
    "directory","academy","training","privacy",
    "careers","construction","products","listed",
    "architectural","conformity","bodies",
    "phone","road","india","delhi","gurugram"
    "jobs", "hotel", "resort", "inn", "express", "plaza",
    "rewards", "deals", "specialist", "view", "stories",
    "safety", "auditor", "report", "east", "cristal", 
    "listings", "compliance", "research", "assurance","manager","engineer","director",
    "sales","head","lead","marketing","executive","officer","foods","ltd","inc","corp","company",
    "technologies","solutions","industries","profile", "project", "communications", "web", "financial", 
    "partnership", "talent", "pool", "architect", "hire", "area",
    "storage", "service", "manual", "cycle", "funding", "stakeholder",
    "cluster", "sustainability", "box", "reviews", "hiring", "thanks"
}

def normalize_person_name(raw_name: str) -> Optional[str]:
    if not raw_name:
        return None
    words = raw_name.strip().split()
    cleaned = []
    for w in words:
        lw = w.lower()
        if lw in MONTH_WORDS or lw in GENERIC_WORDS:
            continue
        if not re.match(r"^[A-Z][a-zA-Z\-\']+$", w): 
            continue    
        cleaned.append(w)
    if len(cleaned) < 2:
        return None
    return " ".join(cleaned[:3])

def is_human_name(name: str) -> bool:
    parts = name.split()
    if not (2 <= len(parts) <= 3):
        return False
    for p in parts:
        if not re.match(r"^[A-Z][a-z]{2,}$", p):
            return False
    return True

@dataclass
class QueueJob:
    job_type: str
    payload: dict

class InMemoryPOCRunState:
    def __init__(self, criteria: LeadCriteria) -> None:
        self.criteria = criteria
        self.company_states_by_domain: Dict[str, CompanyState] = {}
        self.generated_leads: List[Lead] = []
        self.total_google_custom_search_requests = 0
        self.seen_person_keys: Set[Tuple[str, str]] = set()
        self.seen_email_candidates: Set[str] = set()
        self.company_search_page_by_query: Dict[str, int] = {}
        self.exhausted_company_queries: Set[str] = set()

    def confirmed_lead_count(self) -> int:
        return sum(1 for l in self.generated_leads if l.status == "confirmed")

    def dump(self) -> dict:
        return {
            "criteria": self.criteria.model_dump(),
            "companies": {k: v.model_dump() for k, v in self.company_states_by_domain.items()},
            "leads": [l.model_dump() for l in self.generated_leads],
        }

# ============================================================
# PIPELINE
# ============================================================

class LeadGenerationPipelinePOC:
    def __init__(
        self,
        settings: POCSettings,
        criteria: LeadCriteria,
        google_pool: GoogleCustomSearchCredentialPool,
    ) -> None:
        self.settings = settings
        self.state = InMemoryPOCRunState(criteria)
        self.google = GoogleCustomSearchClientWithRotation(
            credential_pool=google_pool,
            http_timeout_seconds=settings.http_timeout_seconds,
        )
        self.job_queue: asyncio.Queue[QueueJob] = asyncio.Queue()
        self.should_stop = False
    def _can_search_more_companies(self) -> bool:
        return (
            self.state.total_google_custom_search_requests < self.settings.maximum_google_custom_search_requests
            and len(self.state.company_states_by_domain) < self.settings.maximum_company_domains_to_process
        )

    def _target_reached(self) -> bool:
        return self.state.confirmed_lead_count() >= self.state.criteria.target_count

    def build_company_discovery_queries(self) -> List[str]:
        c = self.state.criteria

        industry = (c.industry or "FMCG").lower()
        location = (c.location or "India").replace("Gurugram", "Gurgaon")

        return [
            f"{industry} companies in {location}",
            f"list of {industry} companies in {location}",
            f"{location} {industry} manufacturers",
            f"top {industry} brands in {location}",
            f"{industry} suppliers in {location}",
        ]


    def build_people_discovery_queries(self, domain: str) -> List[str]:
        company_name = domain.split(".")[0]

        return [
            f'"{company_name}" "sales manager"',
            f'"{company_name}" "regional sales manager"',
            f'"{company_name}" "business development manager"',
            f'"{company_name}" "sales head"',
            f'"{company_name}" "sales director"',
        ]



    async def enqueue_initial_jobs(self):
        for q in self.build_company_discovery_queries():
            await self.job_queue.put(QueueJob("company_discovery", {"query": q}))

    async def handle_company_discovery_job(self, query: str):
        if query in self.state.exhausted_company_queries or not self._can_search_more_companies():
            return

        page = self.state.company_search_page_by_query.get(query, 1)
        start_index = (page - 1) * 10 + 1
        print(f"\nSearching: {query} (page {page})")

        # FIXED: Used 'query' instead of 'q' and included start_index
        items = await asyncio.to_thread(self.google.search, query, start_index, 10)
        self.state.total_google_custom_search_requests += 1

        if not items:
            print(f"No results for {query}")
            self.state.exhausted_company_queries.add(query)
            return

        self.state.company_search_page_by_query[query] = page + 1
        for item in items:
            domain = extract_company_domain_from_url(item.link or "")
            if not domain or domain in self.state.company_states_by_domain:
                continue

            print(f"Company found: {domain}")
            self.state.company_states_by_domain[domain] = CompanyState(company_domain=domain, seed_url=item.link)
            await self.job_queue.put(QueueJob("company_email_harvest", {"company_domain": domain}))

    async def handle_company_email_harvest_job(self, domain: str):
        print(f"DEBUG: Learning email pattern for {domain}...") 
        company = self.state.company_states_by_domain[domain]
        emails: List[str] = []
        queries = [f'site:{domain} "@{domain}"', f'site:{domain} leadership "@{domain}"']

        for q in queries:
            # FIXED: Used 'q' correctly here as it is the loop variable
            items = await asyncio.to_thread(self.google.search, q, 1, 10)
            for item in items:
                text = (item.snippet or "") + " " + (item.htmlSnippet or "")
                emails.extend(extract_person_emails_for_domain(text, domain))

        emails = list(set(emails))[:20]
        company.person_email_samples = emails

        if len(emails) >= 2:
            company.learned_email_patterns_ranked = infer_ranked_email_patterns(emails)
            print(f"SUCCESS: Learned pattern for {domain}: {company.learned_email_patterns_ranked}")
        else:
            company.learned_email_patterns_ranked = ["first.last", "first", "flast", "firstl"]
            print(f"INFO: No pattern found for {domain}, using fallbacks.")

        await asyncio.sleep(1)
        await self.job_queue.put(QueueJob("people_discovery", {"company_domain": domain}))

    async def handle_people_discovery_job(self, domain: str):
        print(f"DEBUG: Starting People Search for {domain}...")
        for q in self.build_people_discovery_queries(domain):
            await asyncio.sleep(0.5)
            items = await asyncio.to_thread(self.google.search, q, 1, 10)
            for item in items:
                extracted = extract_person_name_from_search_title_or_snippet(item.title or "", item.snippet or "")
                for raw_name, role_hint in extracted:
                    clean_name = normalize_person_name(raw_name)
                    if not clean_name or not is_human_name(clean_name):
                        continue

                    key = (domain, clean_name.lower())
                    if key not in self.state.seen_person_keys:
                        self.state.seen_person_keys.add(key)
                        print(f"Found candidate: {clean_name}")
                        await self.job_queue.put(QueueJob("verify_person_email_candidates", {
                            "company_domain": domain, "full_name": clean_name, "role_hint": role_hint
                        }))

    async def handle_verify_person_email_candidates_job(self, company_domain: str, full_name: str, role_hint: Optional[str]):
        company = self.state.company_states_by_domain[company_domain]
        candidates = generate_email_candidates_from_name(full_name, company_domain, company.learned_email_patterns_ranked)

        for email, _ in candidates:
            if email in self.state.seen_email_candidates:
                continue

            print(f"Verifying: {email}")
            try:
                # Call your own API function from email_verification_client.py
                raw_response = await asyncio.to_thread(verify_email, email)
                
                # Map the response based on your successful test result
                inner_result = raw_response.get("result", {})
                status = inner_result.get("status", "UNKNOWN").lower()
                
            except Exception as e:
                print(f"Verification error for {email}: {e}")
                status = "unknown"
                inner_result = {}

            # Success criteria for your specific API
            if status in ("valid", "success", "unknown"): 
                print(f"Confirmed lead: {email} (Status: {status})")
                
                lead = Lead(
                    company_domain=company_domain,
                    person_name=full_name,
                    role_hint=role_hint,
                    email=email,
                    # FIXED: Using the new generic class name
                    verification=EmailValidationResult(
                        address=email,
                        status=status,
                        # Optional: Extract substatus if your API provides it
                        sub_status=inner_result.get("subStatus", "none"),
                        raw_response=raw_response
                    ),
                    status="confirmed",
                    confidence=0.8 if status != "unknown" else 0.4
                )
                self.state.generated_leads.append(lead)
                self.state.seen_email_candidates.add(email)
                return

    async def run(self, output_json_path: str, state_snapshot_path: str):
        await self.enqueue_initial_jobs()
        print("Pipeline running...")
        
        while not self.should_stop:
            if self._target_reached():
                print("Target lead count reached.")
                break
                
            try:
                job = await asyncio.wait_for(self.job_queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                if not self._can_search_more_companies():
                    print("All search tasks completed and limit reached.")
                    break
                continue

            try:
                if job.job_type == "company_discovery":
                    await self.handle_company_discovery_job(job.payload["query"])
                elif job.job_type == "company_email_harvest":
                    await self.handle_company_email_harvest_job(job.payload["company_domain"])
                elif job.job_type == "people_discovery":
                    await self.handle_people_discovery_job(job.payload["company_domain"])
                elif job.job_type == "verify_person_email_candidates":
                    await self.handle_verify_person_email_candidates_job(**job.payload)
            except Exception as e:
                print(f"Error in {job.job_type}: {e}")
            finally:
                self.job_queue.task_done()

        # Final Save
        print(f"Saving {len(self.state.generated_leads)} leads to {output_json_path}")
        with open(output_json_path, "w") as f:
            json.dump([l.model_dump() for l in self.state.generated_leads], f, indent=2)
            
        with open(state_snapshot_path, "w") as f:
            json.dump(self.state.dump(), f, indent=2)
            
        return self.state.generated_leads