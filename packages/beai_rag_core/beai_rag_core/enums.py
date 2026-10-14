"""Domain enums shared by the API, the worker and the database (spec section 4.1)."""

from enum import StrEnum


class KnowledgeBaseStatus(StrEnum):
    EMPTY = "empty"
    INDEXING = "indexing"
    READY = "ready"
    ERROR = "error"


class SourceType(StrEnum):
    FILE = "file"
    URL = "url"
    BUSINESS_INFO = "business_info"


class SourceStatus(StrEnum):
    QUEUED = "queued"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    READY = "ready"
    ERROR = "error"
    DELETING = "deleting"


class JobKind(StrEnum):
    INDEX = "index"
    REINDEX = "reindex"
    DELETE = "delete"
    RECRAWL = "recrawl"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
