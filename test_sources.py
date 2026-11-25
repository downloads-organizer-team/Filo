import importlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
from typing import Literal, overload
import unittest
from unittest.mock import patch

import storage
from desktop_service import Desktop
from models import Group, ScanResult, MovePreview


class SourceTests(unittest.TestCase):
    root=Path()
    extra=Path()
    destination=Path()
    app=Desktop()
    _data:ScanResult|None=None

    @property
    def data(self) -> ScanResult:
        assert self._data is not None
        return self._data

    @data.setter
    def data(self,value:ScanResult):
        self._data=value
    def setUp(self):
        base=Path(self.enterContext(TemporaryDirectory()))
        self.root=base/"Downloads";self.root.mkdir()
        self.extra=base/"Extra";self.extra.mkdir()
        self.destination=base/"Destination";self.destination.mkdir()
        self.enterContext(patch.object(storage,"HOME",base/"Home"))
        self.enterContext(patch.object(storage,"downloads_folder",return_value=self.root))
        self.app=Desktop()

    def scan(self,roots=None,recursive=True):
        args=dict(deep=False,covers=False,recursive=recursive)
        if roots is not None:args["roots"]=roots
        self.data=self.app.run("scan",args)
        return self.data

    @overload
    def call(self,action:Literal["preview"],**args) -> MovePreview: ...
    @overload
    def call(self,action:Literal["execute"],**args) -> list[str]: ...
    def call(self,action,**args):
        return self.app.run(action,dict(generation=self.data["generation"],**args))

    def grouped(self):
        self.scan([str(self.root),str(self.extra)])
        group=Group("test","Collected",self.app.study.files)
        self.app.study.groups=[group]
        for file in group.members:file.group=group
        return group

    def test_sources_persist_defaults_and_scan_overlap(self):
        nested=self.root/"Nested";nested.mkdir()
        (nested/"alpha.txt").write_text("alpha")
        (self.extra/"beta.txt").write_text("beta")
        options=self.app.run("sources",dict(roots=[str(nested),str(self.extra),str(self.extra)]))
        self.assertEqual(options["roots"],list(map(str,[nested,self.extra])))
        self.assertEqual(Desktop().options(),options)
        data=self.scan()
        self.assertEqual(data["roots"],options["roots"])
        self.assertEqual(data["root"],str(nested))
        self.assertEqual({f["path"] for f in data["files"]},{str(nested/"alpha.txt"),str(self.extra/"beta.txt")})
        self.assertEqual(len(data["files"]),2)
        self.assertEqual({f.rel for f in self.app.study.files},{str(nested),str(self.extra)})
        self.assertEqual(len({f.uid for f in self.app.study.files}),2)
        reset=self.app.run("sources",dict(roots=[]))
        self.assertEqual(reset["roots"],[])
        with self.assertRaises(ValueError):self.scan()

    def test_nonrecursive_overlapping_root_still_scans_explicit_child(self):
        nested=self.root/"Nested";nested.mkdir()
        (nested/"alpha.txt").write_text("alpha")
        self.assertEqual(len(self.scan([str(nested)],recursive=False)["files"]),1)

    def test_invalid_and_unavailable_roots_leave_settings(self):
        expected=self.app.options()
        for roots in ("bad",["relative"],[str(self.extra/"missing")]):
            with self.assertRaises((OSError,ValueError)):
                self.app.run("sources",dict(roots=roots))
            self.assertEqual(self.app.options(),expected)
        self.app.run("sources",dict(roots=[str(self.extra)]))
        self.extra.rmdir()
        self.assertIn(str(self.extra),self.app.options()["roots"])
        with self.assertRaises(OSError):self.scan()

    def test_default_new_and_existing_destinations_move_and_undo(self):
        self.assertEqual(self.app.run("history",{}),[])
        for mode,destination in (("new",None),("new",self.destination),("existing",self.destination)):
            with self.subTest(mode=mode,destination=destination):
                a=self.root/"alpha.txt";b=self.extra/"beta.txt"
                a.write_text("alpha");b.write_text("beta")
                group=self.grouped()
                args=dict(kind="organize",group=group.gid,destinationMode=mode)
                if destination is not None:args["destination"]=str(destination)
                preview=self.call("preview",**args)
                folder=(destination or self.root)/"Collected" if mode=="new" else self.destination
                self.assertEqual({Path(row["target"]).parent for row in preview["rows"]},{folder})
                self.assertTrue(all(not row["skip"] for row in preview["rows"]))
                self.call("execute",token=preview["token"])
                self.assertFalse(a.exists());self.assertFalse(b.exists())
                log,rows=storage.latest()
                self.assertTrue(all(r["source_roots"]==list(map(str,[self.root,self.extra])) for r in rows))
                undo=self.call("preview",kind="undo")
                self.call("execute",token=undo["token"])
                self.assertEqual(a.read_text(),"alpha");self.assertEqual(b.read_text(),"beta")
                history=self.app.run("history",{})
                self.assertEqual((history[0]["moved"],history[0]["undone"],history[0]["pending"]),(2,2,0))
                self.assertEqual(set(history[0]["files"]),{"alpha.txt","beta.txt"})
                if mode=="new":self.assertFalse(folder.exists())
                else:self.assertTrue(folder.is_dir())

    def test_collisions_across_roots_and_after_preview(self):
        (self.root/"same.txt").write_text("one")
        (self.extra/"same.txt").write_text("two")
        group=self.grouped()
        preview=self.call("preview",kind="organize",destinationMode="existing",destination=str(self.destination))
        self.assertEqual(sum(bool(r["skip"]) for r in preview["rows"]),1)
        conflict=self.destination/"same.txt";conflict.write_text("collision")
        self.call("execute",token=preview["token"])
        self.assertEqual(conflict.read_text(),"collision")
        self.assertTrue(all(f.path.exists() for f in group.members))

    def test_only_checked_source_reserves_destination_and_moves(self):
        for root,value in [(self.root,"keep"),(self.extra,"move")]:
            (root/"same.txt").write_text(value)
        group=self.grouped()
        moving=next(f for f in group.members if f.path.parent==self.extra)
        args=dict(kind="organize",destinationMode="existing",destination=str(self.destination))
        self.assertEqual(self.call("preview",files=[],**args)["rows"],[])
        preview=self.call("preview",files=[moving.index],**args)
        self.assertEqual([(r["source"],r["skip"]) for r in preview["rows"]],[(str(moving.path),"")])
        self.call("execute",token=preview["token"])
        self.assertEqual((self.root/"same.txt").read_text(),"keep")
        self.assertEqual((self.destination/"same.txt").read_text(),"move")
        self.assertFalse(moving.path.exists())
        undo=self.call("preview",kind="undo")
        self.call("execute",token=undo["token"])
        self.assertEqual(moving.path.read_text(),"move")

    def test_stale_source_and_settings_invalidate_preview(self):
        source=self.extra/"alpha.txt";source.write_text("alpha")
        self.grouped()
        preview=self.call("preview",kind="organize")
        self.app.run("sources",dict(roots=[str(self.extra)]))
        with self.assertRaises(ValueError):self.call("execute",token=preview["token"])
        preview=self.call("preview",kind="organize")
        source.write_text("modified")
        self.call("execute",token=preview["token"])
        self.assertEqual(source.read_text(),"modified")
        self.assertFalse(Path(preview["rows"][0]["target"]).exists())

    def test_replaced_source_identity_is_stale_even_with_same_metadata(self):
        source=self.extra/"alpha.txt";source.write_text("alpha")
        self.grouped()
        preview=self.call("preview",kind="organize")
        old=source.stat()
        replacement=self.extra/"replacement.txt";replacement.write_text("alpha")
        os.utime(replacement,ns=(old.st_atime_ns,old.st_mtime_ns))
        os.replace(replacement,source)
        self.call("execute",token=preview["token"])
        self.assertTrue(source.exists())
        self.assertFalse(Path(preview["rows"][0]["target"]).exists())

    def test_destination_requires_absolute_existing_directory(self):
        (self.extra/"alpha.txt").write_text("alpha")
        self.grouped()
        for mode,destination in (("existing",None),("new","relative"),("existing",str(self.extra/"missing")),("other",str(self.destination))):
            with self.assertRaises((OSError,ValueError)):
                self.call("preview",kind="organize",destinationMode=mode,destination=destination)

    def test_unknown_group_rejects_edit_with_recoverable_error(self):
        (self.extra/"alpha.txt").write_text("alpha")
        self.grouped()
        with self.assertRaises(ValueError):
            self.app.run("edit",dict(kind="rename",group="stale-group",title="Renamed",
                                    generation=self.data["generation"]))

    def test_link_roots_and_destinations_are_rejected(self):
        link=self.root/"link"
        if os.name=="nt":
            subprocess.run(["cmd.exe","/c","mklink","/J",str(link),str(self.extra)],
                           check=True,capture_output=True)
        else:
            link.symlink_to(self.extra,target_is_directory=True)
        (self.extra/"alpha.txt").write_text("alpha")
        with self.assertRaises(OSError):self.app.run("sources",dict(roots=[str(link)]))
        self.scan()
        self.assertEqual(self.data["files"],[])
        self.grouped()
        with self.assertRaises(OSError):
            self.call("preview",kind="organize",destination=str(link))

    def test_search_without_scan_is_independent_of_organization_roots(self):
        target=self.extra/"alpha.txt";target.write_text("project")
        self.app.run("sources",dict(roots=[str(self.root)]))
        rows=[dict(name="alpha.txt",path=str(target),isFolder=False)]
        with patch("file_search.search",return_value={"results":rows}) as search:
            result=self.app.run("search",dict(query="alpha"))
        search.assert_called_once_with("alpha")
        self.assertEqual(result["results"],rows)

    def test_related_view_is_bounded_and_excludes_unrelated_files(self):
        for number in range(1,9):(self.extra/f"별빛_시안_v{number}.txt").touch()
        (self.extra/"자동차보험.txt").touch()
        self.scan([str(self.extra)])
        source=next(f for f in self.data["files"] if f["name"]=="별빛_시안_v1.txt")
        result=self.app.run("related",dict(id=source["id"],generation=self.data["generation"]))
        self.assertEqual({r["name"] for r in result},{f"별빛_시안_v{n}.txt" for n in range(2,7)})
        self.assertTrue(all(r["signals"] and r["id"]!=source["id"] for r in result))

    def test_related_view_honors_user_separation(self):
        for number in (1,2):(self.extra/f"별빛_시안_v{number}.txt").touch()
        self.scan([str(self.extra)])
        self.app.run("edit",dict(kind="cannot",files=[0,1],generation=self.data["generation"]))
        self.scan()
        result=self.app.run("related",dict(id=0,generation=self.data["generation"]))
        self.assertEqual(result,[])


class PortableEnvironmentTests(unittest.TestCase):
    def test_environment_overrides(self):
        try:
            with TemporaryDirectory() as temp:
                home=Path(temp)/"Portable"
                downloads=Path(temp)/"Files";downloads.mkdir()
                with patch.dict(os.environ,MOA_HOME=str(home),MOA_DOWNLOADS=str(downloads)):
                    importlib.reload(storage)
                    self.assertEqual(storage.HOME,home)
                    self.assertEqual(storage.downloads_folder(),downloads)
                    storage.remember_options(True,False,False,[str(downloads)])
                    self.assertEqual(json.loads((home/"download-settings.json").read_text())["roots"],[str(downloads)])
        finally:importlib.reload(storage)
