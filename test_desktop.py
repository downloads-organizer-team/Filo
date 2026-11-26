from pathlib import Path
from itertools import count
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import storage
from desktop_service import Desktop


class DesktopTests(unittest.TestCase):
    def setUp(self):
        tmp = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.object(storage, "HOME", Path(tmp)))
        self.root = storage.sample()
        self.enterContext(patch.object(storage, "downloads_folder", return_value=self.root))
        self.app = Desktop()
        self.scan()

    def scan(self):
        self.data = self.app.run("scan", {"deep": True, "recursive": False})

    def call(self, action, **args):
        return self.app.run(action, dict(generation=self.data["generation"], **args))

    def test_scoped_move_then_undo_and_stale_plan(self):
        g = self.data["groups"][0]
        first = self.call("preview", kind="organize", group=g["id"])
        plan = self.call("preview", kind="organize", group=g["id"])
        rows = plan["rows"]
        self.assertEqual(len(rows), g["count"])
        original = {Path(r["source"]): Path(r["source"]).read_bytes() for r in rows}
        self.assertTrue(all(not Path(r["target"]).exists() for r in rows))
        with self.assertRaises(ValueError):
            self.call("execute", token=first["token"])
        self.call("execute", token=plan["token"])
        self.assertTrue(all(Path(r["target"]).is_file() for r in rows))
        self.scan()
        undo = self.call("preview", kind="undo")
        self.call("execute", token=undo["token"])
        self.assertEqual(original, {p: p.read_bytes() for p in original})
        self.assertFalse(any(Path(r["target"]).exists() for r in rows))

    def test_scan_reports_measured_stage_progress_in_each_mode(self):
        events=[]
        self.app.status=events.append
        with patch("scan_progress.monotonic",side_effect=count()):
            for mode in ("related","extension"):
                events.clear()
                self.app.run("scan",{"groupBy":mode})
                collected=[e for e in events if e["label"]=="파일 수집 중"]
                self.assertTrue(all(e["percent"] is None for e in collected))
                self.assertEqual(collected[-1]["files"],len(self.data["files"]))
                labels=["고유 파일과 사본 확인 중","정리 목록 준비 중"]
                labels+=["유사도 행렬 계산 중","계층 군집화 중"] if mode=="related" else ["확장자 확인 중"]
                for label in labels:
                    values=[e["percent"] for e in events if e["label"]==label and e["percent"] is not None]
                    self.assertEqual(values,sorted(set(values)),label)
                    self.assertEqual((values[0],values[-1]),(0,100),label)
                self.assertEqual(any(e["label"]=="유사도 행렬 계산 중" for e in events),mode=="related")

    def test_cancel_inside_large_hash_leaves_previous_review_intact(self):
        block=b"x"*(3*1024*1024)
        for name in ("큰 파일.bin","큰 파일 (1).bin"):
            (self.root/name).write_bytes(block)
        def cancel_during_read(event):
            if event["label"]=="고유 파일과 사본 확인 중" and 10<(event["percent"] or 0)<40:
                self.app.cancel.set()
        self.app.status=cancel_during_read
        with patch("scan_progress.monotonic",side_effect=count()),self.assertRaises(InterruptedError):
            self.app.run("scan",{})
        self.assertEqual(self.app.generation,self.data["generation"])

    def test_group_edit_and_pair_details(self):
        g = self.data["groups"][0]
        a, b, *_ = [f["id"] for f in self.data["files"] if f["group"] == g["id"]]
        self.assertEqual(self.call("matrix", start=a, col=b)[0][0], self.call("pair", a=a, b=b)["score"])
        self.assertTrue(self.call("detail", id=a)["path"])
        before = self.data["generation"]
        self.call("edit", kind="rename", group=g["id"], title="시연 그룹")
        self.scan()
        self.assertIn("시연 그룹", [item["title"] for item in self.data["groups"]])
        with self.assertRaises(ValueError):
            self.app.run("preview", dict(kind="organize", generation=before))
