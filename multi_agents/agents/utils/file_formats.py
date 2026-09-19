import aiofiles
import urllib
import uuid
import mistune

async def write_to_file(filename: str, text: str) -> None:
    """Asynchronously write text to a file in UTF-8 encoding.

    Args:
        filename (str): The filename to write to.
        text (str): The text to write.
    """
    # Ensure text is a string
    if not isinstance(text, str):
        text = str(text)

    # Convert text to UTF-8, replacing any problematic characters
    text_utf8 = text.encode('utf-8', errors='replace').decode('utf-8')

    async with aiofiles.open(filename, "w", encoding='utf-8') as file:
        await file.write(text_utf8)

async def write_text_to_md(text: str, path: str) -> str:
    """Writes text to a Markdown file and returns the file path.

    Args:
        text (str): Text to write to the Markdown file.

    Returns:
        str: The file path of the generated Markdown file.
    """
    task = uuid.uuid4().hex
    file_path = f"{path}/{task}.md"
    await write_to_file(file_path, text)
    print(f"Report written to {file_path}")
    return file_path


# Fonts forced into every exported DOCX. See the matching comment in
# backend/utils.py: python-docx's default template names no East Asian font in
# its theme, so Word falls back to mixing Cambria (Latin, serif) with 宋体
# (Chinese) on the same line, which reads as uneven.
_DOCX_LATIN_FONT = "Segoe UI"
_DOCX_EAST_ASIA_FONT = "微软雅黑"


def _apply_docx_fonts(docx_path: str) -> None:
    """Write an explicit Latin + East Asian typeface into a saved DOCX.

    Patches the theme rather than individual styles, because nearly every style
    in the default template references the theme. python-docx exposes the theme
    part as read-only, so the saved package is rewritten instead.
    """
    import os
    import re
    import zipfile

    theme_part = "word/theme/theme1.xml"
    tmp_path = f"{docx_path}.tmp"

    with zipfile.ZipFile(docx_path) as src, zipfile.ZipFile(
        tmp_path, "w", zipfile.ZIP_DEFLATED
    ) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == theme_part:
                theme = data.decode("utf-8")
                theme = re.sub(
                    r'<a:latin typeface="[^"]*"',
                    f'<a:latin typeface="{_DOCX_LATIN_FONT}"',
                    theme,
                )
                theme = re.sub(
                    r'<a:ea typeface="[^"]*"',
                    f'<a:ea typeface="{_DOCX_EAST_ASIA_FONT}"',
                    theme,
                )
                # Per-script entries beat <a:ea> for the scripts they name.
                theme = re.sub(
                    r'<a:font script="(Hans|Hant)" typeface="[^"]*"',
                    rf'<a:font script="\1" typeface="{_DOCX_EAST_ASIA_FONT}"',
                    theme,
                )
                data = theme.encode("utf-8")
            dst.writestr(item, data)

    os.replace(tmp_path, docx_path)


async def write_md_to_word(text: str, path: str) -> str:
    """Converts Markdown text to a DOCX file and returns the file path.

    Args:
        text (str): Markdown text to convert.

    Returns:
        str: The encoded file path of the generated DOCX.
    """
    task = uuid.uuid4().hex
    file_path = f"{path}/{task}.docx"

    try:
        from htmldocx import HtmlToDocx
        from docx import Document
        # Convert report markdown to HTML
        html = mistune.html(text)
        # Create a document object
        doc = Document()
        # Convert the html generated from the report to document format
        HtmlToDocx().add_html_to_document(html, doc)

        # Saving the docx document to file_path
        doc.save(file_path)
        _apply_docx_fonts(file_path)

        print(f"Report written to {file_path}")

        encoded_file_path = urllib.parse.quote(file_path)
        return encoded_file_path

    except Exception as e:
        print(f"Error in converting Markdown to DOCX: {e}")
        return ""
