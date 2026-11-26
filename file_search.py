"""Live literal filename queries against the Everything 1.5 index."""
from collections import deque
from collections.abc import Callable
import ctypes
import json
from queue import Empty, Queue
from threading import Thread
import os
from pathlib import Path
import re
import subprocess
import sys
from time import perf_counter, sleep
from typing import NotRequired, TypedDict

import storage
from search_engine import BundledEngine, index_roots, private_instance

LIMIT = 200
CONNECT_MESSAGE = "검색 엔진을 시작하고 있습니다. 준비되면 자동으로 검색합니다."


class SearchFile(TypedDict):
    name: str
    path: str
    isFolder: bool


class SearchResult(TypedDict):
    backend: str
    results: list[SearchFile]
    total: int
    elapsed: int
    truncated: bool
    note: str
    partial: NotRequired[bool]


class InvalidQuery(ValueError):
    def __str__(self) -> str:
        return "파일 이름 일부를 1~200자로 입력하세요. 경로와 검색 연산자는 사용할 수 없습니다."


class EverythingUnavailable(OSError):
    pass


class SdkMissing(OSError):
    pass


class IndexLoading(EverythingUnavailable):
    pass


def validate_query(query):
    if not isinstance(query, str):
        raise InvalidQuery()
    query = query.strip()
    if not 1 <= len(query) <= 200 or re.search(r'[\\/:*?"<>|\x00-\x1f]', query):
        raise InvalidQuery()
    return query


def quick_search(query, stop):
    """Show nearby names while Everything builds its first full index."""
    started = perf_counter()
    scope = list(map(Path, index_roots()))
    candidates = [storage.downloads_folder(), *map(Path, storage.source_roots()),
                  Path.home() / "Desktop", Path.home() / "Documents"]
    if "MOA_SEARCH_ROOTS" in os.environ:
        candidates.extend(scope)
    roots = list(dict.fromkeys(p for p in candidates if any(p.is_relative_to(drive) for drive in scope)))
    pending = deque((p, 0) for p in roots)
    visited = set(roots)
    needle = query.casefold()
    rows = []
    total = examined = 0
    # A short breadth-first pass prioritizes all root folders over descendants.
    # The full index handles deep paths and large directories on completion.
    deadline = perf_counter() + .15
    while pending and perf_counter() < deadline and examined < 12000:
        stop()
        directory, depth = pending.popleft()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if examined % 32 == 0:
                        stop()
                        if perf_counter() >= deadline or examined >= 12000:
                            break
                    examined += 1
                    folder = entry.is_dir(follow_symlinks=False)
                    if needle in entry.name.casefold():
                        total += 1
                        if len(rows) < LIMIT:
                            rows.append(SearchFile(name=entry.name,path=entry.path,isFolder=folder))
                    if folder and depth < 2 and not entry.is_junction():
                        child = Path(entry.path)
                        if child not in visited:
                            visited.add(child)
                            pending.append((child, depth + 1))
        except InterruptedError:
            raise
        except OSError:
            continue
    return SearchResult(backend="자주 쓰는 폴더", results=rows, total=total,
                        elapsed=round((perf_counter()-started)*1000), truncated=total>LIMIT,
                        partial=True, note="전체 드라이브 색인 중")


def load_sdk():
    dll_path = Path(os.environ.get(
        "MOA_EVERYTHING_DLL", str(Path(__file__).parent / "vendor" / "Everything3_x64.dll")))
    sdk = ctypes.WinDLL(str(dll_path.resolve()))
    pointer, size, boolean = ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int
    signatures = {
        "ConnectW": ([ctypes.c_wchar_p], pointer),
        "IsDBLoaded": ([pointer], boolean),
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
    return sdk


def query_client(sdk,client,query):
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
        seen_paths: set[str] = set()
        buffer = ctypes.create_unicode_buffer(32768)
        viewport = sdk.Everything3_GetResultListViewportCount(results)
        for index in range(viewport):
            length = sdk.Everything3_GetResultFullPathNameW(results, index, buffer, len(buffer))
            if not 0 < length < len(buffer):
                raise OSError("Everything 결과 경로를 읽을 수 없습니다.")
            p = Path(buffer.value)
            full_path = str(p)
            if full_path in seen_paths:
                continue
            seen_paths.add(full_path)
            rows.append(SearchFile(name=p.name or full_path, path=full_path,
                                   isFolder=bool(sdk.Everything3_IsFolderResult(results, index))))
        total = sdk.Everything3_GetResultListCount(results)
        # The SDK total counts index entries, including overlapping index sources.
        return SearchResult(backend="Everything 1.5 SDK", results=rows[:LIMIT], total=total, elapsed=0,
                    truncated=total > viewport or len(rows) > LIMIT,
                    note="")
    finally:
        if results:
            sdk.Everything3_DestroyResultList(results)
        if state:
            sdk.Everything3_DestroySearchState(state)


class SdkClient:
    def __init__(self):
        self.sdk=None
        self.client=None
        self.backend="Everything 1.5 SDK"

    def connect(self):
        if self.client:
            return
        if self.sdk is None:
            try:
                self.sdk=load_sdk()
            except (OSError,AttributeError) as exc:
                raise SdkMissing("Everything 검색 SDK를 불러올 수 없습니다. 앱의 vendor 폴더와 x64 DLL을 확인하세요.") from exc
        instance = os.environ.get("MOA_EVERYTHING_INSTANCE")
        if instance is None and "MOA_SEARCH_ROOTS" not in os.environ:
            for name in ("", "1.5a"):
                client = self.sdk.Everything3_ConnectW(name)
                if client:
                    if self.sdk.Everything3_IsDBLoaded(client):
                        self.client = client
                        self.backend = "Everything 1.5 SDK"
                        return
                    self.sdk.Everything3_DestroyClient(client)
        self.client = self.sdk.Everything3_ConnectW(private_instance() if instance is None else instance)
        self.backend = "내장 Everything" if instance is None else "Everything 1.5 SDK"
        if not self.client:
            raise EverythingUnavailable(CONNECT_MESSAGE)

    def close(self):
        if self.client:
            self.sdk.Everything3_DestroyClient(self.client)
            self.client=None

    def search(self,query):
        query=validate_query(query)
        self.connect()
        if not self.sdk.Everything3_IsDBLoaded(self.client):
            self.close()
            raise IndexLoading("파일 이름 색인을 준비하고 있습니다. 첫 실행에는 시간이 걸릴 수 있습니다.")
        try:
            result = query_client(self.sdk,self.client,query)
            result["backend"] = self.backend
            return result
        except OSError as exc:
            self.close()
            raise EverythingUnavailable(CONNECT_MESSAGE) from exc


def sdk_search(query):
    client=SdkClient()
    try:
        return client.search(query)
    finally:
        client.close()


def serve_sdk():
    client=SdkClient()
    try:
        for line in sys.stdin:
            query=json.loads(line)
            try:
                value=client.search(query) if query is not None else client.connect()
                reply=("ok",value)
            except SdkMissing as exc:
                reply=("missing",str(exc))
            except IndexLoading as exc:
                reply=("loading",str(exc))
            except EverythingUnavailable as exc:
                reply=("offline",str(exc))
            print(json.dumps(reply,ensure_ascii=False),flush=True)
    finally:
        client.close()


def read_replies(stream,replies):
    try:
        with stream:
            for line in stream:
                replies.put(json.loads(line))
    finally:
        replies.put(None)


class SearchWorker:
    """One reusable native client, with bounded calls and a separate crash boundary."""
    def __init__(self):
        self.process=None
        self.replies=Queue()
        self.engine = None if "MOA_EVERYTHING_INSTANCE" in os.environ else BundledEngine()

    def close_client(self):
        if self.process:
            try:
                self.process.stdin.close()
            except BrokenPipeError:
                pass
            try:
                self.process.wait(timeout=.1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process=None

    def close(self):
        self.close_client()
        if self.engine is not None:
            self.engine.close()

    def request(self,query,stop: Callable[[],None]=lambda:None):
        stop()
        if query is not None:
            query=validate_query(query)
        start=perf_counter()
        if self.process is None:
            self.process=subprocess.Popen(
                [sys.executable,"-B","-X","utf8","-u",str(Path(__file__).resolve()),"--worker"],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                text=True,encoding="utf-8",creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            self.replies=Queue()
            Thread(target=read_replies,args=(self.process.stdout,self.replies),daemon=True).start()
        try:
            self.process.stdin.write(json.dumps(query)+"\n")
            self.process.stdin.flush()
            while True:
                try:
                    reply=self.replies.get(timeout=.04)
                    break
                except Empty:
                    stop()
                    if perf_counter()-start>=5:
                        raise TimeoutError()
            if reply is None:
                raise EOFError()
            status,value=reply
        except (OSError,EOFError) as exc:
            self.close_client()
            if isinstance(exc,InterruptedError):
                raise
            raise EverythingUnavailable(CONNECT_MESSAGE) from exc
        if status=="missing":
            raise SdkMissing(value)
        if status=="loading":
            raise IndexLoading(value)
        if status=="offline":
            if self.engine is not None:
                self.engine.start()
            raise EverythingUnavailable(value)
        stop()
        if value is not None:
            value["elapsed"]=round((perf_counter()-start)*1000)
        return value


def search(query: str | None) -> SearchResult:
    query=validate_query(query)
    worker=SearchWorker()
    try:
        deadline = perf_counter() + 20
        while True:
            try:
                return worker.request(query)
            except EverythingUnavailable:
                if perf_counter() >= deadline:
                    raise
                sleep(.2)
    finally:
        worker.close()


if __name__=="__main__":
    if sys.argv[1:]==["--worker"]:
        serve_sdk()
        sys.exit(0)
    try:
        print(json.dumps(search(sys.argv[1]),ensure_ascii=False))
    except OSError as error:
        print(str(error),file=sys.stderr)
        sys.exit(1)
