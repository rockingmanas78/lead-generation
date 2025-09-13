import json
from typing import Dict, List
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin, urlparse

SOCIAL_HOSTS = {
    "twitter.com", "x.com", "facebook.com", "m.facebook.com", "instagram.com",
    "www.instagram.com", "pinterest.com", "www.pinterest.com", "linkedin.com"
}
DISALLOWED_PATH_FRAGMENTS = {"share", "sharer", "intent", "pin/create", "send"}

def is_same_registrable_domain(src: str, dst: str) -> bool:
    # simple heuristic without publicsuffix2: compare last two labels
    s = urlparse(src).netloc.split("."); d = urlparse(dst).netloc.split(".")
    return len(s) >= 2 and len(d) >= 2 and s[-2:] == d[-2:]

class FooterParser:
    FOOTER_SELECTORS = [
        "footer", ".footer", "#footer", "[role='contentinfo']",
        ".site-footer", ".page-footer", ".block--footer",
        "[class*='footer']", "section[class*='footer']"
    ]

    def extract_footer(self, html_text: str) -> str:
        soup = BeautifulSoup(html_text, "html.parser")
        for selector in self.FOOTER_SELECTORS:
            footer = soup.select_one(selector)
            if footer:
                return footer.get_text(separator=' ', strip=True)
        return ""

    # def find_contact_links(self, html_text: str, base_url: str) -> List[str]:
    #     from urllib.parse import urljoin
    #     import re
    #     soup = BeautifulSoup(html_text, 'html.parser')
    #     patterns = [r'contact', r'contact[_-]us', r'get[_-]in[_-]touch', r'reach[_-]us', r'support', r'help']
    #     contact_links: List[str] = []

    #     for link in soup.find_all('a', href=True):
    #         href_lower = link['href'].lower()
    #         text_lower = link.get_text(strip=True).lower()
    #         if any(re.search(pattern, href_lower) or re.search(pattern, text_lower) for pattern in patterns):
    #             full_url = urljoin(base_url, link['href'])
    #             if full_url not in contact_links:
    #                 contact_links.append(full_url)
    #     return contact_links
    def find_contact_links(self, html_text: str, base_url: str) -> List[str]:
        soup = BeautifulSoup(html_text, 'html.parser')
        patterns = [r'contact', r'contact[_-]us', r'get[_-]in[_-]touch', r'reach[_-]us', r'support', r'help']
        out = []
        for a in soup.find_all('a', href=True):
            href = urljoin(base_url, a['href'])
            host = urlparse(href).netloc.lower()
            path = urlparse(href).path.lower()
            text = a.get_text(strip=True).lower()

            if host in SOCIAL_HOSTS:         # skip social/share
                continue
            if any(frag in path for frag in DISALLOWED_PATH_FRAGMENTS):
                continue
            if not is_same_registrable_domain(base_url, href):  # keep it on-site
                continue
            if any(re.search(p, a['href'].lower()) or re.search(p, text) for p in patterns):
                if href not in out:
                    out.append(href)
        return out

    def extract_from_json_ld(self, html_text: str) -> Dict:
        """
        Best-effort extraction from JSON-LD blocks (ContactPage/Organization/ContactPoint).
        Returns a dict aligned with our ContactInfo fields when possible.
        """
        soup = BeautifulSoup(html_text, "html.parser")
        emails: List[str] = []
        phones: List[str] = []
        addresses: List[str] = []
        company_name: str = ""
        description: str = ""

        for script_tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script_tag.string or "{}")
            except Exception:
                continue

            data_objects = data if isinstance(data, list) else [data]
            for obj in data_objects:
                if not isinstance(obj, dict):
                    continue

                # Organization name / description
                if not company_name and isinstance(obj.get("name"), str):
                    company_name = obj["name"]
                if not description and isinstance(obj.get("description"), str):
                    description = obj["description"]

                # ContactPoint / ContactPage
                possible_points = []
                if "contactPoint" in obj:
                    if isinstance(obj["contactPoint"], list):
                        possible_points.extend(obj["contactPoint"])
                    else:
                        possible_points.append(obj["contactPoint"])

                for cp in possible_points:
                    if not isinstance(cp, dict):
                        continue
                    email_value = cp.get("email")
                    telephone_value = cp.get("telephone")
                    if isinstance(email_value, str):
                        emails.append(email_value)
                    if isinstance(telephone_value, str):
                        phones.append(telephone_value)

                # Postal address
                address_obj = obj.get("address")
                if isinstance(address_obj, dict):
                    parts: List[str] = []
                    for key in ["streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry"]:
                        value = address_obj.get(key)
                        if isinstance(value, str) and value.strip():
                            parts.append(value.strip())
                    if parts:
                        addresses.append(", ".join(parts))

        return {
            "emails": emails,
            "phones": phones,
            "addresses": addresses,
            "company_name": company_name,
            "description": description,
        }


# from bs4 import BeautifulSoup

# class FooterParser:
#     FOOTER_SELECTORS = [
#         "footer", ".footer", "#footer", "[role='contentinfo']",
#         ".site-footer", ".page-footer", ".block--footer",
#         "[class*='footer']", "section[class*='footer']"
#     ]

#     def extract_footer(self, html: str) -> str:
#         soup = BeautifulSoup(html, "html.parser")
#         for selector in self.FOOTER_SELECTORS:
#             footer = soup.select_one(selector)
#             if footer:
#                 return footer.get_text(separator=' ', strip=True)
#         return ""

#     def find_contact_links(self, html: str, base_url: str) -> list[str]:
#         from urllib.parse import urljoin
#         import re
#         soup = BeautifulSoup(html, 'html.parser')
#         patterns = [r'contact', r'contact[_-]us', r'get[_-]in[_-]touch', r'reach[_-]us', r'support', r'help']
#         contact_links = []

#         for link in soup.find_all('a', href=True):
#             href = link['href'].lower()
#             text = link.get_text(strip=True).lower()
#             if any(re.search(p, href) or re.search(p, text) for p in patterns):
#                 full_url = urljoin(base_url, href)
#                 if full_url not in contact_links:
#                     contact_links.append(full_url)
#         return contact_links
