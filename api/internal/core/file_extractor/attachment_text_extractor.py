#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2026/10/26
@File    : attachment_text_extractor.py

聊天附件文本解析器。

对话场景下的附件是「随消息临时上传」的，没有 upload_file 记录、也不需要落到对象存储，
所以这里直接基于内存字节流解析，避免「上传到COS -> 再下载回来解析」这一圈往返。

仅使用项目里已经安装好的依赖(stdlib + pypdf)，不引入新的三方包：
- txt/md/csv/json/xml/log 等纯文本：按编码嗅探后直接解码
- html/htm：解码后去掉标签
- pdf：pypdf 逐页提取
- docx：解压后读 word/document.xml 去标签(等价于 python-docx 的文本结果)
- xlsx：解压后读 sharedStrings.xml + worksheets/sheetN.xml 拼表格文本
"""
import html
import io
import re
import zipfile

from internal.exception import FailException

# 纯文本扩展名(直接解码即可)
PLAIN_TEXT_EXTENSION = [
    "txt", "md", "markdown", "csv", "json", "xml", "log",
    "yml", "yaml", "ini", "conf", "sql", "py", "js", "ts",
]

# html扩展名(解码后需要去标签)
HTML_EXTENSION = ["html", "htm"]

# 二进制的office/pdf扩展名
PDF_EXTENSION = "pdf"
DOCX_EXTENSION = "docx"
XLSX_EXTENSION = "xlsx"

# PDF/Excel 最多解析的页数与工作表数量，避免超大文件拖垮进程
MAX_PDF_PAGE = 50
MAX_SHEET = 10
# 单个文件解析的安全上限，防止恶意超大文本撑爆内存
MAX_RAW_TEXT_LENGTH = 400000

# 服务端能解析出文本的扩展名合集(其余类型一律当作二进制附件，走对象存储+URL)
TEXT_PARSEABLE_EXTENSION = PLAIN_TEXT_EXTENSION + HTML_EXTENSION + [PDF_EXTENSION, DOCX_EXTENSION, XLSX_EXTENSION]


class AttachmentTextExtractor:
    """将对话附件(内存字节流)解析成纯文本"""

    @classmethod
    def is_parseable(cls, filename: str) -> bool:
        """判断该附件是否属于服务端能解析出文本的类型"""
        extension = cls.get_extension(filename)
        return extension in TEXT_PARSEABLE_EXTENSION

    @staticmethod
    def get_extension(filename: str) -> str:
        """提取文件名的小写扩展名(不含点)"""
        filename = filename or ""
        return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    @classmethod
    def extract(cls, filename: str, content: bytes) -> str:
        """根据文件名(扩展名)选择解析器，将字节流解析成纯文本"""
        # 1.提取扩展名并做基础校验
        extension = cls.get_extension(filename)
        if not content:
            raise FailException("附件内容为空，请重新上传")

        # 2.根据扩展名分发到不同的解析逻辑
        if extension in PLAIN_TEXT_EXTENSION or extension in HTML_EXTENSION:
            text = cls._decode(content)
            if extension in HTML_EXTENSION:
                text = cls._strip_html(text)
        elif extension == PDF_EXTENSION:
            text = cls._read_pdf(content)
        elif extension == DOCX_EXTENSION:
            text = cls._read_docx(content)
        elif extension == XLSX_EXTENSION:
            text = cls._read_xlsx(content)
        else:
            raise FailException(
                f"暂不支持解析.{extension or '未知'}格式的附件文本，已按普通文件附件处理"
            )

        # 3.清洗文本并校验是否解析出了有效内容
        text = cls._clean(text)
        if not text:
            raise FailException("未能从附件中解析出文本内容，请确认文件内容后重试")

        return text[:MAX_RAW_TEXT_LENGTH]

    @classmethod
    def _decode(cls, content: bytes) -> str:
        """按常见编码依次尝试解码字节流"""
        for encoding in ("utf-8", "utf-8-sig", "gb18030", "utf-16"):
            try:
                return content.decode(encoding)
            except (UnicodeDecodeError, UnicodeError):
                continue
        return content.decode("utf-8", errors="ignore")

    @classmethod
    def _strip_html(cls, text: str) -> str:
        """去掉html标签，保留可读文本"""
        text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
        text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h[1-6]>", "\n", text)
        text = re.sub(r"<[^>]+>", "", text)
        return html.unescape(text)

    @classmethod
    def _read_pdf(cls, content: bytes) -> str:
        """使用pypdf逐页提取pdf文本"""
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content))
            contents = []
            for page in reader.pages[:MAX_PDF_PAGE]:
                contents.append(page.extract_text() or "")
            return "\n\n".join(contents)
        except Exception:
            raise FailException("PDF附件解析失败，请确认该PDF不是扫描件(纯图片)后重试")

    @classmethod
    def _read_docx(cls, content: bytes) -> str:
        """解析docx：读取正文xml中的w:t节点，按段落换行"""
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zip_file:
                xml = zip_file.read("word/document.xml").decode("utf-8", errors="ignore")
        except Exception:
            raise FailException("docx附件解析失败，请确认文件未损坏后重试")

        # 段落结束换行、单元格/制表符保留可读性，再去掉全部标签
        xml = re.sub(r"(?i)</w:p>", "\n", xml)
        xml = re.sub(r"(?i)<w:tab[^>]*/>", "\t", xml)
        xml = re.sub(r"(?i)</w:tc>", "\t", xml)
        xml = re.sub(r"<[^>]+>", "", xml)
        return html.unescape(xml)

    @classmethod
    def _read_xlsx(cls, content: bytes) -> str:
        """解析xlsx：读取共享字符串与每个工作表，按行拼接成制表符分隔的文本"""
        try:
            zip_file = zipfile.ZipFile(io.BytesIO(content))
        except Exception:
            raise FailException("xlsx附件解析失败，请确认文件未损坏后重试")

        with zip_file:
            names = zip_file.namelist()
            # 1.读取共享字符串(单元格中形如 t="s" 的值是这里的下标)
            shared_strings = []
            if "xl/sharedStrings.xml" in names:
                shared_xml = zip_file.read("xl/sharedStrings.xml").decode("utf-8", errors="ignore")
                for item in re.findall(r"(?s)<si>(.*?)</si>", shared_xml):
                    shared_strings.append(
                        html.unescape("".join(re.findall(r"(?s)<t[^>]*>(.*?)</t>", item)))
                    )

            # 2.依次解析每个工作表
            sheet_names = sorted(
                name for name in names
                if re.match(r"xl/worksheets/sheet\d+\.xml$", name)
            )
            rows_text = []
            for sheet_name in sheet_names[:MAX_SHEET]:
                sheet_xml = zip_file.read(sheet_name).decode("utf-8", errors="ignore")
                for row in re.findall(r"(?s)<row[^>]*>(.*?)</row>", sheet_xml):
                    values = []
                    for attrs, inner in re.findall(r"(?s)<c([^>]*)>(.*?)</c>", row):
                        values.append(cls._parse_xlsx_cell(attrs, inner, shared_strings))
                    if any(value != "" for value in values):
                        rows_text.append("\t".join(values))
                rows_text.append("")

        return "\n".join(rows_text)

    @staticmethod
    def _parse_xlsx_cell(attrs: str, inner: str, shared_strings: list[str]) -> str:
        """解析单个xlsx单元格的值"""
        # 1.共享字符串类型
        if 't="s"' in attrs:
            match = re.search(r"(?s)<v>(\d+)</v>", inner)
            if match:
                index = int(match.group(1))
                if 0 <= index < len(shared_strings):
                    return shared_strings[index]
            return ""

        # 2.内联字符串类型
        if 't="inlineStr"' in attrs:
            return html.unescape("".join(re.findall(r"(?s)<t[^>]*>(.*?)</t>", inner)))

        # 3.数值/公式等类型直接取v节点的值
        match = re.search(r"(?s)<v>(.*?)</v>", inner)
        return html.unescape(match.group(1)) if match else ""

    @classmethod
    def _clean(cls, text: str) -> str:
        """清洗文本：统一换行符、去掉连续空行与行尾空白"""
        if not text:
            return ""
        text = text.lstrip("\ufeff")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
