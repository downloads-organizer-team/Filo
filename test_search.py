from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import subprocess
import sys
from threading import Timer
from time import perf_counter
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
        self.assertEqual(result["results"], [{"name": target.name, "path": str(target)}])
        self.assertEqual(result["backend"], "폴더 검색")
        self.assertFalse(result["truncated"])

    def test_search_reads_current_disk_state(self):
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
        self.assertTrue(all(Path(row["path"]).is_file() for row in result["results"]))

    def test_cancellation_propagates(self):
        def cancelled():
            raise InterruptedError("cancel")
        with self.assertRaises(InterruptedError):
            file_search.search("trip", [str(self.extra)], cancelled)


def verify_live_sdk():
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
                service.stdin.write(json.dumps(dict(id=1,action="search",args=dict(query="Everything.exe")))+"\n")
                service.stdin.flush()
                # Keep stdin open, exactly as Electron does while awaiting a reply.
                response=json.loads(service.stdout.readline())
                assert response["ok"],response
                result=response["value"]
                assert result["backend"]=="Everything 1.5 SDK",result
                assert any(Path(r["path"]).is_file() and r["name"].casefold()=="everything.exe"
                           for r in result["results"]),result
                print(json.dumps(dict(scenario="live SDK through open-stdin desktop IPC",
                                      backend=result["backend"],elapsed_ms=result["elapsed"],
                                      total_ms=round((perf_counter()-started)*1000),passed=True)))
            finally:
                service.stdin.close()
                try:service.wait(timeout=3)
                except subprocess.TimeoutExpired:service.kill();service.wait()
                deadline.cancel()


if __name__=="__main__":
    if sys.argv[1:]==["--sdk"]:verify_live_sdk()
    else:unittest.main()
