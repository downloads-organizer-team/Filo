from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from desktop_service import Desktop
import feedback
from models import DownloadContext
import storage


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        base=Path(self.enterContext(TemporaryDirectory()))
        self.root=base/"Downloads"
        self.root.mkdir()
        self.enterContext(patch.object(storage,"HOME",base/"State"))
        self.enterContext(patch.object(storage,"downloads_folder",return_value=self.root))
        self.app=Desktop()

    def create(self,*names):
        for name in names:
            path=self.root/name
            path.parent.mkdir(exist_ok=True,parents=True)
            path.write_text(name,encoding="utf-8")

    def scan(self,mode="new",minimum=.7):
        return self.app.scan(dict(folderMode=mode,minConfidence=minimum,deep=False,covers=False))

    def test_activity_names_and_unrelated_lecture(self):
        event=["[붙임2] (제8회) TS 보안 허점을 찾아라 (참가신청서 양식).hwp",
               "(붙임3) (제8회) TS 보안 허점을 찾아라 (신고서 양식).pdf",
               "(제8회) TS 보안 허점을 찾아라_참가신청서_새팀.pdf"]
        team=["(킥오프)WHS 4기 팀 프로젝트_난기류.pdf","[공방전][난기류팀] 최종 발표.pdf",
              "난기류 로고.png","난기류레드팀_공방전.pdf"]
        program=["[WHS4] 네트워크 과제 - 박하나.pdf","박하나-WHS지원금-영수증.zip",
                 "AWS 보고서_WHS 4기_박하나.pdf"]
        summer=["2026_여름_프로젝트_1주차_보고서.pdf","여름 프로젝트 2주차 보고서.pdf",
                "여름 프로젝트 3주차 보고서.docx"]
        noise=["02. XSS 공격.pdf","네트워크 강의_작성자 박하나.pdf","무제 (1).pptx","Untitled 2.docx"]
        self.create(*(event+team+program+summer+noise))
        self.scan()
        grouped={g.title:{m.name for m in g.members} for g in self.app.study.groups}
        self.assertEqual(grouped,{"TS 보안 허점을 찾아라":set(event),"난기류":set(team),
                                  "WHS 4기":set(program),"여름 프로젝트":set(summer)})

    def test_opaque_batch_requires_same_shape_and_verified_close_downloads(self):
        names=["51aa2385ca91bcdef0ab.pdf","58aa2385ca91bcdbe0ae.pdf","59aa2385ca91bcdee0ae.pdf","69aa2385ca91bcdee0ae.pdf",
               "be62b04a-901f-471e-818c-9ed65e1b1922.pdf"]
        self.create(*names)
        self.assertFalse(self.scan()["groups"])
        times=[0,150,300,650,10]
        for f in self.app.study.files:
            stamp=datetime(2026,5,1,tzinfo=timezone.utc)+timedelta(seconds=times[names.index(f.name)])
            feedback.record_download(f.uid,DownloadContext(downloaded_at=stamp.isoformat()))
        self.scan()
        self.assertEqual([{f.name for f in g.members} for g in self.app.study.groups],[set(names[:3])])
        self.assertIn("다운로드",self.app.study.groups[0].title)
        self.assertFalse(self.scan(minimum=1)["groups"])

    def test_excerpt_does_not_replace_a_descriptive_filename(self):
        import similarity
        self.create("네트워크_강의.txt","네트워크_실습.txt","5. XSS 공격.txt","첨부.txt")
        self.scan()
        study=self.app.study
        files={f.name:f.index for f in study.files}
        anchor=files["네트워크_강의.txt"]
        for name in ("5. XSS 공격.txt","첨부.txt"):
            study.extras[files[name]]=similarity.content_vector(study,"네트워크 네트워크")
        unrelated=files["5. XSS 공격.txt"]
        self.assertEqual(similarity.refined(study,unrelated,anchor),study.primary[unrelated][anchor])
        self.assertGreater(similarity.refined(study,files["첨부.txt"],anchor),70)

    def test_program_position_and_joint_programs(self):
        single=["[ACE] 네트워크 강의.pdf","작성자 박하나_후기_ACE.txt","[ACE] 발표자료.docx"]
        joint=["WHS 4기 BOB 15기 공동 일정.pdf","BOB 15기 WHS 4기 참가 안내.docx","WHS 4기 BOB 15기 결과.xlsx"]
        self.create(*(single+joint))
        self.scan()
        self.assertEqual({g.title:{f.name for f in g.members} for g in self.app.study.groups},
                         {"ACE":set(single),"BOB 15기 · WHS 4기":set(joint)})

    def test_version_week_and_camera_numbers_do_not_name_an_activity(self):
        for marker in ("REV2","week2","IMG12"):
            with self.subTest(marker=marker):
                self.create(f"[{marker}] 학술대회 예산.xlsx",f"[{marker}] 자동차 수리 내역.pdf")
                self.scan()
                self.assertFalse(any(self.app.study.activities))
                self.assertFalse(self.app.study.groups)
                for f in self.app.study.files:f.path.unlink()

    def test_short_random_names_and_creation_time_without_a_source_do_not_group(self):
        short=["ab2c435f.pdf","ab2c435e.pdf"]
        long=["51aa2385ca91bcdef0ab.pdf","58aa2385ca91bcdbe0ae.pdf","59aa2385ca91bcdee0ae.pdf"]
        self.create(*(short+long))
        self.assertFalse(self.scan()["groups"])
        for f in self.app.study.files:
            feedback.record_download(f.uid,DownloadContext(url="https://download.example/file",domain="download.example"))
        self.scan()
        self.assertEqual([{f.name for f in g.members} for g in self.app.study.groups],[set(long)])
        self.assertIn("생성 시각",self.app.study.groups[0].title_note)

    def test_existing_folder_matches_single_file_by_contents_and_undo_preserves_it(self):
        self.create("보관함/달빛정원_이전 견적.pdf","달빛정원_새 시안.png","무제.txt")
        old=self.root/"보관함"/"달빛정원_이전 견적.pdf"
        result=self.scan("reuse")
        self.assertEqual({f["name"] for f in result["files"]},{"달빛정원_새 시안.png","무제.txt"})
        preview=self.app.preview(dict(kind="organize"))
        self.assertEqual([Path(r["target"]).parent for r in preview["rows"]],[old.parent])
        self.app.execute(preview)
        self.assertTrue(old.is_file())
        self.assertTrue((old.parent/"달빛정원_새 시안.png").is_file())
        self.app.execute(self.app.preview(dict(kind="undo")))
        self.assertEqual(old.read_text(encoding="utf-8"),"보관함/달빛정원_이전 견적.pdf")
        self.assertTrue((self.root/"달빛정원_새 시안.png").is_file())
        self.assertFalse(self.scan("new")["groups"])
        self.assertFalse(self.scan("reuse",1)["groups"])

    def test_existing_folder_by_name_or_new_without_collision(self):
        self.create("달빛정원/이전.txt","달빛정원_시안.png","달빛정원_견적.xlsx","달빛정원_일정.pdf")
        self.scan("reuse")
        existing=self.app.preview(dict(kind="organize"))
        self.assertEqual({Path(r["target"]).parent.name for r in existing["rows"]},{"달빛정원"})
        self.scan("new")
        new=self.app.preview(dict(kind="organize"))
        self.assertEqual({Path(r["target"]).parent.name for r in new["rows"]},{"달빛정원 (2)"})
        self.create("달빛정원 (2)/사전 작업.txt")
        self.app.execute(new)
        self.assertTrue((self.root/"달빛정원_견적.xlsx").is_file())
        self.assertEqual(len(list((self.root/"달빛정원 (2)").iterdir())),1)

    def test_existing_project_folder_year_must_match(self):
        self.create("2025 여름 프로젝트/작년 문서.txt","2026 여름 프로젝트 1주차 보고서.pdf")
        self.assertFalse(self.scan("reuse")["groups"])
        self.create("2026 여름 프로젝트 2주차 보고서.docx","2026 여름 프로젝트 3주차 보고서.xlsx")
        self.scan("reuse")
        self.assertEqual(len(self.app.study.groups),1)
        self.assertIsNone(self.app.study.groups[0].destination)
        self.create("2026 여름 프로젝트/올해 문서.txt")
        self.scan("reuse")
        rows=self.app.preview(dict(kind="organize"))["rows"]
        self.assertEqual(len(rows),3)
        self.assertEqual({Path(r["target"]).parent.name for r in rows},{"2026 여름 프로젝트"})

    def test_identifiers_remain_distinct_in_folder_reuse(self):
        self.create("AB-203451/old.txt","AB-203452/old.txt","검수증 ab203451.xlsx",
                    "AB-203452 송장.pdf","무제.png")
        self.scan("reuse")
        rows=self.app.preview(dict(kind="organize"))["rows"]
        self.assertEqual({r["name"]:Path(r["target"]).parent.name for r in rows},
                         {"검수증 ab203451.xlsx":"AB-203451","AB-203452 송장.pdf":"AB-203452"})

    def test_existing_destination_requires_full_short_words_and_numbers(self):
        self.create("Studio 12/old.txt","Studio 17_배송.pdf","Studio 12_지도.png",
                    "풍경과 빛/old.txt","풍경과 꿈_계약.pdf","풍경과 빛_시안.png")
        self.scan("reuse")
        rows=self.app.preview(dict(kind="organize"))["rows"]
        self.assertEqual({r["name"]:Path(r["target"]).parent.name for r in rows},
                         {"Studio 12_지도.png":"Studio 12","풍경과 빛_시안.png":"풍경과 빛"})

    def test_sample_from_another_year_is_insufficient(self):
        self.create("보관함/달빛정원_2025 견적.pdf","달빛정원_2026 시안.pdf")
        self.assertFalse(self.scan("reuse")["groups"])
        self.create("보관함/달빛정원_2026 기획.txt")
        self.scan("reuse")
        self.assertEqual(self.app.study.groups[0].destination,self.root/"보관함")

    def test_ambiguous_existing_destinations_abstain(self):
        self.create("보관 A/달빛정원_이전 견적.pdf","보관 B/달빛정원_이전 자료.pdf","달빛정원_추가 견적.pdf")
        self.assertFalse(self.scan("reuse")["groups"])

    def test_word_inside_filename_does_not_match_a_sample_project_prefix(self):
        self.create("실습 정리/XSS_워크숍.md","대회 증빙 자료 XSS 보고서.pdf")
        self.assertFalse(self.scan("reuse")["groups"])

    def test_legacy_recursive_setting_does_not_expose_children(self):
        self.create("보관함/기존 파일.txt","신규 파일.txt")
        storage.remember_options(True,False,False,[str(self.root)])
        result=self.app.scan(dict(recursive=True))
        self.assertEqual([f["name"] for f in result["files"]],["신규 파일.txt"])
        self.assertFalse(result["options"]["recursive"])

    def test_threshold_validation_persistence_and_manual_membership(self):
        self.create("별빛_견적.pdf","별빛_시안.png","별빛_일정.xlsx")
        for v in [-.1,.15,1.1,False,"0.7"]:
            with self.subTest(v=v),self.assertRaises(ValueError):self.scan(minimum=v)
        for step in range(11):
            minimum=step/10
            data=self.scan(minimum=minimum)
            self.assertEqual(Desktop().options()["minConfidence"],minimum)
            self.assertTrue(all(f["confidence"]>=minimum for f in data["files"] if f["group"]))
        data=self.scan(minimum=.7)
        self.app.run("edit",dict(kind="rename",group=data["groups"][0]["id"],title="확정한 묶음",generation=data["generation"]))
        self.assertEqual(self.scan(minimum=1)["groups"][0]["title"],"확정한 묶음")
