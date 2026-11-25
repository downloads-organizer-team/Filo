"""Classify first, then name groups using optional, bounded course-cover evidence."""
from pathlib import Path
from time import perf_counter
from models import Study
from scanner import scan
from features import extract
from similarity import prepare
from matrix import build
from clustering import agglomerate
from candidates import make,assign_title
from confidence import detect
from refinement import refine,summarize
from constraints import Constraints
from eligibility import identify_files, eligible_groups
from existing_folders import recommend
from storage import plan_group_folders
import feedback

def discover_relations(root,recursive=False,deep=True,stop=lambda:None,status=lambda text:None,*,course_covers=None,roots=None,min_confidence=.7):
    start=perf_counter()
    s=Study(Path(root).absolute(),deep)
    s.min_confidence=min_confidence
    s.roots=[Path(p).absolute() for p in roots] if roots is not None else [s.root]
    status("파일 스캔 중");scan(s,recursive,stop)
    status("고유 파일과 사본 확인 중");identify_files(s.files,stop)
    status("파일명과 메타데이터 분석 중");extract(s.files,stop)
    saved=feedback.load(s.files);s.revision=saved.revision
    rules=Constraints(s.files,saved);s.rules=rules
    rules.hold.update(f.index for f in s.files if f.hold_reason)
    prepare(s);build(s,stop,status)
    status("완전 연결 계층 클러스터링 중")
    provisional=make(s,agglomerate(s,rules,stop),rules)
    status("이웃과 경쟁 묶음을 비교하는 중")
    s.groups=detect(s,provisional,rules)
    status("중간 신뢰도 파일의 문서 일부를 확인하는 중")
    refine(s,rules,stop);summarize(s)
    status("그룹별 과목명 확인 중")
    read_covers=deep if course_covers is None else course_covers
    for group in s.groups:
        stop()
        assign_title(s,group,saved,read_covers)
        if group.title_kind in {"activity","batch"}:
            for file in group.members:
                if file.state=="1차 추천":file.note=group.title_note
    s.groups.sort(key=lambda g:(g.title,g.gid))
    s.ms=round((perf_counter()-start)*1000)
    return s


def analyze(root,recursive=False,deep=True,stop=lambda:None,status=lambda text:None,*,course_covers=None,
            roots=None,min_confidence=.7,folder_mode="new"):
    study = discover_relations(root,recursive,deep,stop,status,course_covers=course_covers,
                               roots=roots,min_confidence=min_confidence)
    study.folder_mode = folder_mode
    if folder_mode == "reuse":
        status("기존 폴더와 파일 이름 대조 중")
        recommend(study,stop)
    eligible_groups(study,plan_group_folders(study,mode=folder_mode))
    summarize(study)
    study.groups.sort(key=lambda g:(g.title,g.gid))
    return study
