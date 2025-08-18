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

def convert_common_markdown_to_html(text: str) -> str:
    if not text:
        return ""
    
    # Bold: **text** -> <b>text</b>
    text = re.sub(r'\*\*(?=\S)(.*?)(?<=\S)\*\*', r'<b>\1</b>', text)
    # Italic: *text* or _text_ -> <i>text</i>
    text = re.sub(r'\*(?=\S)(.*?)(?<=\S)\*', r'<i>\1</i>', text)
    text = re.sub(r'_(?=\S)(.*?)(?<=\S)_', r'<i>\1</i>', text)
    # Strikethrough: ~~text~~ -> <s>text</s>
    text = re.sub(r'~~(?=\S)(.*?)(?<=\S)~~', r'<s>\1</s>', text)
    
    return text

def convert_markdown_code_to_html(text: str) -> str:
    def replacer(match):
        lang = match.group(1) or ""
        code = escape_html(match.group(2).strip())
        if lang:
            return f'<pre><code class="language-{lang}">{code}</code></pre>'
        else:
            return f'<pre>{code}</pre>'

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

def process_telegram_html(text: str) -> str:
    if not text:
        return ""
    markdown_converted = convert_common_markdown_to_html(text)
    code_converted = convert_markdown_code_to_html(markdown_converted)
    sanitized = sanitize_html_v2(code_converted)
    return sanitized