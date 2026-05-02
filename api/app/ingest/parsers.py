from pathlib import Path

from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import InputFormat
from docling.datamodel.document import DoclingDocument

_converter = DocumentConverter()


def parse(file_path: str | Path) -> DoclingDocument:
    result = _converter.convert(str(file_path))
    return result.document
