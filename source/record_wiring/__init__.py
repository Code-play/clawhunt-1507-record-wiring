"""record_wiring：管理记录知识接线（来源指针 / append-only / 权限 / 脱敏 / 引用）。"""

from .access import AccessController, AccessPolicy, load_policy
from .citation import CitationError, build_citation, resolve_citation
from .config import DEFAULT_INGEST_AT, PROJECT_ROOT
from .ingest import IngestReport, Ingestor
from .model import AccessTag, ModelError, Record, SourcePointer, sha256_text
from .privacy import PrivacyEngine, RedactionFinding, load_engine
from .schema import Schema, SchemaError, load_schema
from .store import AppendOnlyStore, StoreError
from .trace import TraceRecorder

__version__ = "1.0.0"

__all__ = [
    "AccessController",
    "AccessPolicy",
    "AccessTag",
    "AppendOnlyStore",
    "CitationError",
    "DEFAULT_INGEST_AT",
    "IngestReport",
    "Ingestor",
    "ModelError",
    "PrivacyEngine",
    "PROJECT_ROOT",
    "Record",
    "RedactionFinding",
    "Schema",
    "SchemaError",
    "SourcePointer",
    "StoreError",
    "TraceRecorder",
    "__version__",
    "build_citation",
    "load_engine",
    "load_policy",
    "load_schema",
    "resolve_citation",
    "sha256_text",
]
