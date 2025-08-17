import re
from bs4 import BeautifulSoup

ALLOWED_TAGS = [
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "span", "tg-spoiler", "a", "tg-emoji", "code", "pre", "blockquote"
]

def escape_html(text: str) -> str:
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def convert_markdown_code_to_html(text: str) -> str:
    """Finds Markdown-style code blocks and converts them to HTML <pre><code>."""
    def replacer(match):
        lang = match.group(1) or ""
        code = escape_html(match.group(2).strip())
        if lang:
            return f'<pre><code class="language-{lang}">{code}</code></pre>'
        else:
            return f'<pre>{code}</pre>'

    # Regex to find ```code``` or ```python...```
    pattern = re.compile(r'```(\w+)?\n(.*?)\n```', re.DOTALL)
    return pattern.sub(replacer, text)

def sanitize_html_v2(html_content: str) -> str:
    if not html_content:
        return ""

    soup = BeautifulSoup(html_content, 'html.parser')
    target_node = soup.body if soup.body else soup

    for tag in list(target_node.find_all(True)):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()
        elif tag.name == "span" and "tg-spoiler" not in (tag.get('class') or []):
            tag.unwrap()
        elif tag.name == "a" and not tag.has_attr('href'):
            tag.unwrap()
        elif tag.name == "pre":
            if not tag.find('code'):
                content = tag.string
                if content:
                    tag.string = ''
                    new_code_tag = soup.new_tag('code')
                    new_code_tag.string = content
                    tag.append(new_code_tag)

    if target_node.name == 'body':
        return ''.join(str(c) for c in target_node.contents)
    else:
        return str(target_node)

def truncate_html(html_string: str, limit: int = 3800) -> str:
    if len(html_string) <= limit:
        return html_string

    truncated = html_string[:limit]
    
    open_tags = []
    for tag_match in re.finditer(r"<(/)?([a-zA-Z0-9_-]+)[^>]*>", truncated):
        is_closing, tag_name = tag_match.groups()
        tag_name = tag_name.lower()
        if is_closing:
            if open_tags and open_tags[-1] == tag_name:
                open_tags.pop()
        elif not tag_match.group(0).endswith("/>"):
            open_tags.append(tag_name)
    
    end_pos = truncated.rfind('<')
    if end_pos > truncated.rfind('>'):
        truncated = truncated[:end_pos]

    for tag in reversed(open_tags):
        truncated += f"</{tag}>"

    return truncated + "\n..."

def process_telegram_html(text: str) -> str:
    """Runs the full sanitization and truncation process."""
    converted = convert_markdown_code_to_html(text)
    sanitized = sanitize_html_v2(converted)
    truncated = truncate_html(sanitized)
    return truncated
