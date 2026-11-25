"""Live literal filename queries against the Everything 1.5 index."""
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
from time import perf_counter
from typing import TypedDict

LIMIT = 200
CONNECT_MESSAGE = "Everything 1.5 연결을 기다리고 있습니다. 설치된 Everything이 실행 중인지 확인하세요."


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


def installed_everything():
    """Look up a registered 1.5 installation without searching any drives."""
    if os.name != "nt":
        return None
    import winreg
    uninstall = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for hive in (winreg.HKEY_LOCAL_MACHINE,winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_64KEY,winreg.KEY_WOW64_32KEY):
            for key in ("Everything","Everything 1.5a"):
                try:
                    with winreg.OpenKey(hive,uninstall+"\\"+key,0,winreg.KEY_READ|view) as entry:
                        version=winreg.QueryValueEx(entry,"DisplayVersion")[0]
                        folder=Path(winreg.QueryValueEx(entry,"InstallLocation")[0])
                    if not str(version).startswith("1.5.") or not folder.is_absolute():
                        continue
                    for name in ("Everything.exe","Everything64.exe","Everything32.exe"):
                        if (folder/name).is_file():
                            return folder/name
                except OSError:
                    continue
    return None


class SdkClient:
    def __init__(self):
        self.sdk=None
        self.client=None

    def connect(self):
        if self.client:
            return
        if self.sdk is None:
            try:
                self.sdk=load_sdk()
            except (OSError,AttributeError) as exc:
                raise SdkMissing("Everything 검색 SDK를 불러올 수 없습니다. 앱의 vendor 폴더와 x64 DLL을 확인하세요.") from exc
        instances=[os.environ["MOA_EVERYTHING_INSTANCE"]] if "MOA_EVERYTHING_INSTANCE" in os.environ else ["","1.5a"]
        for instance in instances:
            self.client=self.sdk.Everything3_ConnectW(instance)
            if self.client:
                return
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
            raise IndexLoading("Everything 색인을 준비하고 있습니다. 준비되면 자동으로 검색합니다.")
        try:
            return query_client(self.sdk,self.client,query)
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
        self.launch_attempted=False

    def close(self):
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
            self.close()
            if isinstance(exc,InterruptedError):
                raise
            raise EverythingUnavailable(CONNECT_MESSAGE) from exc
        if status=="missing":
            raise SdkMissing(value)
        if status=="loading":
            raise IndexLoading(value)
        if status=="offline":
            if not self.launch_attempted and "MOA_EVERYTHING_INSTANCE" not in os.environ:
                self.launch_attempted=True
                if exe:=installed_everything():
                    try:
                        subprocess.Popen([str(exe),"-startup"],cwd=exe.parent,stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    except OSError:
                        pass
            raise EverythingUnavailable(value)
        stop()
        if value is not None:
            value["elapsed"]=round((perf_counter()-start)*1000)
        return value


def search(query: str | None) -> SearchResult:
    query=validate_query(query)
    worker=SearchWorker()
    try:
        return worker.request(query)
    finally:
        worker.close()


if __name__=="__main__":
    if sys.argv[1:]==["--worker"]:
        serve_sdk()
        sys.exit(0)
    try:
        print(json.dumps(sdk_search(sys.argv[1]),ensure_ascii=False))
    except OSError as error:
        print(str(error),file=sys.stderr)
        sys.exit(1)
