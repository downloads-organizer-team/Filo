from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict
if TYPE_CHECKING:
    from topics import Activity
from constraints import Constraints

CourseNamespace = tuple[tuple[str,int|None],str] | tuple[tuple[str,int|None],str,str]


@dataclass
class Vector:
    literal: dict[str,float]
    context: dict[str,float]
    grams: frozenset[str]


@dataclass
class DownloadContext:
    url: str = ""
    domain: str = ""
    page_title: str = ""
    downloaded_at: str = ""
    directory: str = ""
    course_name: str = ""
    course_page: str = ""
    source_page: str = ""


@dataclass(eq=False)
class File:
    path: Path
    uid: str
    rel: str
    size: int
    created: float
    modified: float
    mtime_ns: int
    offline: bool
    ext: str = ""
    normalized: str = ""
    tokens: tuple[str,...] = ()
    roles: tuple[str,...] = ()
    versions: tuple[str,...] = ()
    sequence: str = ""
    numbers: tuple[str,...] = ()
    pattern: str = ""
    number: int | None = None
    year: int | None = None
    academic_year: int | None = None
    referrer_hint: tuple[CourseNamespace,str,str|None] | None = field(default=None,repr=False)
    course_scope: tuple[CourseNamespace,str] | None = field(default=None,repr=False)
    download: DownloadContext = field(default_factory=DownloadContext)
    index: int = 0
    group: Group | None = None
    state: str = "미분류"
    note: str = ""
    confidence: float | None = None
    evidence: str = ""
    first_band: str = "낮음"
    excerpt_status: str = ""
    course_cover_checked: bool = False
    digest: str = ""
    hold_reason: str = ""
    @property
    def name(self): return self.path.name
    @property
    def host(self): return self.download.domain


@dataclass(eq=False)
class Group:
    gid: str
    title: str
    members: list[File]
    confidence: float | None = None
    cohesion: float = 0
    title_note: str = ""
    title_kind: str = "topic"
    destination: Path | None = None
    destination_reason: str = ""


@dataclass
class Study:
    root: Path
    deep: bool
    files: list[File] = field(default_factory=list)
    groups: list[Group] = field(default_factory=list)
    matrix: list[bytearray] = field(default_factory=list)
    primary: list[bytearray] = field(default_factory=list)
    vectors: list[Vector] = field(default_factory=list)
    task_prefixes: list[str] = field(default_factory=list)
    extras: dict[int,Vector] = field(default_factory=dict)
    medium: set[int] = field(default_factory=set)
    attempted: set[int] = field(default_factory=set)
    skipped: int = 0
    tried: int = 0
    rescued: int = 0
    ms: int = 0
    revision: int = 0
    roots: list[Path] = field(default_factory=list)
    rules: Constraints | None = field(default=None,repr=False)
    idf: dict[str,float] = field(default_factory=dict)
    task_heads: list[str] = field(default_factory=list)
    parents: list[str] = field(default_factory=list)
    source_pages: list[tuple[str,str,str]|None] = field(default_factory=list)
    role_sets: list[frozenset[str]] = field(default_factory=list)
    download_times: list[float|None] = field(default_factory=list)
    activities: list[Activity | None] = field(default_factory=list)
    bilingual_topics: list[str] = field(default_factory=list)
    opaque_formats: list[tuple[str,int,tuple[int,...]] | None] = field(default_factory=list)
    min_confidence: float = 0.7
    folder_mode: str = "new"
    group_by: str = "related"


class ScanOptions(TypedDict):
    groupBy: str
    recursive: bool
    deep: bool
    covers: bool
    roots: list[str]
    minConfidence: float
    folderMode: str


class FileRow(TypedDict):
    id: int
    name: str
    path: str
    ext: str
    group: str | None
    state: str
    confidence: float | None
    size: int
    host: str
    note: str


class GroupRow(TypedDict):
    reason: str
    folderEvidence: list[str]
    id: str
    title: str
    note: str
    confidence: float | None
    count: int


class ScanResult(TypedDict):
    layout: list[dict]
    root: str
    roots: list[str]
    files: list[FileRow]
    groups: list[GroupRow]
    options: ScanOptions
    generation: str
    time: str
    elapsed: int
    medium: int
    attempted: int
    rescued: int
    covers: int


class MoveRow(TypedDict):
    name: str
    source: str
    target: str
    skip: str


class MovePreview(TypedDict):
    token: str
    rows: list[MoveRow]


class RelatedFile(TypedDict):
    id: int
    name: str
    score: int
    group: str | None
    signals: list[str]


class HistoryEvent(TypedDict):
    operation: str
    id: str
    readable: bool
    time: str
    moved: int
    undone: int
    pending: int
    files: list[str]
