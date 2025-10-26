import json
from typing import Tuple, Dict
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers.string import StrOutputParser
from app.config import OPENAI_MODEL

# Keep emails concise and concrete (subjects < 45 chars; body ~120–180 words).
# NN/g + Mailchimp suggest brevity + clarity; first 25 characters matter a lot on mobile. :contentReference[oaicite:1]{index=1}
SUBJECT_MAX_CHARS = 45

def _safe_json_extract(raw: str) -> Dict:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("Model did not return JSON.")
    return json.loads(raw[start:end+1])

class ColdEmailTemplateGenerator:
    def __init__(self):
        # Temperature slightly creative but not fluffy
        self.llm = ChatOpenAI(model="gpt-4.1", temperature=0.7, max_tokens=1200)
        self.chain = self.llm | StrOutputParser()
        # Reviewer is stricter
        self.reviewer = ChatOpenAI(model=OPENAI_MODEL, temperature=0.2) | StrOutputParser()

    async def generate_subject_and_content(
        self,
        *,
        user_prompt: str,
        brand_colors: list[str],
        font_family: str | None,
        show_header: bool,
        show_footer: bool,
        preheader: str | None,
    ) -> Tuple[str, Dict]:
        """Return (subject, content_json_dict) after review pass."""

        primary = (brand_colors[0] if len(brand_colors) > 0 else "#111111")
        accent  = (brand_colors[1] if len(brand_colors) > 1 else primary)

        # ---------- DRAFT ----------
        draft_prompt = f"""
You are a B2B cold email copywriter. Output ONLY one JSON object (no prose).
Keys:
{{
  "subject": string,                      // <= {SUBJECT_MAX_CHARS} chars, clear & specific
  "greeting": string,                     // use {{contactName}} if naming
  "opener": string,                       // problem-solution hook tied to audience
  "value_props": [string, ...],           // 3–5 crisp, benefit-first bullets
  "body_paragraph": string|null,          // optional short para with concrete detail
  "cta_text": string|null,                // e.g., "Get 15-min walkthrough"
  "cta_url": string|null,                 // omit or null if "Reply" CTA
  "closing": string,                      // warm but professional
  "signature": string|null,               // e.g., "— Manas, Productimate AI"
  "contact_email": string|null,
  "contact_phone": string|null
}}

Rules:
- Total body length target: 120–180 words.
- Allowed merge vars ONLY: {{contactName}}, {{companyName}}, {{contactEmail}}, {{contactPhone}}, {{contactAddress}}.
- No generic fluff ("cutting-edge solutions", "synergy"), no spammy claims or hype.
- Subject must be descriptive and value-led (avoid vague clickbait).
- Preheader (if provided by server) should be supported by opener (don’t duplicate).

Context (for tailoring, not for styling):
- Business & audience: {user_prompt}
- Primary color (renderer): {primary}
- Accent color (renderer): {accent}
- Preferred font (renderer fallback if unsupported): {font_family or "system default"}
- Header: {show_header} | Footer: {show_footer} | Preheader: {preheader or "None"}
"""
        raw_draft = await self.chain.ainvoke(draft_prompt)
        draft = _safe_json_extract(raw_draft)

        # ---------- REVIEW & ENRICH ----------
        review_prompt = f"""
You are a senior copy editor optimizing a B2B cold email JSON.

Return ONLY a JSON object with the SAME KEYS you received.

Improve the draft by this rubric:
- CLARITY: replace vague claims with specific, verifiable benefits (numbers, time-savings, examples).
- RELEVANCE: tie opener/bullets to the audience stated below; reflect their likely pains.
- BREVITY: keep body ~120–180 words; trim redundant phrases.
- SUBJECT: <= {SUBJECT_MAX_CHARS} chars; put the strongest benefit or offer up front (first 25 chars matter on mobile).
- PREHEADER SUPPORT: ensure opener complements a preheader (if given) instead of repeating it.
- CTA: single, unmistakable action; prefer "Reply" or 1-click link; keep it above the fold.
- TONE: professional, confident, human; avoid buzzwords and caps.
- ACCESSIBILITY: keep sentences readable (grade ~6–9).

Audience context (do not add HTML or style):
{user_prompt}

Preheader (if any): {preheader or "None"}

Draft JSON to improve:
{json.dumps(draft, ensure_ascii=False)}
"""
        raw_final = await self.reviewer.ainvoke(review_prompt)
        final = _safe_json_extract(raw_final)

        # Trim subject just in case
        final["subject"] = (final.get("subject") or "Quick question")[:SUBJECT_MAX_CHARS].strip()
        return final["subject"], final

