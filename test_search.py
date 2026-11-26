from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
import json
import os
import subprocess
import sys
from threading import Timer
from time import perf_counter, sleep
import unittest
from unittest.mock import Mock, patch

import file_search
import search_engine


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(TemporaryDirectory()))
        self.extra=self.root/"Projects"
        self.downloads=self.root/"Downloads"

    def test_missing_sdk_never_returns_files_from_the_disk(self):
        (self.root/"available.txt").touch()
        with patch.dict(os.environ,MOA_EVERYTHING_DLL=str(self.root/"absent.dll")):
            with self.assertRaises(file_search.SdkMissing):
                file_search.search("available")

    def test_invalid_query_does_not_start_worker(self):
        with patch("file_search.SearchWorker") as worker:
            for query in (""," ","*","file:","a\x00b","x"*201,None):
                with self.subTest(query=query),self.assertRaises(file_search.InvalidQuery):
                    file_search.search(query)
            worker.assert_not_called()

    def test_connection_is_reused_and_index_readiness_is_checked(self):
        with patch.dict(os.environ,MOA_EVERYTHING_INSTANCE="test"),patch("file_search.load_sdk") as load,patch("file_search.query_client") as query:
            sdk=load.return_value
            sdk.Everything3_IsDBLoaded.side_effect=[False,True,True]
            client=file_search.SdkClient()
            with self.assertRaises(file_search.EverythingUnavailable):
                client.search("pending")
            query.assert_not_called()
            client.search("first")
            client.search("second")
            self.assertEqual(sdk.Everything3_ConnectW.call_count,2)
            self.assertEqual(query.call_count,2)
            client.close()

    def test_prefers_ready_existing_index_and_skips_unready_index(self):
        for ready in (True,False):
            with self.subTest(ready=ready),patch.dict(os.environ),patch("file_search.load_sdk") as load:
                os.environ.pop("MOA_EVERYTHING_INSTANCE",None)
                os.environ.pop("MOA_SEARCH_ROOTS",None)
                sdk=load.return_value
                sdk.Everything3_ConnectW.side_effect=[101,None,202]
                sdk.Everything3_IsDBLoaded.return_value=ready
                client=file_search.SdkClient()
                client.connect()
                self.assertEqual(client.client,101 if ready else 202)
                self.assertEqual(sdk.Everything3_ConnectW.call_count,1 if ready else 3)
                if not ready:sdk.Everything3_DestroyClient.assert_called_once_with(101)
                client.close()

    def test_early_search_finds_literal_names_and_respects_roots_and_cancel(self):
        self.extra.mkdir()
        self.downloads.mkdir()
        nested=self.extra/"한글 폴더"
        nested.mkdir()
        expected=nested/"제안 [12].txt"
        for path in (expected,self.downloads/expected.name,nested/"제안 2.txt"):path.touch()
        with patch.dict(os.environ,MOA_DOWNLOADS=str(self.downloads),MOA_SEARCH_ROOTS=str(self.extra)):
            result=file_search.quick_search("[12]",lambda:None)
            self.assertTrue(result["partial"])
            self.assertEqual([Path(r["path"]) for r in result["results"]],[expected])
            self.assertTrue(file_search.quick_search("한글",lambda:None)["results"][0]["isFolder"])
            with self.assertRaises(InterruptedError):
                file_search.quick_search("[12]",Mock(side_effect=InterruptedError))

    def test_missing_bundled_engine_reports_reinstall(self):
        with patch.dict(os.environ), patch.object(search_engine, "ENGINE", self.root / "absent.exe"):
            os.environ.pop("MOA_EVERYTHING_INSTANCE", None)
            worker = file_search.SearchWorker()
            worker.process = Mock()
            worker.replies.put(("offline", "waiting"))
            with self.assertRaisesRegex(FileNotFoundError, "다시 설치"):
                worker.request(None)

    def test_explicit_instance_is_externally_managed(self):
        with patch.dict(os.environ,MOA_EVERYTHING_INSTANCE="test-instance"),patch("file_search.BundledEngine") as engine:
            worker=file_search.SearchWorker()
            worker.process=Mock()
            worker.replies.put(("offline","waiting"))
            with self.assertRaises(file_search.EverythingUnavailable):worker.request(None)
            engine.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows x64 integration")
    def test_bundled_engine_finds_korean_names_and_reopens_its_index(self):
        self.extra.mkdir()
        self.downloads.mkdir()
        other = self.root / "두 번째 폴더"
        other.mkdir()
        stem = "색인 확인 [42]"
        sample = self.extra / (stem + ".txt")
        folder = other / (stem + ".folder")
        sample.touch()
        folder.mkdir()
        (self.downloads / (stem + ".outside")).touch()
        state = self.root / "state"
        roots = os.pathsep.join(map(str, (self.extra, other)))
        def await_results(worker, expected):
            deadline = perf_counter() + 20
            while perf_counter() < deadline:
                try:
                    result = worker.request(stem)
                    found = {Path(r["path"]): r["isFolder"] for r in result["results"]}
                    if found == expected and result["total"] == len(expected):
                        self.assertEqual(result["backend"], "내장 Everything")
                        return
                except file_search.EverythingUnavailable:
                    pass
                sleep(.12)
            self.fail("내장 검색 색인이 테스트 파일의 현재 상태와 일치하지 않습니다.")

        with patch.dict(os.environ, MOA_SEARCH_ROOTS=roots, MOA_HOME=str(state)), \
                patch.object(search_engine.storage, "HOME", state):
            os.environ.pop("MOA_EVERYTHING_INSTANCE", None)
            expected = {sample: False, folder: True}
            for run in range(2):
                worker = file_search.SearchWorker()
                try:
                    await_results(worker, expected)
                    if run == 0:
                        new_file = other / (stem + ".새파일")
                        new_file.touch()
                        await_results(worker, {**expected, new_file: False})
                        new_file.unlink()
                        await_results(worker, expected)
                        # A subsequent query reopens a crashed private indexer.
                        worker.engine.process.kill()
                        worker.engine.process.wait()
                        await_results(worker, expected)
                    process = worker.engine.process
                    self.assertIsNone(process.poll())
                finally:
                    worker.close()
                self.assertIsNotNone(process.poll())
                self.assertGreater((state / "Search" / "Everything.db").stat().st_size, 0)
                if run == 0:
                    renamed = sample.rename(self.extra / (stem + ".바뀐이름"))
                    expected = {renamed: False, folder: True}

    def test_cancelled_search_does_not_start_process(self):
        worker=file_search.SearchWorker()
        def cancelled():raise InterruptedError("cancel")
        with self.assertRaises(InterruptedError):
            worker.request("trip",cancelled)
        self.assertIsNone(worker.process)

    def test_sdk_keeps_index_total_and_deduplicates_only_identical_paths(self):
        paths=[str(self.extra/"same.txt"),str(self.extra/"same.txt"),str(self.downloads/"same.txt")]
        def full_path(results,index,buffer,size):
            buffer.value=paths[index]
            return len(buffer.value)
        with patch.object(file_search.ctypes,"WinDLL",create=True) as load:
            sdk=load.return_value
            sdk.Everything3_GetSearchViewportCount.return_value=file_search.LIMIT+1
            sdk.Everything3_GetResultListViewportCount.return_value=len(paths)
            sdk.Everything3_GetResultListCount.return_value=len(paths)
            sdk.Everything3_GetResultFullPathNameW.side_effect=full_path
            sdk.Everything3_IsFolderResult.return_value=0
            result=file_search.sdk_search("same")
            self.assertFalse(result["truncated"])
            self.assertEqual(result["total"],3)
            self.assertEqual([row["path"] for row in result["results"]],[paths[0],paths[2]])
            sdk.Everything3_GetResultListCount.return_value=410
            capped=file_search.sdk_search("same")
            self.assertTrue(capped["truncated"])
            self.assertEqual(capped["total"],410)

def verify_live_sdk(query,expected):
    """Query an isolated real index through the same stdin protocol as Electron."""
    with TemporaryDirectory(prefix="moa-sdk-") as temporary:
        environment=dict(os.environ,MOA_HOME=temporary,MOA_DOWNLOADS=temporary)
        with subprocess.Popen(
            [sys.executable,"-B","-X","utf8","-u",str(Path(__file__).with_name("desktop_service.py"))],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,encoding="utf-8",env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0,
        ) as service:
            assert service.stdin is not None and service.stdout is not None
            deadline=Timer(25,service.kill)
            deadline.start()
            try:
                started=perf_counter()
                attempts=0
                while True:
                    attempts+=1
                    service.stdin.write(json.dumps(dict(id=attempts,action="search",args=dict(query=query)))+"\n")
                    service.stdin.flush()
                    # Keep stdin open, exactly as Electron does while awaiting a reply.
                    response=json.loads(service.stdout.readline())
                    if response["ok"] and not response["value"].get("partial"):break
                    assert (response["ok"] or response.get("code")=="everythingUnavailable") and perf_counter()-started<20,response
                    sleep(.25)
                result=response["value"]
                expected_backend = "Everything 1.5 SDK" if "MOA_EVERYTHING_INSTANCE" in environment else "내장 Everything"
                assert result["backend"] == expected_backend,result
                assert result["total"]>=len(result["results"])
                assert len({r["path"] for r in result["results"]})==len(result["results"])
                matches=[Path(r["path"]) for r in result["results"] if r["name"].casefold()==query.casefold()]
                assert expected in matches and expected.is_file(),result
                print(json.dumps(dict(scenario="isolated search through desktop IPC",
                                      backend=result["backend"],attempts=attempts,elapsed_ms=result["elapsed"],
                                      total_ms=round((perf_counter()-started)*1000),passed=True)))
            finally:
                service.stdin.close()
                try:service.wait(timeout=3)
                except subprocess.TimeoutExpired:service.kill();service.wait()
                deadline.cancel()


@contextmanager
def isolated_instance(executable,base,inbox,name):
    ini=base/"Everything.ini"
    ini.write_text("[Everything]\nrun_as_admin=0\nshow_in_tray=0\n",encoding="utf-8")
    proc=subprocess.Popen([str(executable),"-instance",name,"-config",str(ini),"-no-db","-no-auto-index",
                           "-folders",str(inbox),"-startup"],cwd=base)
    try:
        yield
    finally:
        if proc.poll() is None:
            try:
                subprocess.run([str(executable),"-instance",name,"-exit"],timeout=5,check=True)
                proc.wait(timeout=5)
            except (subprocess.TimeoutExpired,subprocess.CalledProcessError):
                proc.terminate()
                proc.wait(timeout=5)


def verify_bundled_sdk():
    with TemporaryDirectory(prefix="organizer-search-") as temporary:
        inbox = Path(temporary) / "받은 파일"
        inbox.mkdir()
        sample = inbox / "검색 확인 [42].txt"
        sample.touch()
        with patch.dict(os.environ, MOA_SEARCH_ROOTS=str(inbox)):
            os.environ.pop("MOA_EVERYTHING_INSTANCE", None)
            verify_live_sdk(sample.name, sample)


def verify_isolated_sdk(executable):
    with TemporaryDirectory(prefix="organizer-sdk-") as temporary:
        base=Path(temporary)
        inbox=base/"Inbox"
        inbox.mkdir()
        sample=inbox/"색인 확인 [42].txt"
        sample.touch()
        folder=inbox/"색인 확인 [42].folder"
        folder.mkdir()
        stem="색인 확인 [42]"
        (inbox/"색인 확인 4.txt").touch()
        with patch.dict(os.environ,MOA_EVERYTHING_INSTANCE=base.name),isolated_instance(executable,base,inbox,base.name):
            worker=file_search.SearchWorker()
            try:
                deadline=perf_counter()+15
                while perf_counter()<deadline:
                    try:
                        result=worker.request(stem)
                        if result["total"]==2:break
                    except file_search.EverythingUnavailable:
                        pass
                    sleep(.15)
                else:raise AssertionError("The temporary items were not indexed")
                for _ in range(3):
                    result=worker.request(stem)
                    assert {Path(r["path"]):r["isFolder"] for r in result["results"]}=={sample:False,folder:True}
                    print("Warm SDK query (ms):",result["elapsed"])
                verify_live_sdk(sample.name,sample)
            finally:
                worker.close()


if __name__=="__main__":
    if sys.argv[1:]==["--sdk"]:verify_bundled_sdk()
    elif len(sys.argv)==3 and sys.argv[1]=="--sdk":verify_isolated_sdk(sys.argv[2])
    else:unittest.main()
