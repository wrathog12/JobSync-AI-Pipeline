"""Ingest — documents in, text out. No interpretation happens here.

    extract(data, filename)  ->  RawDocument   # PDF / DOCX / TXT, sniffed
    extract_pasted(text)     ->  RawDocument   # the always-works escape hatch

Structuring that text into L0/L1/L2 records is the next step and an LLM one.
Keeping it separate means a layout bug shows up as visibly scrambled text rather
than as a confidently wrong employment date.
"""

from .extract import extract, extract_pasted, sniff
from .normalize import normalize
from .store import DocumentStore, get_documents

__all__ = ["extract", "extract_pasted", "sniff", "normalize", "DocumentStore", "get_documents"]
