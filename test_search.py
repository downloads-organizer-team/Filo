from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import subprocess
import sys
from threading import Timer
from time import perf_counter, sleep
import unittest
from unittest.mock import patch

import file_search


class SearchTests(unittest.TestCase):
    root=Path()
    downloads=Path()
    extra=Path()
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.downloads = self.root / "Downloads"
        self.extra = self.root / "Projects"
        self.downloads.mkdir()
        self.extra.mkdir()
        self.enterContext(patch.dict("os.environ", {"MOA_EVERYTHING_DLL": str(self.root / "absent.dll")}))

    def test_fallback_finds_literal_filename_across_roots_and_overlaps(self):
        nested = self.extra / "Nested"
        nested.mkdir()
        target = nested / "Jeju[2026].pdf"
        target.write_text("ticket")
        (self.downloads / "Jeju2026.pdf").write_text("different name")
        result = file_search.search("jeju[2026]", [str(self.downloads), str(self.extra), str(nested)])
        self.assertEqual(result["results"], [{"name": target.name, "path": str(target), "isFolder":False}])
        self.assertEqual(result["backend"], "폴더 검색")
        self.assertEqual(result["total"], 1)
        self.assertFalse(result["truncated"])

    def test_search_reads_current_disk_state(self):
        folder = self.extra / "directory.with.dots"
        folder.mkdir()
        self.assertEqual(file_search.search("with.dots", [str(self.extra)])["results"],
                         [dict(name=folder.name,path=str(folder),isFolder=True)])
        target = self.extra / "trip.md"
        target.write_text("plan")
        target.rename(self.extra / "finished.md")
        self.assertEqual(file_search.search("trip", [str(self.extra)])["results"], [])
        result = file_search.search("finished", [str(self.extra)])
        self.assertEqual([r["path"] for r in result["results"]], [str(self.extra / "finished.md")])

    def test_invalid_input_does_not_expand_to_every_file(self):
        for query in ("", " ", "*", "file:", "a\x00b", "x" * 201, None):
            with self.subTest(query=query), self.assertRaises(file_search.InvalidQuery):
                file_search.search(query, [str(self.extra)])

    def test_result_limit_is_reported_and_missing_root_is_not_fatal(self):
        for i in range(4):
            (self.extra / f"receipt-{i}.txt").touch()
        with patch.object(file_search, "LIMIT", 2):
            result = file_search.search("receipt", [str(self.root / "missing"), str(self.extra)])
        self.assertEqual(len(result["results"]), 2)
        self.assertTrue(result["truncated"])
        self.assertIsNone(result["total"])
        self.assertTrue(all(Path(row["path"]).is_file() for row in result["results"]))

    def test_incomplete_empty_search_does_not_claim_zero_total(self):
        with patch.object(file_search,"ENTRY_LIMIT",0):
            (self.extra/"unrelated.txt").touch()
            limited=file_search.folder_search("missing",[str(self.extra)],lambda:None)
        skipped=file_search.folder_search("missing",[str(self.root/"unavailable")],lambda:None)
        for result in (limited,skipped):
            self.assertEqual(result["results"],[])
            self.assertIsNone(result["total"])
        complete=file_search.folder_search("missing",[str(self.extra)],lambda:None)
        self.assertEqual(complete["total"],0)

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

    def test_cancellation_propagates(self):
        def cancelled():
            raise InterruptedError("cancel")
        with self.assertRaises(InterruptedError):
            file_search.search("trip", [str(self.extra)], cancelled)

        (self.extra/"last.txt").touch()
        checks=iter([False,True])
        def cancel_during_directory_read():
            if next(checks):raise InterruptedError("cancel")
        with self.assertRaises(InterruptedError):
            file_search.folder_search("trip",[str(self.extra)],cancel_during_directory_read)


def verify_live_sdk(query="Everything.exe",expected=None):
    """Opt-in real IPC proof: python -B -X utf8 test_search.py --sdk."""
    with TemporaryDirectory(prefix="moa-sdk-") as temporary:
        environment=dict(os.environ,MOA_HOME=temporary,MOA_DOWNLOADS=temporary)
        with subprocess.Popen(
            [sys.executable,"-B","-X","utf8","-u",str(Path(__file__).with_name("desktop_service.py"))],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,encoding="utf-8",env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0,
        ) as service:
            assert service.stdin is not None and service.stdout is not None
            deadline=Timer(10,service.kill)
            deadline.start()
            try:
                started=perf_counter()
                service.stdin.write(json.dumps(dict(id=1,action="search",args=dict(query=query)))+"\n")
                service.stdin.flush()
                # Keep stdin open, exactly as Electron does while awaiting a reply.
                response=json.loads(service.stdout.readline())
                assert response["ok"],response
                result=response["value"]
                assert result["backend"]=="Everything 1.5 SDK",result
                assert result["total"]>=len(result["results"])
                assert len({r["path"] for r in result["results"]})==len(result["results"])
                matches=[Path(r["path"]) for r in result["results"] if r["name"].casefold()==query.casefold()]
                assert any(p.is_file() and (expected is None or p==expected) for p in matches),result
                print(json.dumps(dict(scenario="live SDK through open-stdin desktop IPC",
                                      backend=result["backend"],elapsed_ms=result["elapsed"],
                                      total_ms=round((perf_counter()-started)*1000),passed=True)))
            finally:
                service.stdin.close()
                try:service.wait(timeout=3)
                except subprocess.TimeoutExpired:service.kill();service.wait()
                deadline.cancel()


def verify_isolated_sdk(executable):
    with TemporaryDirectory(prefix="organizer-sdk-") as temporary:
        base=Path(temporary)
        inbox=base/"Inbox"
        inbox.mkdir()
        sample=inbox/"색인 확인 [42].txt"
        sample.touch()
        name=base.name
        ini=base/"Everything.ini"
        ini.write_text("[Everything]\nrun_as_admin=0\nshow_in_tray=0\n",encoding="utf-8")
        proc=subprocess.Popen([executable,"-instance",name,"-config",str(ini),"-no-db",
                               "-volumes","","-folders",str(inbox),"-startup"],cwd=base)
        try:
            with patch.dict(os.environ,MOA_EVERYTHING_INSTANCE=name):
                deadline=perf_counter()+15
                while perf_counter()<deadline:
                    result=file_search.search(sample.name,roots=[])
                    if result["backend"]=="Everything 1.5 SDK" and result["results"]:
                        break
                    sleep(.2)
                else:
                    raise AssertionError("The isolated Everything instance did not index the test file")
                verify_live_sdk(sample.name,sample)
        finally:
            if proc.poll() is None:
                try:
                    subprocess.run([executable,"-instance",name,"-exit"],timeout=5,check=True)
                    proc.wait(timeout=5)
                except (subprocess.TimeoutExpired,subprocess.CalledProcessError):
                    proc.terminate()
                    proc.wait(timeout=5)


if __name__=="__main__":
    if sys.argv[1:]==["--sdk"]:verify_live_sdk()
    elif len(sys.argv)==3 and sys.argv[1]=="--sdk":verify_isolated_sdk(sys.argv[2])
    else:unittest.main()
