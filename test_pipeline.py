"""Run with python -B -m unittest -v test_pipeline in the application directory."""
import os
import tempfile
import unittest
from zipfile import ZipFile
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import engine, feedback, storage, readers
from features import filename

NET={"01_네트워크개요.pdf","02_TCP_IP.pdf","DNS_실습.pptx","wireshark_lab.zip","과제_패킷분석.hwp"}
NUT={"01_영양학개론.pdf","02_탄수화물.pdf","단백질_실습.pptx"}

def write_slide_fixture(path,shapes):
    # Slide 8 is first in presentation order. Slide 1 and the metadata are decoys.
    import xml.etree.ElementTree as ET
    p="http://schemas.openxmlformats.org/presentationml/2006/main"
    a="http://schemas.openxmlformats.org/drawingml/2006/main"
    r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    def node(parent,ns,tag,**attrs):
        return ET.SubElement(parent,f"{{{ns}}}{tag}",attrs)
    slide=ET.Element(f"{{{p}}}sld")
    tree=node(node(slide,p,"cSld"),p,"spTree")
    for ph,size,paragraphs in shapes:
        shape=node(tree,p,"sp")
        if ph:
            node(node(node(shape,p,"nvSpPr"),p,"nvPr"),p,"ph",type=ph)
        body=node(shape,p,"txBody")
        for runs in paragraphs:
            para=node(body,a,"p")
            for text in runs:
                run=node(para,a,"r")
                node(run,a,"rPr",sz=str(size))
                node(run,a,"t").text=text
    with ZipFile(path,"w") as z:
        z.writestr("ppt/presentation.xml",f'<p:presentation xmlns:p="{p}" xmlns:r="{r}"><p:sldIdLst><p:sldId r:id="a"/><p:sldId r:id="b"/></p:sldIdLst></p:presentation>')
        z.writestr("ppt/_rels/presentation.xml.rels",f'<Relationships><Relationship Id="b" Type="{r}/slide" Target="slides/slide1.xml"/><Relationship Id="a" Type="{r}/slide" Target="slides/slide8.xml"/></Relationships>')
        z.writestr("ppt/slides/slide8.xml",ET.tostring(slide,encoding="utf-8"))
        z.writestr("ppt/slides/slide1.xml","<invalid")
        z.writestr("docProps/core.xml","<title>서식 파일</title>")

class CampusTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        old=storage.HOME;storage.HOME=Path(self.tmp.name)
        self.addCleanup(setattr,storage,"HOME",old)
        self.root=storage.sample()
    def run_app(self,deep=False):
        s=engine.analyze(self.root,deep=deep)
        return s,{f.name:f for f in s.files}

    def test_group_folders_preview_move_and_undo(self):
        study,files=self.run_app(True)
        group=files["DNS_실습.pptx"].group
        existing=self.root/group.title
        existing.mkdir()
        conflict=existing/"DNS_실습.pptx"
        conflict.write_bytes(b"existing file")
        plan=storage.plan_group_folders(study)
        self.assertEqual(len(plan),11)
        self.assertEqual(sum(bool(item.skip) for item in plan),1)
        before={item.file.path:item.file.path.read_bytes() for item in plan}
        self.assertEqual([d for d in self.root.iterdir() if d.is_dir()],[existing])
        storage.move_files(plan,self.root)
        self.assertEqual(conflict.read_bytes(),b"existing file")
        for item in plan:
            self.assertEqual(item.target.parent.name,item.file.group.title)
            self.assertEqual(item.file.path.exists(),bool(item.skip))
            if not item.skip:self.assertEqual(item.target.read_bytes(),before[item.file.path])
        self.assertTrue(all(f.path.is_file() for f in study.files if f.group is None))
        repeated=storage.plan_group_folders(self.run_app(True)[0])
        self.assertTrue(all(item.skip for item in repeated))
        log,_=storage.latest()
        storage.undo(log)
        self.assertTrue(all(path.read_bytes()==content for path,content in before.items()))
        self.assertEqual([d for d in self.root.iterdir() if d.is_dir()],[existing])
        self.assertEqual(conflict.read_bytes(),b"existing file")

    def test_group_names_and_collisions_after_preview(self):
        study,_=self.run_app(True)
        first,second=study.groups
        first.title="보고서/실습"
        second.title="보고서:실습"
        all_items=storage.plan_group_folders(study)
        self.assertEqual({p.target.parent.name for p in all_items},{"보고서_실습","보고서_실습 (2)"})
        plan=storage.plan_group_folders(study,second)
        self.assertEqual(plan,[p for p in all_items if p.file.group is second])
        self.assertEqual(storage.folder_name("NUL.txt"),"_NUL.txt")
        self.assertEqual(storage.folder_name(".."),"그룹")
        blocked=plan[0]
        blocked.target.parent.mkdir()
        blocked.target.write_bytes(b"added since preview")
        storage.move_files(plan,self.root)
        self.assertEqual(blocked.target.read_bytes(),b"added since preview")
        self.assertTrue(blocked.file.path.exists())
        self.assertTrue(all(f.path.exists() for f in first.members))
        log,_=storage.latest()
        storage.undo(log)
        self.assertTrue(all(p.file.path.exists() for p in plan))

    def test_mixed_courses_and_selective_reading(self):
        with patch("refinement.read",wraps=readers.read) as rd:
            a,fa=self.run_app()
            self.assertEqual(rd.call_count,0)
            b,fb=self.run_app(True)
            touched={call.args[0].name for call in rd.call_args_list}
        self.assertEqual(touched,{"첨부.pdf","과제.docx","메모.md","01.txt"})
        self.assertEqual({frozenset(f.name for f in g.members) for g in a.groups},{frozenset(NET),frozenset(NUT)})
        self.assertIs(fb["첨부.pdf"].group,fb["DNS_실습.pptx"].group)
        self.assertIs(fb["과제.docx"].group,fb["단백질_실습.pptx"].group)
        self.assertIsNone(fb["01.txt"].group)
        self.assertIsNone(fb["IMG_2031.jpg"].group)
        self.assertEqual(b.rescued,3)
        fragment,_=readers.read(fb["첨부.pdf"])
        self.assertIn("Wireshark",fragment);self.assertNotIn("탄수화물",fragment)
        self.assertIn("영양학 과제",readers.read(fb["과제.docx"])[0])
        for i in range(len(a.files)):
            self.assertEqual(b.matrix[i][i],100)
            for j in range(len(a.files)):
                self.assertEqual(b.matrix[i][j],b.matrix[j][i])
                if i not in b.extras and j not in b.extras:self.assertEqual(b.matrix[i][j],a.matrix[i][j])
        i,j=fb["첨부.pdf"].index,fb["DNS_실습.pptx"].index
        self.assertGreater(b.matrix[i][j],b.primary[i][j])
    def test_names_and_versions(self):
        f=SimpleNamespace(path=Path("02-1. 패킷 분석 실습_최종(1).pdf"))
        filename(f)
        self.assertEqual((f.sequence,f.tokens,f.versions,f.ext),("02-1",("패킷","분석","실습"),("최종","(1)"),"pdf"))
        for ver in ["final","final2","수정","진짜최종","v1","v2","copy","(1)"]:
            f=SimpleNamespace(path=Path("안개꽃_"+ver+".md"));filename(f)
            self.assertIn(ver,f.versions);self.assertIn("안개꽃",f.normalized)
        for stem in ["1주차","week01","lec01","01","2주차"]:
            f=SimpleNamespace(path=Path(stem+".md"));filename(f);self.assertTrue(f.sequence)
    def test_course_title_is_independent_of_confidence_and_chapter_numbers(self):
        from models import DownloadContext
        self.root=storage.HOME/"제목";self.root.mkdir()
        course=["chap.0 강의소개.pdf","chap.1 DevOps.pdf","chap.2 Git.pdf","practice1.md"]
        other=["CHAP.1 기업재무.pdf","CHAP.2 재무설계.pdf"]
        for name in course+other:(self.root/name).touch()
        s,files=self.run_app()
        self.assertLess(s.primary[files[course[1]].index][files[other[0]].index],60)
        self.assertEqual(files[course[0]].sequence,"chap.0")
        self.assertNotIn("chap",files[course[0]].tokens)
        for name in course+other:
            cid=111 if name in course else 222
            feedback.record_download(files[name].uid,DownloadContext(f"https://lms.example/courses/{cid}/files","lms.example"))
        with patch("readers.pdf") as read_pdf:
            s=engine.analyze(self.root,deep=True,course_covers=False)
            files={f.name:f for f in s.files}
            g=files[course[0]].group
            self.assertEqual({f.name for f in g.members},set(course))
            self.assertEqual(set(g.title.split(" · ")),{"DevOps","Git"})
            read_pdf.assert_not_called()
            read_pdf.return_value="열린 소프트웨어 설계\nChapter 0. 강의 소개"
            title,source=readers.course_cover(g.members)
            self.assertIn(course[0],source)
            self.assertEqual(title,"열린 소프트웨어 설계")
            read_pdf.assert_called_once_with(files[course[0]].path,cover_only=True)
            read_pdf.reset_mock()
            auto,automatic_files=self.run_app(True)
            self.assertEqual(automatic_files[course[0]].group.title,title)
            self.assertEqual(automatic_files[course[0]].group.title_kind,"cover")
            self.assertEqual(auto.matrix,s.matrix)
            read_pdf.assert_called_once_with(files[course[0]].path,cover_only=True)
            feedback.set_course_title(s,g,title)
        s,files=self.run_app()
        self.assertEqual(files[course[1]].group.title,title)
        self.assertNotEqual(files[other[0]].group.title,title)
        self.assertFalse(s.rules.rules.pins)
        for name in course:(self.root/name).unlink()
        for i in (3,4):
            name=f"chap.{i} 수업자료.pdf"
            (self.root/name).touch()
            s,files=self.run_app()
            feedback.record_download(files[name].uid,DownloadContext("https://lms.example/courses/111/files","lms.example"))
        s,files=self.run_app()
        self.assertEqual(files["chap.3 수업자료.pdf"].group.title,title)

    def test_course_title_sources_and_ambiguous_covers(self):
        from models import DownloadContext
        from course_titles import find_title
        def file(name,page=""):
            f=SimpleNamespace(path=Path(name),name=name,download=DownloadContext(page_title=page),
                              course_scope=None,offline=False,size=5)
            filename(f)
            return f
        fs=[file("01. 미디어와 사회 1주차 읽기.md"),file("02. 미디어와 사회 강의 2주차 토론.pdf")]
        self.assertEqual(find_title(fs,False)[::2],("미디어와 사회","filename"))
        fs[0].download.page_title="과목명: 미디어와 사회 | 강의 게시판"
        with patch("readers.pdf") as cover:
            self.assertEqual(find_title(fs,True)[::2],("미디어와 사회","lms"))
            cover.assert_not_called()
        fs[0].download.page_title="과목명: 다른 강좌 | 게시판"
        self.assertEqual(find_title(fs,True)[2],"conflict")
        fs=[file("[Lec01] Introduction.pdf"),file("[Lec02] Databases.pdf")]
        with patch("readers.pdf",return_value="Department of Computing\nSystems Design\nCh.01 Introduction") as cover:
            self.assertEqual(find_title(fs,True)[::2],("Systems Design","cover"))
            cover.assert_called_once_with(fs[0].path,cover_only=True)
        self.assertEqual(readers.title_from_cover("Example Univ.\n암호 프로토콜\n담당 교수"),"암호 프로토콜")
        self.assertEqual(readers.title_from_cover("강의계획서\n교과목명: 운영체제설계"),"운영체제설계")
        self.assertEqual(readers.title_from_cover("Chapter 1: 자료구조\n이름"),"")
        self.assertEqual(readers.title_from_cover("Professor Kim\n이름"),"")
        self.assertEqual(find_title([file("샘플 1주차.md"),file("샘플 1주차(1).md")],False)[2],"topic")

    def test_first_week_slide_names_group_and_folder_without_feedback(self):
        from models import DownloadContext
        self.root=storage.HOME/"PPTX";self.root.mkdir()
        first=self.root/"1주 1차시내용_0206.pptx"
        write_slide_fixture(first,[(None,3000,[["도시","의"],["리듬"]]),
                                   (None,1600,[["도시대학교"],["교수 김선우"]])])
        for week,session in [(1,2),(1,3),(2,1),(2,2),(2,3)]:
            (self.root/f"{week}주{session}차시내용.pptx").touch()
        for f in self.run_app()[0].files:
            feedback.record_download(f.uid,DownloadContext(f"https://lms.example/courses/731/files/{f.index}","lms.example"))
        # No membership refinement or prior course names; only the cover switch is on.
        with patch("readers.pptx_course_title",wraps=readers.pptx_course_title) as read_slide:
            base=engine.analyze(self.root,deep=False,course_covers=False)
            read_slide.assert_not_called()
            s=engine.analyze(self.root,deep=False,course_covers=True)
            read_slide.assert_called_once_with(first,intro=False)
        group=next(f.group for f in s.files if f.path==first)
        self.assertEqual((len(group.members),group.title,group.title_kind),(6,"도시의 리듬","cover"))
        self.assertEqual(s.matrix,base.matrix)
        self.assertNotIn("차시내용",base.groups[0].title)
        self.assertIn(first.name+" · 첫 슬라이드",group.title_note)
        self.assertEqual([f.path for f in s.files if f.course_cover_checked],[first])
        plan=storage.plan_group_folders(s,group)
        self.assertEqual(len(plan),6)
        self.assertEqual({item.target.parent for item in plan},{self.root/"도시의 리듬"})

    def test_slide_title_needs_cover_evidence(self):
        first=self.root/"1주1차시.pptx"
        title=("ctrTitle",3600,[["공공 데이터 읽기"]])
        write_slide_fixture(first,[title])
        self.assertEqual(readers.pptx_course_title(first,intro=False),"")
        self.assertEqual(readers.pptx_course_title(first,intro=True),"공공 데이터 읽기")
        write_slide_fixture(first,[title,("subTitle",1600,[["과목명: 시민 과학"]])])
        self.assertEqual(readers.pptx_course_title(first,intro=False),"시민 과학")
        write_slide_fixture(first,[(None,3000,[["제목 하나"]]),(None,3000,[["제목 둘"]]),
                                   (None,1600,[["담당 교수"]])])
        self.assertEqual(readers.pptx_course_title(first,intro=False),"")
        write_slide_fixture(first,[("ctrTitle",3600,[["1주 1차시내용"]]),(None,1800,[["교수 김선우"]])])
        self.assertEqual(readers.pptx_course_title(first,intro=False),"")

    def test_number_only_and_unseen_topic(self):
        self.root=Path(self.tmp.name)/"작업";self.root.mkdir()
        for name in ("01.pdf","02.pdf","03.txt"):(self.root/name).touch()
        with patch("refinement.read") as rd:
            s,_=self.run_app(True);self.assertFalse(s.groups);rd.assert_not_called()
        for name in ("안개꽃_시안.docx","안개꽃_견적.xlsx","안개꽃_사진.jpg"):(self.root/name).touch()
        s,fs=self.run_app()
        self.assertEqual(len(s.groups),1)
        self.assertEqual({f.name.split("_")[0] for f in s.groups[0].members},{"안개꽃"})
    def test_feedback_assign_merge_split_rename(self):
        s,fs=self.run_app()
        net=fs["DNS_실습.pptx"].group
        feedback.rename(s,net,"통신 수업");s,fs=self.run_app()
        self.assertEqual(fs["DNS_실습.pptx"].group.title,"통신 수업")
        feedback.assign(s,[fs["01.txt"]],fs["DNS_실습.pptx"].group);s,fs=self.run_app()
        self.assertEqual(fs["01.txt"].group.title,"통신 수업")
        feedback.split(s,fs["01.txt"].group,[fs["01.txt"],fs["DNS_실습.pptx"]],"별도 과제")
        s,fs=self.run_app();self.assertEqual(fs["01.txt"].group.title,"별도 과제")
        self.assertNotEqual(fs["01.txt"].group,fs["02_TCP_IP.pdf"].group)
        feedback.merge(s,fs["01.txt"].group,fs["02_TCP_IP.pdf"].group)
        s,fs=self.run_app();self.assertIs(fs["01.txt"].group,fs["02_TCP_IP.pdf"].group)
        feedback.assign(s,[fs["01.txt"]],None)
        s,fs=self.run_app(True);self.assertIsNone(fs["01.txt"].group);self.assertNotIn(fs["01.txt"].index,s.attempted)
    def test_pair_constraints_and_conflicts(self):
        s,f=self.run_app();a,b,c=f["DNS_실습.pptx"],f["01.txt"],f["IMG_2031.jpg"]
        feedback.save_edit(s,relation=(a,b,"must"));s,f=self.run_app()
        self.assertIs(f[a.name].group,f[b.name].group)
        feedback.save_edit(s,relation=(f[b.name],f[c.name],"must"));s,f=self.run_app()
        with self.assertRaises(ValueError):feedback.save_edit(s,relation=(f[a.name],f[c.name],"cannot"))
        self.assertIs(f[a.name].group,f[c.name].group)
        feedback.save_edit(s,relation=(f[a.name],f["02_TCP_IP.pdf"],"cannot"));s,f=self.run_app(True)
        self.assertIsNot(f[a.name].group,f["02_TCP_IP.pdf"].group)
        feedback.save_edit(s,relation=(f[a.name],f["02_TCP_IP.pdf"],"clear"));s,f=self.run_app()
        self.assertFalse(any(kind=="cannot" for _,_,kind in s.rules.rules.relations))
    def test_mixed_subject_and_actual_group_transfer(self):
        mixed=self.root/"네트워크_영양학_과제.txt"
        mixed.write_text("영양학 단백질 탄수화물 네트워크 TCP DNS",encoding="utf-8")
        s,f=self.run_app(True)
        self.assertEqual(f[mixed.name].first_band,"중간")
        self.assertIsNone(f[mixed.name].group)
        net=f["DNS_실습.pptx"].group;nut=f["단백질_실습.pptx"].group
        feedback.assign(s,[f["DNS_실습.pptx"]],nut)
        s,f=self.run_app()
        self.assertIs(f["DNS_실습.pptx"].group,f["단백질_실습.pptx"].group)
        self.assertIsNot(f["DNS_실습.pptx"].group,f["02_TCP_IP.pdf"].group)
        feedback.create(s,[f[mixed.name]],"융합 과제")
        s,f=self.run_app(True)
        self.assertEqual(f[mixed.name].group.title,"융합 과제")
        self.assertNotIn(f[mixed.name].index,s.attempted)
    def test_cannot_link_retains_two_confident_anchors(self):
        s,f=self.run_app(True);a,b=f["DNS_실습.pptx"],f["02_TCP_IP.pdf"]
        feedback.save_edit(s,relation=(a,b,"cannot"));s,f=self.run_app(True)
        self.assertIsNotNone(f[a.name].group);self.assertIsNotNone(f[b.name].group)
        self.assertIsNot(f[a.name].group,f[b.name].group)
    def test_context_and_move_undo(self):
        from models import DownloadContext
        s,f=self.run_app()
        x=f["단백질_실습.pptx"]
        feedback.record_download(x.uid,DownloadContext("https://example.edu/lms/42","example.edu","수업 자료","2026-11-16T10:00:00+09:00"))
        s,f=self.run_app();self.assertEqual(f[x.name].download.page_title,"수업 자료")
        dest=Path(self.tmp.name)/"정리함";dest.mkdir()
        original=x.path.read_bytes();storage.move([x],dest);self.assertFalse(x.path.exists())
        log,_=storage.latest();storage.undo(log);self.assertEqual(x.path.read_bytes(),original)
        s,f=self.run_app();self.assertEqual(f[x.name].uid,x.uid)

    def test_course_chapters_and_reference_publication_years(self):
        self.root=storage.HOME/"강의";self.root.mkdir()
        crypto={"01_암호학개론.pdf","02_스트림암호.pdf","03_블록암호와_AES.pptx"}
        nutrition={"식생활_영양_지침.pdf","2020_영양과건강_식품구성.pdf","2025_영양섭취기준.pdf"}
        for name in crypto|nutrition:(self.root/name).touch()
        s,f=self.run_app()
        self.assertEqual({frozenset(x.name for x in g.members) for g in s.groups},{frozenset(crypto),frozenset(nutrition)})
        p=self.root/"2025학년도_네트워크_과제.pdf";p.touch()
        q=self.root/"2026학년도_네트워크_과제.pdf";q.touch()
        s,f=self.run_app();self.assertLess(s.primary[f[p.name].index][f[q.name].index],60)

    def test_lecture_attachment_keys_need_independent_posts(self):
        from models import DownloadContext
        from course_source import prepare,relation,hint
        def entry(key,post,file):
            url=f"https://campus.example/download?ky={key}&CONTENT_SEQ={post}&FILE_SEQ={file}&LECTURE_MAIN_DIV=L"
            return SimpleNamespace(download=DownloadContext(url),referrer_hint=None)
        a,b,c,d=[entry(k,p,n) for n,(k,p) in enumerate([("A",1),("A",2),("B",8),("B",9)])]
        prepare([a,b]);self.assertEqual(relation(a,b),0)
        prepare([a,b,c,entry("B",8,99)]);self.assertEqual(relation(a,b),0)
        prepare([a,b,c,d]);self.assertEqual(relation(a,b),1);self.assertEqual(relation(a,c),-1)
        self.assertIsNone(hint("https://campus.example/download?ky=A&user=U"))
        a.referrer_hint=hint("https://portal.example/courses/83/files")
        b.download.url="https://portal.example/download?course_id=83"
        c.download.url="https://elsewhere.example/download?course_id=83"
        prepare([a,b,c]);self.assertEqual(relation(a,b),1);self.assertEqual(relation(a,c),0)

    def test_distinct_lecture_sources_separate_overlapping_sequences(self):
        from models import DownloadContext
        self.root=storage.HOME/"강의";self.root.mkdir()
        names=("lec01_introduction.pdf","lec02_history.pdf","lec03_discussion.pdf",
               "week01_introduction.pdf","week02_history.pdf","week03_discussion.pdf")
        for name in names:(self.root/name).touch()
        s,f=self.run_app()
        for i,name in enumerate(names):
            course=23 if i<3 else 42
            feedback.record_download(f[name].uid,DownloadContext(f"https://lms.example/courses/{course}/files/{i}","lms.example"))
        s,f=self.run_app(True)
        self.assertEqual({frozenset(x.name for x in g.members) for g in s.groups},{frozenset(names[:3]),frozenset(names[3:])})
        self.assertFalse(s.attempted)

        a,b=f[names[0]],f[names[3]]
        with self.assertRaises(feedback.CourseConflict):
            feedback.save_edit(s,relation=(a,b,"must"))
        with self.assertRaises(feedback.CourseConflict):
            feedback.merge(s,a.group,b.group)
        after=feedback.load(s.files)
        self.assertEqual(after.revision,s.revision)
        self.assertFalse(after.relations or after.pins or after.names)
        feedback.save_edit(s,relation=(a,b,"must"),allow_cross_course=True)
        s,f=self.run_app(True);a,b=f[a.name],f[b.name]
        self.assertIs(a.group,b.group)
        self.assertEqual((a.group.title_kind,a.group.title),("conflict","과목명 확인 필요"))
        self.assertIsNone(a.confidence)
        self.assertIsNone(a.group.confidence)
        feedback.save_edit(s,relation=(a,b,"clear"))
        s,f=self.run_app(True)
        self.assertEqual({frozenset(x.name for x in g.members) for g in s.groups},{frozenset(names[:3]),frozenset(names[3:])})
        self.assertTrue(all(m.confidence is not None for g in s.groups for m in g.members))

    def test_browser_download_record_joins_real_file_and_names_group(self):
        from contextlib import closing
        from datetime import datetime, timezone
        import sqlite3
        import capture_host
        from models import DownloadContext
        from course_titles import find_title
        self.root=storage.HOME/"download";self.root.mkdir()
        names=("week01_고지도.pdf","week02_지명.pptx")
        for name in names:(self.root/name).write_bytes(b"example")
        s,files=self.run_app()
        a=files[names[0]]
        # Existing installations use five fields of metadata plus the UID.
        db_path=storage.HOME/"feedback.sqlite3"
        with closing(sqlite3.connect(db_path)) as db:
            db.execute("ALTER TABLE downloads DROP COLUMN course_name")
        for f in files.values():
            feedback.record_download(f.uid,DownloadContext("https://clc.chosun.ac.kr/courses/923/files","clc.chosun.ac.kr"))
        msg=dict(type="download",pageOrigin=capture_host.ORIGIN,path=str(a.path),
                 endTime=datetime.now(timezone.utc).isoformat(),size=a.size,pageTitle="1주차 자료 | e-Class",courseName="지도와 도시")
        with patch.object(storage,"downloads_folder",return_value=self.root):
            self.assertTrue(capture_host.capture(msg)["ok"])
            self.assertTrue(capture_host.capture(msg)["ok"])
            self.assertTrue(capture_host.capture(dict(msg,path=str(storage.HOME/"other.txt")))["skip"])
            self.assertTrue(capture_host.capture(dict(msg,size=a.size+1))["skip"])
            self.assertTrue(capture_host.capture(dict(msg,pageOrigin="https://other.invalid"))["skip"])
        s,files=self.run_app()
        a,b=files[names[0]],files[names[1]]
        self.assertEqual((a.download.course_name,a.download.page_title,a.host),("지도와 도시","1주차 자료 | e-Class","clc.chosun.ac.kr"))
        self.assertIs(a.group,b.group)
        self.assertEqual((a.group.title,a.group.title_kind),("지도와 도시","lms"))
        self.assertEqual({p.target.parent.name for p in storage.plan_group_folders(s,a.group)},{"지도와 도시"})
        b.download.course_name="다른 강좌"
        self.assertEqual(find_title([a,b],False)[2],"conflict")
        a.download.course_name=""
        self.assertNotEqual(find_title([a],False)[2],"lms")

    def test_projects_without_school_or_extension(self):
        self.root=storage.HOME/"받은 파일";self.root.mkdir()
        project={"별빛전시_포스터.png","별빛전시_견적.xlsx","별빛전시_공간배치도.dwg"}
        trip={"제주여행_항공권.pdf","제주여행_숙소예약.txt","제주여행_일정표.xlsx"}
        noise={"01.pdf","IMG_0173.jpg","보고서_우박.txt","보고서_종이컵.png","보고서_다람쥐.zip"}
        for name in project|trip|noise:(self.root/name).touch()
        study,files=self.run_app(True)
        self.assertEqual({g.title:frozenset(f.name for f in g.members) for g in study.groups},
                         {"별빛전시":project,"제주여행":trip})
        self.assertTrue(all(files[n].group is None for n in noise))
        self.assertEqual({row.target.parent.name for row in storage.plan_group_folders(study)},{"별빛전시","제주여행"})

    def test_other_lms_course_records_without_school_dictionary(self):
        from datetime import datetime,timezone
        from capture_host import capture
        from course_source import hint
        self.root=storage.HOME/"외부 강좌";self.root.mkdir()
        names=("01.pdf","02.txt","03.pptx","04.pdf","05.txt","06.pptx")
        for name in names:(self.root/name).touch()
        for u,expected in [("https://campus.example.edu/courses/83/files/5","83"),
                           ("https://campus.example.edu/course/view.php?id=72","72")]:
            self.assertEqual(hint(u)[1],expected)
        self.assertIsNone(hint("https://campus.example.edu/mod/resource/view.php?id=72"))
        origin="https://learning.example.edu"
        now=datetime.now(timezone.utc).isoformat()
        with patch.object(storage,"downloads_folder",return_value=self.root):
            for i,name in enumerate(names):
                course="도시 경관 읽기" if i<3 else "소리의 역사"
                msg=dict(type="download",path=str(self.root/name),size=0,endTime=now,
                         pageOrigin=origin,pageTitle="자료실",courseName=course,courseId="")
                if i==0:
                    self.assertTrue(capture(msg)["skip"])
                    self.assertTrue(capture(dict(type="enable-site",pageOrigin=origin))["ok"])
                self.assertTrue(capture(msg)["ok"])
        study,_=self.run_app(True)
        self.assertEqual({g.title:frozenset(f.name for f in g.members) for g in study.groups},
                         {"도시 경관 읽기":set(names[:3]),"소리의 역사":set(names[3:])})
        self.assertEqual({g.title_kind for g in study.groups},{"lms"})

    def test_course_conflict_through_unlabelled_file(self):
        from models import DownloadContext
        s,files=self.run_app()
        a,b,c=(files[name] for name in ("DNS_실습.pptx","01.txt","02_탄수화물.pdf"))
        for f,course in ((a,1),(c,2)):
            feedback.record_download(f.uid,DownloadContext(f"https://school.example/courses/{course}/files"))
        s,files=self.run_app()
        feedback.save_edit(s,relation=(files[a.name],files[b.name],"must"))
        s,files=self.run_app()
        with self.assertRaises(feedback.CourseConflict):
            feedback.save_edit(s,relation=(files[b.name],files[c.name],"must"))
        self.assertEqual(len(feedback.load(s.files).relations),1)

if __name__=="__main__":unittest.main()
