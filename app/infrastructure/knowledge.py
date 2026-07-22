from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import Path

from PIL import Image
from pypdf import PdfReader


class KnowledgeFileStore:
    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, tenant_id: str, filename: str, content: bytes) -> str:
        tenant_folder = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:24]
        suffix = Path(filename).suffix.lower()[:10]
        storage_key = f"{tenant_folder}/{uuid.uuid4()}{suffix}"
        target = self.root / storage_key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return storage_key

    def path(self, storage_key: str) -> Path:
        target = (self.root / storage_key).resolve()
        if self.root.resolve() not in target.parents:
            raise ValueError("Ruta de archivo inválida")
        return target

    def delete(self, storage_key: str) -> None:
        target = self.path(storage_key)
        if target.exists():
            target.unlink()


def extract_pdf_text(content: bytes) -> str:
    if not content.startswith(b"%PDF"):
        raise ValueError("El archivo no es un PDF válido")
    reader = PdfReader(io.BytesIO(content))
    if len(reader.pages) > 200:
        raise ValueError("El PDF supera el máximo de 200 páginas")
    return "\n".join((page.extract_text() or "") for page in reader.pages)[:100_000].strip()


def verify_image(content: bytes) -> None:
    with Image.open(io.BytesIO(content)) as image:
        image.verify()
