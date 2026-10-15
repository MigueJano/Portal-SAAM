from html.parser import HTMLParser
from urllib.parse import urlparse


ALLOWED_TAGS = {"p", "br", "strong", "b", "em", "i", "u", "ul", "ol", "li", "a"}
VOID_TAGS = {"br"}


class _RichTextSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.result = []

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TAGS:
            return
        if tag == "a":
            href = next((value for name, value in attrs if name == "href"), "")
            parsed = urlparse(href)
            if parsed.scheme in {"http", "https", "mailto"} or (not parsed.scheme and not href.startswith("//")):
                safe_href = (
                    href.replace("&", "&amp;")
                    .replace('"', "&quot;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )
                self.result.append(f'<a href="{safe_href}" rel="noopener noreferrer">')
                return
            self.result.append("<a>")
            return
        self.result.append(f"<{tag}>")

    def handle_endtag(self, tag):
        if tag in ALLOWED_TAGS and tag not in VOID_TAGS:
            self.result.append(f"</{tag}>")

    def handle_data(self, data):
        self.result.append(
            data.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )


def sanitize_rich_text(value):
    parser = _RichTextSanitizer()
    parser.feed(value or "")
    parser.close()
    return "".join(parser.result).strip()
