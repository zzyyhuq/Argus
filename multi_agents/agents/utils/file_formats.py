import aiofiles
import urllib
import uuid
import mistune

async def write_to_file(filename: str, text: str) -> None:
    """以 UTF-8 编码异步把文本写入文件。

    参数：
        filename (str): 要写入的文件名。
        text (str): 要写入的文本。
    """
    # 确保 text 是字符串
    if not isinstance(text, str):
        text = str(text)

    # 转成 UTF-8，并把无法编码的字符替换掉
    text_utf8 = text.encode('utf-8', errors='replace').decode('utf-8')

    async with aiofiles.open(filename, "w", encoding='utf-8') as file:
        await file.write(text_utf8)

async def write_text_to_md(text: str, path: str) -> str:
    """把文本写入 Markdown 文件并返回文件路径。

    参数：
        text (str): 要写入 Markdown 文件的文本。

    返回：
        str: 生成的 Markdown 文件的路径。
    """
    task = uuid.uuid4().hex
    file_path = f"{path}/{task}.md"
    await write_to_file(file_path, text)
    print(f"Report written to {file_path}")
    return file_path


# 强制写入每个导出的 DOCX 的字体。参见 backend/utils.py 中对应的注释：
# python-docx 的默认模板在 theme 里没有指定任何东亚字体，于是 Word 会退化成
# 在同一行里混用 Cambria（拉丁文衬线体）与宋体，看起来参差不齐。
_DOCX_LATIN_FONT = "Segoe UI"
_DOCX_EAST_ASIA_FONT = "微软雅黑"


def _apply_docx_fonts(docx_path: str) -> None:
    """把明确的拉丁文字体 + 东亚字体写入已保存的 DOCX。

    改的是 theme 而不是单个样式，因为默认模板里几乎每个样式都引用 theme。
    python-docx 把 theme 部分暴露为只读，所以这里改为重写整个已保存的包。
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
                # 对于自身列出的文字，按 script 的条目优先级高于 <a:ea>。
                theme = re.sub(
                    r'<a:font script="(Hans|Hant)" typeface="[^"]*"',
                    rf'<a:font script="\1" typeface="{_DOCX_EAST_ASIA_FONT}"',
                    theme,
                )
                data = theme.encode("utf-8")
            dst.writestr(item, data)

    os.replace(tmp_path, docx_path)


async def write_md_to_word(text: str, path: str) -> str:
    """把 Markdown 文本转成 DOCX 文件并返回文件路径。

    参数：
        text (str): 要转换的 Markdown 文本。

    返回：
        str: 生成的 DOCX 经过编码后的文件路径。
    """
    task = uuid.uuid4().hex
    file_path = f"{path}/{task}.docx"

    try:
        from htmldocx import HtmlToDocx
        from docx import Document
        # 把报告 markdown 转成 HTML
        html = mistune.html(text)
        # 创建文档对象
        doc = Document()
        # 把由报告生成的 html 转成文档格式
        HtmlToDocx().add_html_to_document(html, doc)

        # 把 docx 文档保存到 file_path
        doc.save(file_path)
        _apply_docx_fonts(file_path)

        print(f"Report written to {file_path}")

        encoded_file_path = urllib.parse.quote(file_path)
        return encoded_file_path

    except Exception as e:
        print(f"Error in converting Markdown to DOCX: {e}")
        return ""
