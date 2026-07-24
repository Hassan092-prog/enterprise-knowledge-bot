import pytest
from pathlib import Path
from src.ingestion.document_loader import load_document

def test_load_document_not_found():
    with pytest.raises(FileNotFoundError):
        load_document(Path("does_not_exist.pdf"))

def test_load_document_unsupported_ext(tmp_path):
    p = tmp_path / "test.jpg"
    p.write_text("dummy")
    with pytest.raises(ValueError, match="Unsupported file type"):
        load_document(p)

def test_load_txt(tmp_path):
    p = tmp_path / "test.txt"
    p.write_text("Hello world")
    
    docs = load_document(p)
    assert len(docs) == 1
    assert docs[0].page_content == "Hello world"
    assert docs[0].metadata["source"] == "test.txt"
    assert docs[0].metadata["file_type"] == "txt"
