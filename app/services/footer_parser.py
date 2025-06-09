from bs4 import BeautifulSoup

class FooterParser:
    FOOTER_SELECTORS = [
        "footer", ".footer", "#footer", "[role='contentinfo']",
        ".site-footer", ".page-footer", ".block--footer",
        "[class*='footer']", "section[class*='footer']"
    ]

    def extract_footer(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for selector in self.FOOTER_SELECTORS:
            footer = soup.select_one(selector)
            if footer:
                return footer.get_text(separator=' ', strip=True)
        return ""

    def find_contact_links(self, html: str, base_url: str) -> list[str]:
        from urllib.parse import urljoin
        import re
        soup = BeautifulSoup(html, 'html.parser')
        patterns = [r'contact', r'contact[_-]us', r'get[_-]in[_-]touch', r'reach[_-]us', r'support', r'help']
        contact_links = []

        for link in soup.find_all('a', href=True):
            href = link['href'].lower()
            text = link.get_text(strip=True).lower()
            if any(re.search(p, href) or re.search(p, text) for p in patterns):
                full_url = urljoin(base_url, href)
                if full_url not in contact_links:
                    contact_links.append(full_url)
        return contact_links
