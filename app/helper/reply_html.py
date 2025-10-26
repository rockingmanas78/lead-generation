import html, re
from typing import Optional

URL_RE = re.compile(r"(https?://[^\s<]+)", re.I)
MAIL_RE = re.compile(r"(?<!\S)([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})(?!\S)")

def escape(s: str) -> str:
    return html.escape(s, quote=True)

def autolink(s: str, link_color: str = "#0B69FF") -> str:
    s = URL_RE.sub(lambda m: f'<a href="{m.group(1)}" style="color:{link_color};text-decoration:underline;">{m.group(1)}</a>', s)
    s = MAIL_RE.sub(lambda m: f'<a href="mailto:{m.group(1)}" style="color:{link_color};text-decoration:underline;">{m.group(1)}</a>', s)
    return s

def text_to_html_reply(text: str, link_color: str = "#0B69FF", font_stack: str = "Arial, Helvetica, sans-serif") -> str:
    """
    Converts a plain reply into simple, safe HTML:
      - Escapes HTML
      - Converts bullet-y lines to <ul>
      - Paragraphizes on blank lines
      - Auto-links URLs & emails
    """
    text = text or ""
    esc = escape(text).strip()

    # bullets: lines starting with -, *, •
    lines = esc.splitlines()
    blocks, ul = [], []
    def flush_ul():
        nonlocal ul, blocks
        if ul:
            blocks.append("<ul>" + "".join(f"<li>{autolink(li.strip(), link_color)}</li>" for li in ul) + "</ul>")
            ul = []

    for ln in lines:
        if re.match(r"^\s*([-*•])\s+", ln):
            ul.append(re.sub(r"^\s*([-*•])\s+", "", ln))
        elif ln.strip() == "":
            flush_ul()
            blocks.append("")  # paragraph break
        else:
            flush_ul()
            blocks.append(f"<p>{autolink(ln.strip(), link_color)}</p>")

    flush_ul()
    # collapse multiple empty blocks → single break
    html_blocks = []
    prev_empty = False
    for b in blocks:
        is_empty = (b == "")
        if is_empty and prev_empty:
            continue
        prev_empty = is_empty
        if not is_empty:
            html_blocks.append(b)

    # simple container (no header/footer)
    return f"""<!doctype html>
<html>
  <head>
    <meta name="x-apple-disable-message-reformatting">
    <meta name="color-scheme" content="light dark">
    <meta name="supported-color-schemes" content="light dark">
    <title></title>
  </head>
  <body style="margin:0;padding:0;background:#FFFFFF;">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:100%;table-layout:fixed;background:#FFFFFF;">
      <tr><td align="center">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:640px;margin:0 auto;background:#FFFFFF;">
          <tr>
            <td style="font-family:{font_stack};color:#111111;font-size:16px;line-height:1.6;padding:16px 20px;">
              {''.join(html_blocks)}
            </td>
          </tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>"""
