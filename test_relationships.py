"""Precision: python -B -m unittest -v test_pipeline test_relationships.

Scaling: python -B test_relationships.py --benchmark
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from time import perf_counter
import unittest
from unittest.mock import patch

import engine
import feedback
import scanner
import similarity
import storage
from features import TASK_GENERIC,clean
from models import DownloadContext


class RelationshipTests(unittest.TestCase):
    root=Path()

    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="moa-relationships-")
        self.addCleanup(tmp.cleanup)
        home=Path(tmp.name)
        self.root=home/"Downloads"
        self.root.mkdir()
        patcher=patch.object(storage,"HOME",home/"state")
        patcher.start()
        self.addCleanup(patcher.stop)

    def files(self,*names):
        for name in names:
            path=self.root/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(name,encoding="utf-8")

    def analyze(self,deep=False,metadata=None):
        original=scanner.scan
        def scan(study,recursive,stop):
            original(study,recursive,stop)
            if metadata:
                for f in study.files:metadata(f)
        with patch("engine.scan",side_effect=scan):
            s=engine.discover_relations(self.root,recursive=True,deep=deep,course_covers=False)
        return s,{f.name:f for f in s.files}

    def groups(self,study):
        return {frozenset(f.name for f in g.members) for g in study.groups}

    def test_two_file_projects_across_formats_and_locations(self):
        names=("left/안개꽃_시안.blend","right/안개꽃_견적.xlsx")
        self.files(*names,"보고서_우박.txt","보고서_종이컵.png")
        s,f=self.analyze()
        self.assertEqual(self.groups(s),{frozenset(Path(n).name for n in names)})
        self.assertIsNone(f["보고서_우박.txt"].group)
        self.assertIsNone(f["보고서_종이컵.png"].group)

    def test_delimited_project_name_still_works_without_optional_metadata(self):
        names=("left/안개꽃 - 홈페이지.blend","right/안개꽃 - 사무실.xlsx")
        self.files(*names)
        def missing(file):
            file.created=file.modified=0
        s,_=self.analyze(metadata=missing)
        self.assertEqual(self.groups(s),{frozenset(Path(n).name for n in names)})

    def test_korean_shared_identity_needs_context_and_ignores_roles(self):
        names=("제주여행_항공권.pdf","제주_일정.xlsx")
        self.files(*names,"숙소예약.png","부산_항공권.pdf","여행_예약.txt")
        s,f=self.analyze(True)
        self.assertEqual(self.groups(s),{frozenset(names)})
        self.assertTrue(all(f[n].group is None for n in ("숙소예약.png","부산_항공권.pdf","여행_예약.txt")))
        def missing(file):
            file.created=file.modified=0
        s,_=self.analyze(metadata=missing)
        self.assertFalse(s.groups)

    def test_actual_project_parent_can_identify_role_only_file(self):
        names=("제주여행_항공권.pdf","제주_일정.xlsx","숙소예약.png")
        self.files(*(f"제주여행/{name}" for name in names),"숙소예약.png")
        s,f=self.analyze()
        self.assertEqual(self.groups(s),{frozenset(names)})
        self.assertIsNone(next(x for x in s.files if x.path.parent==self.root).group)
        self.assertEqual(len(next(g for g in s.groups if len(g.members)==3).members),3)

    def test_versions_and_sequences_do_not_require_matching_extensions(self):
        versions=("aurora_v1.pdf","aurora_v2.blend")
        sequence=("01_별빛_시안.png","02_별빛_사진.raw")
        self.files(*(versions+sequence),"01.txt","02.zip")
        s,f=self.analyze()
        self.assertEqual(self.groups(s),{frozenset(versions),frozenset(sequence)})
        self.assertTrue(similarity.compare(s,f[versions[0]].index,f[versions[1]].index,True)["version"])
        self.assertIsNone(f["01.txt"].group)
        self.assertIsNone(f["02.zip"].group)

    def test_conflicting_project_labels_survive_shared_topics_and_content(self):
        first=("Atlas_디자인_시안.png","Atlas_디자인_배치.dwg")
        second=("Boreal_디자인_시안.png","Boreal_디자인_배치.dwg")
        self.files(*(first+second))
        s,f=self.analyze(True)
        self.assertEqual(self.groups(s),{frozenset(first),frozenset(second)})
        i,j=f[first[0]].index,f[second[0]].index
        self.assertLess(s.matrix[i][j],60)
        s.extras[i]=s.vectors[j]
        self.assertEqual(similarity.refined(s,i,j),s.primary[i][j])

    def test_same_time_and_generic_travel_roles_are_not_identity(self):
        self.files("항공권.pdf","일정.xlsx","숙소예약.png","travel_ticket.pdf",
                   "trip_booking.xlsx","우박.txt","종이컵.png","01.pdf","02.zip")
        s,_=self.analyze(True)
        self.assertFalse(s.groups)
        self.assertFalse(s.attempted)

    def test_distinct_years_do_not_join_repeated_trip_identity(self):
        first=("제주여행_2025_항공권.pdf","제주여행_2025_일정.xlsx")
        second=("제주여행_2026_항공권.pdf","제주여행_2026_일정.xlsx")
        self.files(*(first+second))
        s,_=self.analyze(True)
        self.assertEqual(self.groups(s),{frozenset(first),frozenset(second)})

    def test_relative_folder_names_do_not_cross_actual_roots(self):
        self.files("left/shared/우박.pdf","right/shared/종이컵.xlsx")
        def relative(file):
            file.rel="shared"
        s,f=self.analyze(metadata=relative)
        details=similarity.compare(s,0,1,True)
        self.assertFalse(details["folder"])
        self.assertFalse(s.groups)

    def test_relative_folder_names_do_not_trigger_cross_root_content_reads(self):
        self.files("left/shared/안개꽃_시안.blend","left/shared/안개꽃_견적.xlsx","right/shared/01.txt")
        def relative(file):
            file.rel="shared"
        with patch("refinement.read") as read:
            s,f=self.analyze(True,metadata=relative)
        self.assertEqual(self.groups(s),{frozenset(("안개꽃_시안.blend","안개꽃_견적.xlsx"))})
        self.assertIsNone(f["01.txt"].group)
        read.assert_not_called()

    def test_source_pages_keep_query_identity_and_ignore_homepages(self):
        names=("제주여행_항공권.pdf","제주_일정.xlsx")
        self.files(*names)
        def missing(file):
            file.created=file.modified=0
        s,f=self.analyze(metadata=missing)
        for name in names:
            feedback.record_download(f[name].uid,DownloadContext(
                source_page="https://travel.example/project?id=jeju"))
        s,f=self.analyze(metadata=missing)
        self.assertEqual(self.groups(s),{frozenset(names)})
        self.assertTrue(similarity.compare(s,0,1,True)["source_page"])
        feedback.record_download(f[names[1]].uid,DownloadContext(
            source_page="https://travel.example/project?id=busan"))
        s,_=self.analyze(metadata=missing)
        self.assertFalse(similarity.compare(s,0,1,True)["source_page"])
        self.assertFalse(s.groups)
        self.assertIsNone(similarity.source_page_key("https://travel.example/"))

    def test_browser_download_timestamps_supply_optional_context(self):
        names=("제주여행_항공권.pdf","제주_일정.xlsx")
        self.files(*names)
        s,f=self.analyze()
        for name in names:
            feedback.record_download(f[name].uid,DownloadContext(downloaded_at="2026-11-19T12:00:00+09:00"))
        def missing(file):
            file.created=file.modified=0
        s,_=self.analyze(metadata=missing)
        self.assertEqual(self.groups(s),{frozenset(names)})

    @unittest.skipUnless(os.name=="nt","Windows alternate data streams")
    def test_zone_identifier_retains_referring_project_page(self):
        self.files("제주여행_항공권.pdf","제주_일정.xlsx")
        for path in self.root.iterdir():
            Path(str(path)+":Zone.Identifier").write_text(
                "[ZoneTransfer]\nZoneId=3\nHostUrl=https://cdn.example/file\n"
                "ReferrerUrl=https://travel.example/project?id=jeju\n",encoding="utf-8")
        s,_=self.analyze()
        self.assertEqual(self.groups(s),{frozenset(f.name for f in s.files)})
        self.assertTrue(all(f.download.source_page=="https://travel.example/project?id=jeju" for f in s.files))

    def test_matrix_cache_preserves_every_pair_and_group(self):
        self.files("안개꽃_시안.blend","안개꽃_견적.xlsx","우박.txt","종이컵.png")
        s,_=self.analyze()
        class PerFile:
            def __init__(self,get):
                self.get=get
            def __getitem__(self,index):
                return self.get(s.files[index])
        for i in range(len(s.files)):
            for j in range(i):
                with patch("similarity.source_page_key",side_effect=AssertionError("per-pair parsing")):
                    self.assertEqual(similarity.compare(s,i,j),s.matrix[i][j])
                with patch.object(s,"source_pages",PerFile(lambda f:similarity.source_page_key(f.download.source_page))), \
                     patch.object(s,"role_sets",PerFile(lambda f:frozenset(f.roles))), \
                     patch.object(s,"parents",PerFile(lambda f:os.path.normcase(os.path.abspath(f.path.parent))
                         if clean(f.path.parent.name) not in TASK_GENERIC|{"공용","inbox"} else "")):
                    self.assertEqual(similarity.compare(s,i,j),s.matrix[i][j])
        self.assertEqual(self.groups(s),{frozenset(("안개꽃_시안.blend","안개꽃_견적.xlsx"))})


def benchmark():
    """Full real scan/pipeline, paired mixed-format projects, no content reading."""
    with tempfile.TemporaryDirectory(prefix="moa-scaling-") as temp:
        base=Path(temp)
        with patch.object(storage,"HOME",base/"state"):
            for count in (100,500,1000):
                root=base/str(count)
                root.mkdir()
                for i in range(count):
                    (root/f"unit{i//2:06d}_{'proposal.pdf' if i%2 else 'budget.xlsx'}").write_bytes(str(i).encode())
                started=perf_counter()
                stages={}
                last_time=started
                last_stage="scan"
                def status(text):
                    nonlocal last_time,last_stage
                    now=perf_counter()
                    stages[last_stage]=round(now-last_time,6)
                    last_time,last_stage=now,text
                s=engine.analyze(root,deep=False,status=status,course_covers=False)
                elapsed=perf_counter()-started
                expected={frozenset((f"unit{i:06d}_proposal.pdf",f"unit{i:06d}_budget.xlsx")) for i in range(count//2)}
                actual={frozenset(f.name for f in g.members) for g in s.groups}
                if actual!=expected:raise AssertionError((count,len(actual),len(expected)))
                print(json.dumps(dict(files=count,pairs=count*(count-1)//2,seconds=round(elapsed,6),
                                      matrix_seconds=round(sum(v for k,v in stages.items() if k.startswith("유사도 행렬")),6),
                                      clustering_seconds=stages.get("완전 연결 계층 클러스터링 중"),
                                      groups=len(actual),exact_groups=actual==expected)),flush=True)


if __name__=="__main__":
    if "--benchmark" in sys.argv:benchmark()
    else:unittest.main()
