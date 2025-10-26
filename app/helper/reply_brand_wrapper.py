from typing import Optional
from .reply_html import escape

def _best_text(bg_hex: str) -> str:
    # tiny contrast helper; black on white default
    return "#111111" if bg_hex.upper() == "#FFFFFF" else "#FFFFFF"

def wrap_reply_body(inner_html: str, *, logo_url: Optional[str], font_stack: str, brand_colors: list[str], show_footer: bool) -> str:
    primary    = brand_colors[0] if brand_colors else "#111111"
    accent     = brand_colors[1] if len(brand_colors) > 1 else primary
    background = brand_colors[2] if len(brand_colors) > 2 else "#FFFFFF"
    text = _best_text(background)
    mutetext = "#666666" if text == "#111111" else "#CCCCCC"

    return f"""<!doctype html>
<html>
  <head>
    <meta name="x-apple-disable-message-reformatting">
    <meta name="color-scheme" content="light dark">
    <meta name="supported-color-schemes" content="light dark">
    <title></title>
  </head>
  <body style="margin:0;padding:0;background:{background};">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:100%;table-layout:fixed;background:{background};">
      <tr><td align="center">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:640px;margin:0 auto;background:{background};">
          <tr>
            <td style="padding:12px 20px;text-align:left;">
              {f'<img src="{escape(logo_url)}" alt="Logo" style="max-width:140px;height:auto;border:0;display:block;">' if logo_url else ''}
            </td>
          </tr>
          <tr>
            <td style="font-family:{font_stack};color:{text};font-size:16px;line-height:1.6;padding:16px 20px;border-top:3px solid {accent};">
              {inner_html}
            </td>
          </tr>
          {"<tr><td style='font-family:%s;color:%s;font-size:12px;line-height:1.6;padding:12px 20px 24px;'></td></tr>" % (font_stack, mutetext) if show_footer else ""}
        </table>
      </td></tr>
    </table>
  </body>
</html>"""
