from dataclasses import dataclass, field
from pathlib import Path


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
    tokens: tuple = ()
    roles: tuple = ()
    versions: tuple = ()
    sequence: str = ""
    numbers: tuple = ()
    pattern: str = ""
    number: int | None = None
    year: int | None = None
    academic_year: int | None = None
    referrer_hint: tuple | None = field(default=None,repr=False)
    course_scope: tuple | None = field(default=None,repr=False)
    download: DownloadContext = field(default_factory=DownloadContext)
    index: int = 0
    group: object = None
    state: str = "미분류"
    note: str = ""
    confidence: float | None = None
    evidence: str = ""
    first_band: str = "낮음"
    excerpt_status: str = ""
    course_cover_checked: bool = False
    @property
    def name(self): return self.path.name
    @property
    def host(self): return self.download.domain


@dataclass(eq=False)
class Group:
    gid: str
    title: str
    members: list
    confidence: float | None = None
    cohesion: float = 0
    title_note: str = ""
    title_kind: str = "topic"


@dataclass
class Study:
    root: Path
    deep: bool
    files: list = field(default_factory=list)
    groups: list = field(default_factory=list)
    matrix: list = field(default_factory=list)
    primary: list = field(default_factory=list)
    vectors: list = field(default_factory=list)
    task_prefixes: list = field(default_factory=list)
    extras: dict = field(default_factory=dict)
    medium: set = field(default_factory=set)
    attempted: set = field(default_factory=set)
    skipped: int = 0
    tried: int = 0
    rescued: int = 0
    ms: int = 0
    revision: int = 0
