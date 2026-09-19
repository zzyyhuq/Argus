import aiofiles
import urllib
import mistune
import os

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

async def write_text_to_md(text: str, filename: str = "") -> str:
    """Writes text to a Markdown file and returns the file path.

    Args:
        text (str): Text to write to the Markdown file.

    Returns:
        str: The file path of the generated Markdown file.
    """
    import uuid

    safe_name = (filename or "").strip()[:60] or f"report-{uuid.uuid4().hex[:12]}"
    safe_name = safe_name.replace("/", "-").replace("\\", "-")
    os.makedirs("outputs", exist_ok=True)
    file_path = f"outputs/{safe_name}.md"
    await write_to_file(file_path, text)
    return urllib.parse.quote(file_path)

# Fonts forced into every exported DOCX.
#
# python-docx's bundled default template declares no East Asian typeface in its
# theme (`<a:ea typeface=""/>`) and sets no font on any run, so the whole
# document inherits that theme. Word then falls back on its own: Latin body text
# came out in Cambria (a serif) and Chinese in 宋体 via the theme's per-script
# hint -- two unrelated faces sharing a line, with different stroke weight,
# x-height and baseline, which is what reads as "uneven". Headings were worse:
# Calibri (sans) beside 宋体 (serif).
_DOCX_LATIN_FONT = "Segoe UI"
_DOCX_EAST_ASIA_FONT = "微软雅黑"


def _apply_docx_fonts(docx_path: str) -> None:
    """Write an explicit Latin + East Asian typeface into a saved DOCX.

    Patching the theme rather than individual styles is deliberate: nearly every
    style in the default template references the theme, so this covers body
    text, headings, tables and lists in one place. python-docx loads the theme
    as a generic ``Part`` whose blob is read-only, hence rewriting the saved
    package instead of editing it through the object model.
    """
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
                # Per-script entries take precedence over <a:ea> for the scripts
                # they name, so the Chinese ones must be replaced too or 宋体
                # wins regardless.
                theme = re.sub(
                    r'<a:font script="(Hans|Hant)" typeface="[^"]*"',
                    rf'<a:font script="\1" typeface="{_DOCX_EAST_ASIA_FONT}"',
                    theme,
                )
                data = theme.encode("utf-8")
            dst.writestr(item, data)

    os.replace(tmp_path, docx_path)


async def write_md_to_word(text: str, filename: str = "") -> str:
    """Converts Markdown text to a DOCX file and returns the file path.

    Args:
        text (str): Markdown text to convert.

    Returns:
        str: The encoded file path of the generated DOCX.
    """
    import uuid

    safe_name = (filename or "").strip()[:60] or f"report-{uuid.uuid4().hex[:12]}"
    safe_name = safe_name.replace("/", "-").replace("\\", "-")
    os.makedirs("outputs", exist_ok=True)
    file_path = f"outputs/{safe_name}.docx"

    try:
        from docx import Document
        from htmldocx import HtmlToDocx
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