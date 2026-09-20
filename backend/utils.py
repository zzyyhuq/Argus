import aiofiles
import urllib
import mistune
import os

async def write_to_file(filename: str, text: str) -> None:
    """以 UTF-8 编码异步地把文本写入文件。

    参数：
        filename (str): 要写入的文件名。
        text (str): 要写入的文本。
    """
    # 确保 text 是字符串
    if not isinstance(text, str):
        text = str(text)

    # 转成 UTF-8，顺带替换掉任何有问题的字符
    text_utf8 = text.encode('utf-8', errors='replace').decode('utf-8')

    async with aiofiles.open(filename, "w", encoding='utf-8') as file:
        await file.write(text_utf8)

async def write_text_to_md(text: str, filename: str = "") -> str:
    """把文本写入 Markdown 文件并返回文件路径。

    参数：
        text (str): 要写入 Markdown 文件的文本。

    返回：
        str: 生成的 Markdown 文件路径。
    """
    import uuid

    safe_name = (filename or "").strip()[:60] or f"report-{uuid.uuid4().hex[:12]}"
    safe_name = safe_name.replace("/", "-").replace("\\", "-")
    os.makedirs("outputs", exist_ok=True)
    file_path = f"outputs/{safe_name}.md"
    await write_to_file(file_path, text)
    return urllib.parse.quote(file_path)

# 强制写入每个导出的 DOCX 的字体。
#
# python-docx 自带默认模板的主题里没有声明任何东亚字体（`<a:ea typeface=""/>`），
# 也没有在任何 run 上设置字体，于是整个文档都继承那个主题。Word 随后自行回退：
# 拉丁字母正文落到了 Cambria（衬线），中文则按主题的按脚本提示落到宋体——两种
# 毫无关系的字体共处一行，笔画粗细、x-height 与基线都不一样，看上去就是"参差不
# 齐"。标题更糟：Calibri（无衬线）紧挨着宋体（衬线）。
_DOCX_LATIN_FONT = "Segoe UI"
_DOCX_EAST_ASIA_FONT = "微软雅黑"


def _apply_docx_fonts(docx_path: str) -> None:
    """把显式的拉丁与东亚字体写进已保存的 DOCX。

    选择改主题而不是逐个改样式，是有意为之：默认模板里几乎所有样式都引用主题，
    所以改一处即可覆盖正文、标题、表格与列表。python-docx 把主题当作普通的
    ``Part`` 加载，其 blob 是只读的，因此这里采取重写已保存的包、而不是通过对象
    模型去编辑它。
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
                # 按脚本的条目对它点名的那些脚本优先于 <a:ea>，所以中文的那几条
                # 也必须一起替换，否则不管怎样都是宋体胜出。
                theme = re.sub(
                    r'<a:font script="(Hans|Hant)" typeface="[^"]*"',
                    rf'<a:font script="\1" typeface="{_DOCX_EAST_ASIA_FONT}"',
                    theme,
                )
                data = theme.encode("utf-8")
            dst.writestr(item, data)

    os.replace(tmp_path, docx_path)


async def write_md_to_word(text: str, filename: str = "") -> str:
    """把 Markdown 文本转成 DOCX 文件并返回文件路径。

    参数：
        text (str): 要转换的 Markdown 文本。

    返回：
        str: 生成的 DOCX 经 URL 编码后的文件路径。
    """
    import uuid

    safe_name = (filename or "").strip()[:60] or f"report-{uuid.uuid4().hex[:12]}"
    safe_name = safe_name.replace("/", "-").replace("\\", "-")
    os.makedirs("outputs", exist_ok=True)
    file_path = f"outputs/{safe_name}.docx"

    try:
        from docx import Document
        from htmldocx import HtmlToDocx
        # 把报告的 markdown 转成 HTML
        html = mistune.html(text)
        # 创建文档对象
        doc = Document()
        # 把由报告生成的 HTML 转成文档格式
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