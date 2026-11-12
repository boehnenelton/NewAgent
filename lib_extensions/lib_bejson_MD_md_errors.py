"""
Library:         lib_bejson_MD_md_errors.py
Family:          MD
Module Purpose:  Implements runtime functionality and logic for lib_bejson_MD_md_errors.py.
Architecture:    MFDB provides multi-file database federation coordinating a 104a central manifest (104a.mfdb.bejson) with dense 104 entity tables, supporting atomic transaction locks and cross-disk relational foreign keys.
Version:         1.2.0
Release_Version: 300
Date:            2026-08-15
Author:          Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
Format_Creator:  Elton Boehnen
RELATIONAL_ID:   b69ba283-f3e2-44bc-9522-62164fd4cc33
"""

# --- Error Codes (reserved range: 90–109 for Lib_MD; was 70–89, moved to
#     resolve a collision with Core's 70-72 -- see CHANGE 2026-08-15) ---

E_MD_CHUNK_NOT_FOUND      = 90  # chunk_id not in index
E_MD_FILE_NOT_FOUND       = 91  # target markdown file missing
E_MD_INDEX_NOT_FOUND      = 92  # index document missing or unreadable
E_MD_CHUNK_DRIFT          = 93  # checksum mismatch — file edited out-of-band
E_MD_INDEX_STALE          = 94  # index not reindexed after known file write
E_MD_WRITE_FAILED         = 95  # atomic write to markdown file failed
E_MD_INJECT_RANGE_INVALID = 96  # start_line / end_line out of bounds
E_MD_ASSEMBLE_EMPTY       = 97  # assemble returned no chunks (all inactive or no match)
E_MD_MFDB_ERROR           = 98  # MFDB wrapper layer error
E_MD_INVALID_DOCUMENT     = 99  # loaded BEJSON doc fails structural check

class MarkdownLibError(Exception):
    """Base class for all lib_bejson_markdown errors."""
    def __init__(self, message: str, code: int = None):
        super().__init__(message)
        self.code = code

class ChunkNotFoundError(MarkdownLibError):
    """Raised when a chunk_id is not present in the active index."""
    def __init__(self, chunk_id: str):
        super().__init__(f"Chunk not found: '{chunk_id}'", E_MD_CHUNK_NOT_FOUND)
        self.chunk_id = chunk_id

class MdFileNotFoundError(MarkdownLibError):
    """
    Raised when the target markdown file does not exist on disk.

    LIB-MD-H1 fix (2026-08-08): this class used to be named
    FileNotFoundError, shadowing the Python builtin of the same name.
    Every real call site already defensively aliased it on import
    (`as MdFileNotFoundError`), so it wasn't an active bug -- but it was
    a landmine for any future code in this module that forgot to alias
    it (a bare `except FileNotFoundError` would silently catch this
    class instead of, or in addition to, the real builtin). Renamed at
    the source so the alias is no longer load-bearing.
    """
    def __init__(self, file_path: str):
        super().__init__(f"Markdown file not found: '{file_path}'", E_MD_FILE_NOT_FOUND)
        self.file_path = file_path

class IndexNotFoundError(MarkdownLibError):
    """Raised when the BEJSON index document is missing or cannot be loaded."""
    def __init__(self, index_path: str):
        super().__init__(f"Index not found or unreadable: '{index_path}'", E_MD_INDEX_NOT_FOUND)
        self.index_path = index_path

class ChunkDriftError(MarkdownLibError):
    """
    Raised when a chunk's stored checksum does not match the current file content.
    Indicates out-of-band edits to the markdown file. Caller must reindex.
    """
    def __init__(self, chunk_id: str, file_path: str, stored: str, actual: str):
        super().__init__(
            f"Chunk drift detected for '{chunk_id}' in '{file_path}'. "
            f"Stored checksum: {stored} | Actual: {actual}. Reindex required.",
            E_MD_CHUNK_DRIFT
        )
        self.chunk_id   = chunk_id
        self.file_path  = file_path
        self.stored     = stored
        self.actual     = actual

class IndexStaleError(MarkdownLibError):
    """Raised when the index is known to be stale after a failed write sequence."""
    def __init__(self, file_path: str):
        super().__init__(
            f"Index is stale for file '{file_path}'. Run reindex before reading.",
            E_MD_INDEX_STALE
        )
        self.file_path = file_path

class WriteFailedError(MarkdownLibError):
    """Raised when the atomic write to the markdown file fails."""
    def __init__(self, file_path: str, reason: str = ""):
        msg = f"Atomic write failed for '{file_path}'"
        if reason:
            msg += f": {reason}"
        super().__init__(msg, E_MD_WRITE_FAILED)
        self.file_path = file_path

class InjectRangeInvalidError(MarkdownLibError):
    """Raised when start_line or end_line is out of bounds for the target file."""
    def __init__(self, chunk_id: str, start_line: int, end_line: int, file_lines: int):
        super().__init__(
            f"Inject range invalid for chunk '{chunk_id}': "
            f"[{start_line}:{end_line}] out of bounds for file with {file_lines} lines.",
            E_MD_INJECT_RANGE_INVALID
        )
        self.chunk_id   = chunk_id
        self.start_line = start_line
        self.end_line   = end_line
        self.file_lines = file_lines

class AssembleEmptyError(MarkdownLibError):
    """Raised when assemble returns no chunks — either all inactive or no tag match."""
    def __init__(self, reason: str = ""):
        msg = "Assemble returned no chunks"
        if reason:
            msg += f": {reason}"
        super().__init__(msg, E_MD_ASSEMBLE_EMPTY)

class MFDBWrapperError(MarkdownLibError):
    """Raised when the MFDB wrapper layer encounters an error."""
    def __init__(self, message: str):
        super().__init__(f"MFDB wrapper error: {message}", E_MD_MFDB_ERROR)

class InvalidDocumentError(MarkdownLibError):
    """Raised when a loaded BEJSON document fails structural validation."""
    def __init__(self, path: str, reason: str = ""):
        msg = f"Invalid BEJSON document at '{path}'"
        if reason:
            msg += f": {reason}"
        super().__init__(msg, E_MD_INVALID_DOCUMENT)
        self.path = path