import re
from typing import Dict, List
from bs4 import BeautifulSoup
from html import unescape
from typing import Optional
from app.schemas import EmailContent

IMAGE_OR_ASSET_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "css", "js", "json", "xml"}

def extract_clean_text(html_text: str) -> str:
    soup = BeautifulSoup(html_text, 'html.parser')
    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()
    return ' '.join(soup.stripped_strings)

def find_empty_fields(data: Dict, parent: str = '') -> List[str]:
    empty: List[str] = []
    for key, value in data.items():
        if not value:
            empty.append(f"{parent}.{key}" if parent else key)
    return empty

def merge_data(existing: Dict, new_data: Dict) -> Dict:
    for key in new_data:
        if not existing.get(key):
            existing[key] = new_data[key]
    return existing

def unique_preserve_order(items: List[str]) -> List[str]:
    seen: set[str] = set()
    output: List[str] = []
    for item in items:
        key = item.strip().lower()
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output

def clean_phone_numbers(phone_list: List[str]) -> List[str]:
    """
    Strict-ish cleaning:
    - Keep only digits and '+' sign.
    - Accept E.164-like if starts with '+' and length 8..15 digits after '+'
    - Accept national digits if length 10..15 (no '+')
    - Reject probable dates (e.g., 20250xxxxx), high-repetition, and obviously bogus constants.
    - Do NOT auto-prepend '+' for unknown country.
    """
    cleaned: List[str] = []
    known_bogus_values = {"31536000", "100000000"}  # seconds in a year, etc.

    for raw_value in phone_list:
        if not isinstance(raw_value, str):
            continue
        normalized = re.sub(r"[^\d+]", "", raw_value)

        # Basic shape checks
        if not normalized:
            continue

        has_plus = normalized.startswith("+")
        digits = re.sub(r"\D", "", normalized)

        # Reject known bogus constants
        if digits in known_bogus_values:
            continue

        # Reject date-like (e.g., 20240425...)
        if re.match(r"^(19|20)\d{6,}$", digits):
            continue

        # Reject high repetition (e.g., 0000000000)
        if digits and digits.count(max(set(digits), key=digits.count)) > int(0.7 * len(digits)):
            continue

        if has_plus:
            if 8 <= len(digits) <= 15:
                cleaned.append("+" + digits)
        else:
            # National without plus: require at least 10 digits for quality
            if 10 <= len(digits) <= 15:
                cleaned.append(digits)

    return unique_preserve_order(cleaned)

def clean_emails(email_list: List[str]) -> List[str]:
    """
    Validate and normalize emails:
    - Basic RFC-ish regex.
    - Lowercase the domain part.
    - Drop addresses whose top-level domain looks like an asset extension (png/jpg/etc.).
    """
    cleaned: List[str] = []
    email_regex = re.compile(
        r"(?i)^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,24}$"
    )

    for raw_value in email_list:
        if not isinstance(raw_value, str):
            continue
        candidate = raw_value.strip()
        if not candidate:
            continue
        if not email_regex.match(candidate):
            continue

        local_part, _, domain_part = candidate.rpartition("@")
        if not local_part or not domain_part:
            continue

        # Remove trailing dot if any
        domain_part = domain_part.rstrip(".")

        # Filter out asset-like "TLDs" (e.g., 2x.png)
        tld_match = re.search(r"\.([A-Za-z0-9]{2,24})$", domain_part)
        if not tld_match:
            continue
        tld = tld_match.group(1).lower()
        if tld in IMAGE_OR_ASSET_TLDS:
            continue

        normalized = f"{local_part}@{domain_part.lower()}"
        cleaned.append(normalized)

    return unique_preserve_order(cleaned)

def derive_palette(brand_colors: list[str]) -> dict:
    primary    = (brand_colors[0] if len(brand_colors) > 0 else "#111111")
    accent     = (brand_colors[1] if len(brand_colors) > 1 else primary)
    background = (brand_colors[2] if len(brand_colors) > 2 else "#FFFFFF")
    link       = accent
    button_bg  = primary
    button_txt = "#FFFFFF"
    text       = "#111111" if background.upper() == "#FFFFFF" else "#FFFFFF"
    mutetext   = "#666666" if text == "#111111" else "#CCCCCC"
    return {
        "primary": primary, "accent": accent, "background": background,
        "link": link, "button_bg": button_bg, "button_txt": button_txt,
        "text": text, "mutetext": mutetext
    }

def expand_font_stack(font_family: Optional[str]) -> str:
    if not font_family:
        return "Arial, Helvetica, sans-serif"
    lower = font_family.lower()
    if "serif" in lower:
        return f"{font_family}, Georgia, serif"
    if "mono" in lower or "code" in lower:
        return f"{font_family}, Menlo, monospace"
    # Many clients ignore web fonts (e.g., Outlook/Gmail), fallback is essential:
    return f"{font_family}, Arial, sans-serif"

def strip_html(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\\1>", "", html, flags=re.S)
    text = re.sub(r"<br\\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p\\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    return re.sub(r"[ \\t]+", " ", text).strip()

# ── Outlook-safe button (VML) ─────────────────────────────────────────────────
def _button_html(href: str, label: str, bg: str, color: str, font_stack: str):
    # Height ~44px tap-target
    return f"""
<!--[if mso]>
  <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" href="{href}" style="height:44px;v-text-anchor:middle;width:260px;" arcsize="12%" strokecolor="{bg}" fillcolor="{bg}">
    <w:anchorlock/>
    <center style="color:{color};font-family:{font_stack};font-size:16px;font-weight:600;">{label}</center>
  </v:roundrect>
<![endif]-->
<![if !mso]><!-->
  <a href="{href}" style="display:inline-block;padding:12px 22px;background:{bg};color:{color};text-decoration:none;border-radius:8px;font-family:{font_stack};font-size:16px;font-weight:600;">
    {label}
  </a>
<!--<![endif]-->
""".strip()

# ── Full HTML renderer ────────────────────────────────────────────────────────
def render_email_html(
    *,
    subject: str,
    content: EmailContent,
    logo_url: Optional[str],
    palette: dict,
    font_stack: str,
    show_header: bool,
    show_footer: bool,
    preheader: Optional[str],
    unsubscribe_url: Optional[str],
) -> str:

    base_td = f"font-family:{font_stack};color:{palette['text']};font-size:16px;line-height:1.6;"

    pre = (f'<div style="display:none;opacity:0;visibility:hidden;height:0;width:0;overflow:hidden;">{_esc(preheader)}</div>'
           if preheader else "")

    header = f"""
    <tr>
      <td style="{base_td};padding:0;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:100%;background:{palette['primary']};">
          <tr>
            <td style="padding:18px 24px;text-align:left;">
              {f'<img src="{logo_url}" alt="Logo" style="max-width:160px;height:auto;border:0;display:block;">' if logo_url else ''}
            </td>
          </tr>
        </table>
      </td>
    </tr>
    """ if show_header else ""

    # Body copy
    bullets = "".join([f"<li>{vp}</li>" for vp in (content.value_props or [])])
    bullet_block = f"<ul>{bullets}</ul>" if bullets else ""

    body_mid = f"<p>{content.body_paragraph}</p>" if content.body_paragraph else ""

    contact_line = ""
    if content.contact_email or content.contact_phone:
        pieces = []
        if content.contact_email:
            pieces.append(f'<a href="mailto:{content.contact_email}" style="color:{palette["link"]};text-decoration:underline;">{content.contact_email}</a>')
        if content.contact_phone:
            pieces.append(f'<a href="tel:{content.contact_phone}" style="color:{palette["link"]};text-decoration:underline;">{content.contact_phone}</a>')
        contact_line = f"<p>{' / '.join(pieces)}</p>"

    cta_block = ""
    if content.cta_text and content.cta_url:
        cta_block = f"""
        <p style="margin:20px 0 0 0;">
          {_button_html(content.cta_url, content.cta_text, palette['button_bg'], palette['button_txt'], font_stack)}
        </p>
        """
    elif content.cta_text and not content.cta_url:
        # Text-only CTA (e.g., "Reply to this email")
        cta_block = f"<p><strong>{content.cta_text}</strong></p>"

    main = f"""
      <tr>
        <td style="{base_td};padding:24px 24px;">
          <p>{content.greeting}</p>
          <p>{content.opener}</p>
          {bullet_block}
          {body_mid}
          {cta_block}
          {contact_line}
          <p style="margin-top:20px;">{content.closing}</p>
          {f'<p>{content.signature}</p>' if content.signature else ''}
        </td>
      </tr>
    """

    footer = f"""
    <tr>
      <td style="{base_td};font-size:12px;color:{palette['mutetext']};padding:16px 24px 32px;">
        {f'<a href="{unsubscribe_url}" style="color:{palette["mutetext"]};text-decoration:underline;">Unsubscribe</a>' if unsubscribe_url else ''}
      </td>
    </tr>
    """ if show_footer else ""

    return f"""<!doctype html>
<html>
  <head>
    <meta name="x-apple-disable-message-reformatting">
    <meta name="color-scheme" content="light dark">
    <meta name="supported-color-schemes" content="light dark">
    <title>{_esc(subject)}</title>
  </head>
  <body style="width:100%;margin:0;padding:0;background:{palette['background']};">
    {pre}
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:100%;table-layout:fixed;background:{palette['background']};">
      <tr><td align="center">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:640px;margin:0 auto;background:{palette['background']};">
          {header}
          {main}
          {footer}
        </table>
      </td></tr>
    </table>
  </body>
</html>"""

def _esc(s: Optional[str]) -> str:
    if not s:
        return ""
    return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")