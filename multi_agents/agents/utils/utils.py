import re

def sanitize_filename(filename: str) -> str:
    """
    清理文件名，把 Windows 文件路径中非法字符替换为下划线（'_'）。

    文件名要能在各操作系统上都用得了，所以 Windows 文件路径不允许的字符必须去掉
    或替换掉。具体替换以下字符：< > : " / \\ | ? *

    参数：
    filename (str): 待清理的原始文件名。

    返回：
    str: 清理后的文件名，非法字符已替换为下划线。
    
    示例：
    >>> sanitize_filename('invalid:file/name*example?.txt')
    'invalid_file_name_example_.txt'
    
    >>> sanitize_filename('valid_filename.txt')
    'valid_filename.txt'
    """
    return re.sub(r'[<>:"/\\|?*]', '_', filename)
