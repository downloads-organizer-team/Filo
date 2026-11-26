import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from desktop_service import Desktop
import eligibility
import storage
import entry_names


class ReviewTests(unittest.TestCase):
    def setUp(self):
        base = Path(self.enterContext(TemporaryDirectory()))
        self.inbox = base / "Inbox"
        self.inbox.mkdir()
        self.enterContext(patch.object(storage,"HOME",base/"State"))
        self.enterContext(patch.object(storage,"downloads_folder",return_value=self.inbox))
        self.app = Desktop()

    def project(self,title="달빛정원"):
        paths = [self.inbox / (title+"_"+name) for name in ("견적.xlsx","시안.png","일정.pdf")]
        for path in paths:
            path.write_bytes(path.name.encode())
        return paths

    def scan(self,**kw):
        return self.app.scan(dict(deep=False,covers=False,folderMode="new",**kw))

    def move(self):
        self.scan()
        return self.app.execute(self.app.preview({}))

    def test_representative_stays_stable_across_roots(self):
        originals=self.project()
        extra=self.inbox.parent/"Extra"
        extra.mkdir()
        copies=[extra/"달빛정원_견적 (1).xlsx",extra/"달빛정원_견적 (2).xlsx"]
        for copy in copies:
            copy.write_bytes(originals[0].read_bytes())
        for roots in ([extra,self.inbox],[self.inbox,extra]):
            result=self.scan(roots=list(map(str,roots)))
            self.assertEqual({r["path"] for r in result["files"] if r["group"]},set(map(str,originals)))
            self.assertTrue(all("사본" in r["note"] for r in result["files"] if not r["group"]))
        self.app.execute(self.app.preview({}))
        self.assertTrue(all(p.is_file() for p in copies))
        self.assertTrue(all(not p.exists() for p in originals))

    def test_numbered_names_do_not_establish_content_identity(self):
        paths=[self.inbox/n for n in ("A.exe","A (1).exe","A (2).exe")]
        for p in paths:p.write_bytes(b"A")
        self.assertEqual(self.scan()["groups"],[])
        self.assertEqual(sum(bool(f.hold_reason) for f in self.app.study.files),2)
        self.assertEqual(self.app.preview({})["rows"],[])
        for i,p in enumerate(paths):p.write_bytes(bytes([i]))
        self.scan()
        self.assertFalse(any(f.hold_reason for f in self.app.study.files))

    def test_unreadable_same_size_cannot_complete_group(self):
        paths=self.project()
        for i,p in enumerate(paths):p.write_bytes(bytes([i]))
        digest=eligibility.checksum
        def read(path):
            if path==paths[-1]:raise PermissionError("잠긴 파일")
            return digest(path)
        with patch.object(eligibility,"checksum",side_effect=read):
            result=self.scan()
        self.assertFalse(result["groups"])
        self.assertTrue(any("내용 확인 보류" in f["note"] for f in result["files"]))

    def test_generic_triples_and_colliding_targets_stay_unclassified(self):
        for name in ("무제.txt","무제 (1).txt","무제 (2).txt","ab2c435e.pdf","ab2c435f.pdf","ab2c435a.pdf"):
            (self.inbox/name).write_bytes(name.encode())
        self.assertEqual(self.scan()["groups"],[])
        roots=[self.inbox.parent/f"Root{i}" for i in range(3)]
        for i,root in enumerate(roots):
            root.mkdir()
            (root/"달빛정원_시안.pdf").write_bytes(bytes([i]))
        self.assertEqual(self.scan(roots=list(map(str,roots)))["groups"],[])

    def test_selected_subset_and_change_after_confirmation(self):
        paths=self.project()
        self.scan()
        subset=dict(files=[0,1])
        self.assertTrue(all("3개" in r["skip"] for r in self.app.review(subset)))
        self.assertTrue(all("3개" in r["skip"] for r in self.app.preview(subset)["rows"]))
        plan=self.app.preview({})
        info=paths[0].stat()
        paths[0].write_bytes(b"X"*info.st_size)
        os.utime(paths[0],ns=(info.st_atime_ns,info.st_mtime_ns))
        report=self.app.execute(plan)
        self.assertTrue(all("건너뜀" in line for line in report))
        self.assertFalse(Path(plan["rows"][0]["target"]).parent.exists())
        self.assertTrue(all(p.exists() for p in paths))

    def test_failed_group_is_compensated(self):
        paths=self.project()
        relocate=storage.relocate
        def fail_one(src,dst):
            if src==paths[1]:raise OSError("시험 오류")
            relocate(src,dst)
        with patch.object(storage,"relocate",side_effect=fail_one):
            report=self.move()
        self.assertEqual(sum("복원 완료" in r for r in report),2)
        self.assertFalse(any("이동 완료" in r for r in report))
        self.assertTrue(all(p.exists() for p in paths))
        self.assertFalse((self.inbox/"달빛정원").exists())

    def test_restart_after_rename_before_journal_acknowledgement(self):
        paths=self.project()
        worker="""
import os
from desktop_service import Desktop
import storage
move = storage.relocate
def interrupt(src,dst):
    move(src,dst)
    os._exit(73)
storage.relocate = interrupt
app = Desktop()
app.scan(dict(deep=False,covers=False,folderMode="new"))
app.execute(app.preview({}))
"""
        process=subprocess.run([sys.executable,"-B","-X","utf8","-c",worker],
                               cwd=Path(__file__).parent,timeout=30,
                               env=dict(os.environ,MOA_HOME=str(storage.HOME),MOA_DOWNLOADS=str(self.inbox)))
        self.assertEqual(process.returncode,73)
        self.assertEqual(sum(p.exists() for p in paths),2)
        history=Desktop().run("history",{})
        self.assertEqual((history[0]["undone"],history[0]["pending"]),(1,0))
        self.assertTrue(all(p.exists() for p in paths))
        self.assertFalse((self.inbox/"달빛정원").exists())

    def test_interrupted_rollback_with_occupied_source_is_retryable(self):
        self.project()
        relocate=storage.relocate
        def interrupt(src,dst):
            relocate(src,dst)
            src.write_bytes(b"occupied")
            raise SystemExit()
        with patch.object(storage,"relocate",side_effect=interrupt),self.assertRaises(SystemExit):
            self.move()
        app=Desktop()
        batch=app.run("history",{})[0]
        self.assertEqual(batch["pending"],1)
        args=dict(kind="undo",batch=batch["id"])
        row,=app.preview(args)["rows"]
        self.assertIn("사용 중",row["skip"])
        source=Path(row["target"])
        self.assertEqual(source.read_bytes(),b"occupied")
        source.unlink()
        app.execute(app.preview(args))
        self.assertEqual(source.read_bytes(),source.name.encode())

    def test_select_older_batch_and_retry_only_remaining_rows(self):
        first=self.project()
        self.move()
        first_id=self.app.run("history",{})[0]["id"]
        second=self.project("별빛전시")
        self.move()
        app=Desktop()
        batch=dict(kind="undo",batch=first_id)
        preview=app.preview(batch)
        first[0].write_bytes(b"occupied")
        altered=Path(next(r["source"] for r in preview["rows"] if r["target"]==str(first[1])))
        saved=altered.read_bytes()
        altered.write_bytes(b"modified")
        report=app.execute(preview)
        self.assertEqual(sum("복원 보류" in r for r in report),2)
        self.assertEqual(first[0].read_bytes(),b"occupied")
        self.assertEqual(altered.read_bytes(),b"modified")
        blocked=app.preview(batch)["rows"]
        self.assertEqual(len(blocked),2)
        self.assertTrue(all(r["skip"] for r in blocked))
        first[0].unlink()
        altered.write_bytes(saved)
        app.execute(app.preview(batch))
        self.assertTrue(all(p.is_file() for p in first))
        self.assertTrue(all(not p.exists() for p in second))
        self.assertEqual(app.preview(batch)["rows"],[])
        with self.assertRaises(ValueError):app.preview(dict(kind="undo",batch="../settings"))

    def test_legacy_batches_beyond_ten_and_deleted_destination(self):
        directory=storage.HOME/"History"
        directory.mkdir(parents=True)
        src,dst=self.inbox/"old.txt",self.inbox/"archived.txt"
        dst.write_bytes(b"old")
        for i in range(12):
            row=dict(src=str(src),dst=str(dst),sha=storage.checksum(dst),status="undone" if i else "moved")
            (directory/f"20260101-0000{i:02}-old.json").write_text(json.dumps([row]))
        app=Desktop()
        history=app.run("history",{})
        self.assertEqual(len(history),12)
        batch=dict(kind="undo",batch=history[-1]["id"])
        dst.unlink()
        self.assertIn("사라졌",app.preview(batch)["rows"][0]["skip"])
        dst.write_bytes(b"old")
        app.execute(app.preview(batch))
        self.assertEqual(src.read_bytes(),b"old")

    def test_damaged_history_preserves_other_batches(self):
        self.project()
        self.move()
        damaged=storage.HOME/"History"/"unreadable.json"
        damaged.write_bytes(b"{")
        records=Desktop().run("history",{})
        self.assertEqual(sum(r["readable"] for r in records),1)
        self.assertIsNotNone(storage.latest()[0])
        self.assertEqual(damaged.read_bytes(),b"{")

    def test_inline_title_updates_preview_without_scanning_or_moving(self):
        paths=self.project()
        data=self.scan()
        group=data["groups"][0]["id"]
        old=self.app.preview({})
        def rename(title):
            return self.app.run("edit",dict(generation=data["generation"],kind="folderTitle",group=group,title=title))
        for invalid in ("","../other","NUL"):
            with self.assertRaises(ValueError):rename(invalid)
        with patch("engine.analyze",side_effect=AssertionError("unexpected scan")):
            result=rename("달빛정원 납품")
        folder=self.inbox/"달빛정원 납품"
        self.assertEqual({Path(r["target"]).parent for r in result["layout"]},{folder})
        self.assertFalse(folder.exists())
        self.assertTrue(all(p.exists() for p in paths))
        with self.assertRaises(ValueError):self.app.execute(old)
        self.assertEqual(self.scan()["groups"][0]["title"],folder.name)

    def rename_on_disk(self,path,name):
        app=self.app
        edit=app.run("beginRename",dict(entry="search",source=str(path)))
        return app.run("renameEntry",dict(token=edit["token"],title=name))

    def test_renamed_folder_and_file_follow_an_older_move(self):
        sources=self.project()
        self.move()
        first=self.app.run("history",{})[0]["id"]
        original=self.inbox/"달빛정원"
        folder=Path(self.rename_on_disk(original,"공유 보관함")["path"])
        child=Path(self.rename_on_disk(folder/sources[0].name,"수정한 이름.xlsx")["path"])
        self.assertTrue(child.is_file())
        app=Desktop()
        preview=app.preview(dict(kind="undo",batch=first))
        self.assertTrue(all(not row["skip"] for row in preview["rows"]))
        self.assertEqual({Path(r["source"]).parent for r in preview["rows"]},{folder})
        self.assertIn(str(child),[r["source"] for r in preview["rows"]])
        app.execute(preview)
        self.assertFalse(folder.exists())
        for path in sources:self.assertEqual(path.read_bytes(),path.name.encode())

    def test_undo_folder_name_preserves_children_and_renamed_source_roots(self):
        nested=self.inbox/"원본"
        nested.mkdir()
        child=nested/"보관.txt"
        child.write_bytes(b"sample")
        self.scan(roots=[str(nested)])
        result=self.rename_on_disk(nested,"보관폴더")
        changed=Path(result["path"])
        self.assertEqual(storage.source_roots(),[str(changed)])
        self.assertEqual((changed/child.name).read_bytes(),b"sample")
        app=Desktop()
        app.execute(app.preview(dict(kind="undo")))
        self.assertEqual(storage.source_roots(),[str(nested)])
        self.assertEqual(child.read_bytes(),b"sample")

    def test_rename_rejects_stale_selection_and_conflicts(self):
        original,other,_=self.project()
        edit=self.app.run("beginRename",dict(entry="search",source=str(original)))
        with self.assertRaises(FileExistsError):
            self.app.run("renameEntry",dict(token=edit["token"],title=other.name))
        original.rename(original.with_suffix(".old"))
        original.write_bytes(b"replacement")
        with self.assertRaises(ValueError):
            self.app.run("renameEntry",dict(token=edit["token"],title="bad.xlsx"))
        self.assertEqual(original.read_bytes(),b"replacement")
        self.assertEqual(other.read_bytes(),other.name.encode())

    def test_recover_after_disk_rename_before_rewriting_history(self):
        sources=self.project()
        self.move()
        batch=storage.recent_history()[0]["id"]
        folder=self.inbox/"달빛정원"
        with patch.object(entry_names,"recover",side_effect=SystemExit),self.assertRaises(SystemExit):
            self.rename_on_disk(folder,"새 이름")
        app=Desktop()
        self.assertEqual(app.run("history",{})[0]["operation"],"rename")
        app.execute(app.preview(dict(kind="undo",batch=batch)))
        self.assertTrue(all(p.is_file() for p in sources))
