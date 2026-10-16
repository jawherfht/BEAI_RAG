from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Confidence(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CONFIDENCE_UNSPECIFIED: _ClassVar[Confidence]
    CONFIDENCE_LOW: _ClassVar[Confidence]
    CONFIDENCE_MEDIUM: _ClassVar[Confidence]
    CONFIDENCE_HIGH: _ClassVar[Confidence]
CONFIDENCE_UNSPECIFIED: Confidence
CONFIDENCE_LOW: Confidence
CONFIDENCE_MEDIUM: Confidence
CONFIDENCE_HIGH: Confidence

class Persona(_message.Message):
    __slots__ = ("agent_name", "role", "instructions", "tone", "response_style", "boundaries")
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    INSTRUCTIONS_FIELD_NUMBER: _ClassVar[int]
    TONE_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_STYLE_FIELD_NUMBER: _ClassVar[int]
    BOUNDARIES_FIELD_NUMBER: _ClassVar[int]
    agent_name: str
    role: str
    instructions: str
    tone: str
    response_style: str
    boundaries: str
    def __init__(self, agent_name: _Optional[str] = ..., role: _Optional[str] = ..., instructions: _Optional[str] = ..., tone: _Optional[str] = ..., response_style: _Optional[str] = ..., boundaries: _Optional[str] = ...) -> None: ...

class ConversationTurn(_message.Message):
    __slots__ = ("role", "text")
    ROLE_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    role: str
    text: str
    def __init__(self, role: _Optional[str] = ..., text: _Optional[str] = ...) -> None: ...

class RetrieveRequest(_message.Message):
    __slots__ = ("question", "language", "top_k")
    QUESTION_FIELD_NUMBER: _ClassVar[int]
    LANGUAGE_FIELD_NUMBER: _ClassVar[int]
    TOP_K_FIELD_NUMBER: _ClassVar[int]
    question: str
    language: str
    top_k: int
    def __init__(self, question: _Optional[str] = ..., language: _Optional[str] = ..., top_k: _Optional[int] = ...) -> None: ...

class RetrievedChunk(_message.Message):
    __slots__ = ("source_id", "file_name", "page", "section", "url", "text", "score")
    SOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    FILE_NAME_FIELD_NUMBER: _ClassVar[int]
    PAGE_FIELD_NUMBER: _ClassVar[int]
    SECTION_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    SCORE_FIELD_NUMBER: _ClassVar[int]
    source_id: str
    file_name: str
    page: int
    section: str
    url: str
    text: str
    score: float
    def __init__(self, source_id: _Optional[str] = ..., file_name: _Optional[str] = ..., page: _Optional[int] = ..., section: _Optional[str] = ..., url: _Optional[str] = ..., text: _Optional[str] = ..., score: _Optional[float] = ...) -> None: ...

class RetrieveResponse(_message.Message):
    __slots__ = ("chunks", "confidence", "fallback")
    CHUNKS_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    FALLBACK_FIELD_NUMBER: _ClassVar[int]
    chunks: _containers.RepeatedCompositeFieldContainer[RetrievedChunk]
    confidence: Confidence
    fallback: bool
    def __init__(self, chunks: _Optional[_Iterable[_Union[RetrievedChunk, _Mapping]]] = ..., confidence: _Optional[_Union[Confidence, str]] = ..., fallback: _Optional[bool] = ...) -> None: ...

class AnswerRequest(_message.Message):
    __slots__ = ("question", "language", "persona", "conversation_history")
    QUESTION_FIELD_NUMBER: _ClassVar[int]
    LANGUAGE_FIELD_NUMBER: _ClassVar[int]
    PERSONA_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_HISTORY_FIELD_NUMBER: _ClassVar[int]
    question: str
    language: str
    persona: Persona
    conversation_history: _containers.RepeatedCompositeFieldContainer[ConversationTurn]
    def __init__(self, question: _Optional[str] = ..., language: _Optional[str] = ..., persona: _Optional[_Union[Persona, _Mapping]] = ..., conversation_history: _Optional[_Iterable[_Union[ConversationTurn, _Mapping]]] = ...) -> None: ...

class Source(_message.Message):
    __slots__ = ("file_name", "page", "section", "url", "snippet", "score")
    FILE_NAME_FIELD_NUMBER: _ClassVar[int]
    PAGE_FIELD_NUMBER: _ClassVar[int]
    SECTION_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    SNIPPET_FIELD_NUMBER: _ClassVar[int]
    SCORE_FIELD_NUMBER: _ClassVar[int]
    file_name: str
    page: int
    section: str
    url: str
    snippet: str
    score: float
    def __init__(self, file_name: _Optional[str] = ..., page: _Optional[int] = ..., section: _Optional[str] = ..., url: _Optional[str] = ..., snippet: _Optional[str] = ..., score: _Optional[float] = ...) -> None: ...

class Latency(_message.Message):
    __slots__ = ("embed_ms", "search_ms", "rerank_ms", "llm_ttft_ms", "total_ms")
    EMBED_MS_FIELD_NUMBER: _ClassVar[int]
    SEARCH_MS_FIELD_NUMBER: _ClassVar[int]
    RERANK_MS_FIELD_NUMBER: _ClassVar[int]
    LLM_TTFT_MS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_MS_FIELD_NUMBER: _ClassVar[int]
    embed_ms: float
    search_ms: float
    rerank_ms: float
    llm_ttft_ms: float
    total_ms: float
    def __init__(self, embed_ms: _Optional[float] = ..., search_ms: _Optional[float] = ..., rerank_ms: _Optional[float] = ..., llm_ttft_ms: _Optional[float] = ..., total_ms: _Optional[float] = ...) -> None: ...

class AnswerFinal(_message.Message):
    __slots__ = ("display_text", "spoken_text", "sources", "confidence", "fallback", "latency")
    DISPLAY_TEXT_FIELD_NUMBER: _ClassVar[int]
    SPOKEN_TEXT_FIELD_NUMBER: _ClassVar[int]
    SOURCES_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    FALLBACK_FIELD_NUMBER: _ClassVar[int]
    LATENCY_FIELD_NUMBER: _ClassVar[int]
    display_text: str
    spoken_text: str
    sources: _containers.RepeatedCompositeFieldContainer[Source]
    confidence: Confidence
    fallback: bool
    latency: Latency
    def __init__(self, display_text: _Optional[str] = ..., spoken_text: _Optional[str] = ..., sources: _Optional[_Iterable[_Union[Source, _Mapping]]] = ..., confidence: _Optional[_Union[Confidence, str]] = ..., fallback: _Optional[bool] = ..., latency: _Optional[_Union[Latency, _Mapping]] = ...) -> None: ...

class AnswerChunk(_message.Message):
    __slots__ = ("token", "final")
    TOKEN_FIELD_NUMBER: _ClassVar[int]
    FINAL_FIELD_NUMBER: _ClassVar[int]
    token: str
    final: AnswerFinal
    def __init__(self, token: _Optional[str] = ..., final: _Optional[_Union[AnswerFinal, _Mapping]] = ...) -> None: ...

class StatusRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class StatusResponse(_message.Message):
    __slots__ = ("files", "urls", "rag_enabled", "status", "label")
    FILES_FIELD_NUMBER: _ClassVar[int]
    URLS_FIELD_NUMBER: _ClassVar[int]
    RAG_ENABLED_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    LABEL_FIELD_NUMBER: _ClassVar[int]
    files: int
    urls: int
    rag_enabled: bool
    status: str
    label: str
    def __init__(self, files: _Optional[int] = ..., urls: _Optional[int] = ..., rag_enabled: _Optional[bool] = ..., status: _Optional[str] = ..., label: _Optional[str] = ...) -> None: ...
