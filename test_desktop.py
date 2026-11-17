from pathlib import Path
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
