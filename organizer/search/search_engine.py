"""Run the bundled Everything folder index under the current Windows account."""
import ctypes
from ctypes import wintypes
from hashlib import sha256
import os
from pathlib import Path
from organizer import APP_ROOT
import subprocess
from time import monotonic

from organizer.files import storage


ENGINE = APP_ROOT / "vendor" / "everything" / "Everything.exe"
INSTANCE_PREFIX = "DownloadsOrganizer-"
CONFIG = """[Everything]
app_data=0
run_as_admin=0
index_as_admin=0
allow_everything_service=0
show_tray_icon=0
show_in_tray=0
check_for_updates_on_startup=0
search_history_enabled=0
run_history_enabled=0
"""


def private_instance():
    profile = os.path.normcase(str(storage.HOME.resolve())).encode("utf-8")
    return INSTANCE_PREFIX + sha256(profile).hexdigest()[:20]


def index_roots():
    if "MOA_SEARCH_ROOTS" in os.environ:
        roots = [Path(s) for s in os.environ["MOA_SEARCH_ROOTS"].split(";") if s]
        if not roots or any(not p.is_absolute() or not p.is_dir() for p in roots):
            raise OSError("검색할 폴더 경로를 확인하세요.")
        return [str(p) for p in roots]
    drive_type = ctypes.windll.kernel32.GetDriveTypeW
    drive_type.argtypes = [ctypes.c_wchar_p]
    drive_type.restype = wintypes.UINT
    roots = [root for root in os.listdrives() if drive_type(root) == 3]  # DRIVE_FIXED
    if not roots:
        raise OSError("검색할 로컬 드라이브를 찾을 수 없습니다.")
    return roots


class BasicJobLimits(ctypes.Structure):
    _fields_ = [
        ("per_process_time", ctypes.c_int64), ("per_job_time", ctypes.c_int64),
        ("flags", wintypes.DWORD), ("minimum_working_set", ctypes.c_size_t),
        ("maximum_working_set", ctypes.c_size_t), ("active_process_limit", wintypes.DWORD),
        ("affinity", ctypes.c_size_t), ("priority_class", wintypes.DWORD),
        ("scheduling_class", wintypes.DWORD),
    ]


class ExtendedJobLimits(ctypes.Structure):
    _fields_ = [
        ("basic", BasicJobLimits), ("io_counters", ctypes.c_uint64 * 6),
        ("process_memory_limit", ctypes.c_size_t), ("job_memory_limit", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t),
    ]


def lifetime_job(process):
    """Windows closes the last job handle even if the desktop service crashes."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateJobObjectW
    create.argtypes, create.restype = [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE
    configure = kernel.SetInformationJobObject
    configure.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    assign = kernel.AssignProcessToJobObject
    assign.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    job = create(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = ExtendedJobLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not (configure(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
            and assign(job, process._handle)):
        error = ctypes.WinError(ctypes.get_last_error())
        close(job)
        raise error
    return lambda: close(job)


class BundledEngine:
    def __init__(self):
        self.instance = private_instance()
        self.process = None
        self.release_job = None
        self.started = 0.0
        self.failed_starts = 0

    def start(self):
        if self.process is not None:
            if self.process.poll() is None:
                return
            self.release_job()
            self.release_job = None
            self.process = None
            self.failed_starts = self.failed_starts + 1 if monotonic() - self.started < 10 else 0
        if self.failed_starts >= 3:
            raise OSError("내장 검색 엔진이 종료됐습니다. 앱을 다시 열어 주세요.")
        if not ENGINE.is_file():
            raise FileNotFoundError("내장 검색 엔진 파일이 없습니다. 앱을 다시 설치해 주세요.")
        directory = (storage.HOME / "Search").resolve()
        directory.mkdir(parents=True, exist_ok=True)
        config = directory / "Everything.ini"
        # Everything also stores folder monitor and refresh settings here on shutdown.
        if not config.exists():
            config.write_text(CONFIG, encoding="utf-8-sig")
        database = directory / "Everything.db"
        args = [str(ENGINE), "-instance", self.instance, "-config", str(config), "-db", str(database),
                "-no-auto-index", "-folders", ";".join(index_roots()), "-startup"]
        if database.is_file():
            args.append("-rescan-all")
        process = subprocess.Popen(args, cwd=directory, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            self.release_job = lifetime_job(process)
        except OSError:
            process.kill()
            process.wait()
            raise
        self.process = process
        self.started = monotonic()

    def close(self):
        if self.process is None:
            return
        try:
            if self.process.poll() is None:
                subprocess.run([str(ENGINE), "-instance", self.instance, "-exit"], timeout=5,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                self.process.wait(timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            self.release_job()
            self.process.wait()
            self.process = None
            self.release_job = None
