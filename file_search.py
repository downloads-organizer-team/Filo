"""Literal filename search through the official SDK, or selected folders."""
from collections.abc import Callable, Sequence
from collections import deque
import ctypes
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from time import perf_counter
from typing import TypedDict

LIMIT = 200
ENTRY_LIMIT = 50000
WALK_SECONDS = 3


class SearchFile(TypedDict):
    name: str
    path: str
    isFolder: bool


class SearchResult(TypedDict):
    backend: str
    results: list[SearchFile]
    elapsed: int
    truncated: bool
    note: str


class InvalidQuery(ValueError):
    def __str__(self) -> str:
        return "파일 이름 일부를 1~200자로 입력하세요. 경로와 검색 연산자는 사용할 수 없습니다."


def sdk_search(query: str) -> SearchResult:
    """Run in a bounded child process: a stalled native IPC cannot hang the app."""
    dll_path = Path(os.environ.get(
        "MOA_EVERYTHING_DLL", str(Path(__file__).parent / "vendor" / "Everything3_x64.dll")))
    sdk = ctypes.WinDLL(str(dll_path.resolve()))
    pointer, size, boolean = ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int
    signatures = {
        "ConnectW": ([ctypes.c_wchar_p], pointer),
        "CreateSearchState": ([], pointer),
        "SetSearchTextW": ([pointer, ctypes.c_wchar_p], boolean),
        "SetSearchViewportCount": ([pointer, size], boolean),
        "GetSearchViewportCount": ([pointer], size),
        "AddSearchPropertyRequest": ([pointer, ctypes.c_uint32], boolean),
        "Search": ([pointer, pointer], pointer),
        "GetResultListViewportCount": ([pointer], size),
        "GetResultListCount": ([pointer], size),
        "GetResultFullPathNameW": ([pointer, size, ctypes.c_wchar_p, size], size),
        "IsFolderResult": ([pointer, size], boolean),
        "DestroyClient": ([pointer], boolean),
        "DestroySearchState": ([pointer], boolean),
        "DestroyResultList": ([pointer], boolean),
    }
    for name, (arguments, result_type) in signatures.items():
        fn = getattr(sdk, "Everything3_" + name)
        fn.argtypes, fn.restype = arguments, result_type
    instances = [os.environ["MOA_EVERYTHING_INSTANCE"]] if "MOA_EVERYTHING_INSTANCE" in os.environ else ["", "1.5a"]
    client = None
    for instance in instances:
        client = sdk.Everything3_ConnectW(instance)
        if client:
            break
    if not client:
        raise OSError("Everything 1.5에 연결할 수 없습니다.")
    state, results = None, None
    try:
        state = sdk.Everything3_CreateSearchState()
        if not state:
            raise OSError("Everything 검색 상태를 만들 수 없습니다.")
        # Regex escapes make the user's filename a literal, not Everything syntax.
        expression = 'regex:"' + re.escape(query) + '"'
        # SDK 3.0.1.12 sets the count but always returns FALSE; read its value.
        sdk.Everything3_SetSearchViewportCount(state, LIMIT + 1)
        if not (sdk.Everything3_SetSearchTextW(state, expression)
                and sdk.Everything3_GetSearchViewportCount(state) == LIMIT + 1
                and sdk.Everything3_AddSearchPropertyRequest(state, 240)):
            raise OSError("Everything 검색을 설정할 수 없습니다.")
        results = sdk.Everything3_Search(client, state)
        if not results:
            raise OSError("Everything 검색 결과를 가져올 수 없습니다.")
        rows: list[SearchFile] = []
        buffer = ctypes.create_unicode_buffer(32768)
        for index in range(min(LIMIT, sdk.Everything3_GetResultListViewportCount(results))):
            length = sdk.Everything3_GetResultFullPathNameW(results, index, buffer, len(buffer))
            if not 0 < length < len(buffer):
                raise OSError("Everything 결과 경로를 읽을 수 없습니다.")
            p = Path(buffer.value)
            rows.append(SearchFile(name=p.name or str(p), path=str(p),
                                   isFolder=bool(sdk.Everything3_IsFolderResult(results, index))))
        return SearchResult(backend="Everything 1.5 SDK", results=rows, elapsed=0,
                    truncated=sdk.Everything3_GetResultListCount(results) > LIMIT,
                    note="Everything이 색인한 전체 위치에서 찾았습니다. 정리하려면 해당 폴더를 분석 위치에 추가하세요.")
    finally:
        if results:
            sdk.Everything3_DestroyResultList(results)
        if state:
            sdk.Everything3_DestroySearchState(state)
        sdk.Everything3_DestroyClient(client)


def drive_roots() -> list[str]:
    if os.name != "nt":
        return [os.path.abspath(os.sep)]
    kernel = ctypes.windll.kernel32
    mask = kernel.GetLogicalDrives()
    roots = [f"{chr(65+i)}:\\" for i in range(26) if mask & (1 << i)]
    return [root for root in roots if kernel.GetDriveTypeW(root) in (2, 3)]


def folder_search(query: str, roots: Sequence[str], stop: Callable[[], None]) -> SearchResult:
    """Bound disk work; never follow junctions or silently imply a global index."""
    start = perf_counter()
    pending = deque(Path(p).absolute() for p in roots)
    visited: set[str] = set()
    rows: list[SearchFile] = []
    examined, skipped, truncated = 0, 0, False
    needle = query.casefold()
    while pending:
        stop()
        folder = pending.popleft()
        key = os.path.normcase(str(folder))
        if key in visited:
            continue
        visited.add(key)
        try:
            info = folder.lstat()
            if folder.is_symlink() or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                skipped += 1
                continue
            with os.scandir(folder) as entries:
                for entry in entries:
                    stop()
                    examined += 1
                    if examined > ENTRY_LIMIT or perf_counter() - start > WALK_SECONDS:
                        truncated = True
                        break
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                            continue
                        is_folder = entry.is_dir(follow_symlinks=False)
                        if is_folder:
                            pending.append(Path(entry.path))
                        if needle in entry.name.casefold() and (is_folder or entry.is_file(follow_symlinks=False)):
                            rows.append(SearchFile(name=entry.name, path=entry.path, isFolder=is_folder))
                            if len(rows) > LIMIT:
                                truncated = True
                                break
                    except OSError:
                        skipped += 1
        except InterruptedError:
            raise
        except OSError:
            skipped += 1
        if truncated:
            break
    note = "Everything 연결 없이 폴더를 직접 검색했습니다. 검색 시작 위치: " + ", ".join(roots)
    if skipped:
        note += f" 읽을 수 없는 위치 {skipped}개를 건너뛰었습니다."
    if truncated:
        note += " 검색 범위 또는 결과 한도에 도달했습니다. 더 구체적인 이름으로 검색하세요."
    return SearchResult(backend="폴더 검색", results=sorted(rows[:LIMIT], key=lambda r: r["path"].casefold()),
                elapsed=round((perf_counter() - start) * 1000), truncated=truncated, note=note)


def search(query: str | None, roots: Sequence[str] | None = None, stop: Callable[[], None] = lambda: None) -> SearchResult:
    """Search filenames without moving files or expanding organization scope."""
    if not isinstance(query, str):
        raise InvalidQuery()
    query = query.strip()
    if not 1 <= len(query) <= 200 or re.search(r'[\\/:*?"<>|\x00-\x1f]', query):
        raise InvalidQuery()
    start = perf_counter()
    stop()
    result = None
    if os.name == "nt":
        try:
            with subprocess.Popen(
                [sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()), query],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW) as proc:
                try:
                    while perf_counter() - start < 5:
                        stop()
                        try:
                            output, _ = proc.communicate(timeout=0.08)
                        except subprocess.TimeoutExpired:
                            continue
                        if proc.returncode == 0:
                            result = json.loads(output)
                        break
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        proc.communicate()
        except InterruptedError:
            raise
        except (OSError, subprocess.SubprocessError, ValueError):
            # Missing SDK/client, incompatible instance or native IPC timeout.
            result = None
    stop()
    if result is None:
        result = folder_search(query, drive_roots() if roots is None else roots, stop)
    result["elapsed"] = round((perf_counter() - start) * 1000)
    return result


if __name__ == "__main__":
    try:
        print(json.dumps(sdk_search(sys.argv[1]), ensure_ascii=False))
    except (OSError, AttributeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
