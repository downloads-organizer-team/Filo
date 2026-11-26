"""Classify first, then name groups using optional, bounded course-cover evidence."""
from pathlib import Path
from collections import defaultdict
from uuid import uuid5, NAMESPACE_URL
from time import perf_counter
from models import Study, Group
from scanner import scan, check_directory
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
from storage import folder_name, plan_group_folders
from scan_progress import tracked
import feedback

def discover_relations(root,recursive=False,deep=True,stop=lambda:None,status=lambda text:None,*,course_covers=None,roots=None,min_confidence=.7,progress=None):
    start=perf_counter()
    s=Study(Path(root).absolute(),deep)
    s.min_confidence=min_confidence
    s.roots=[Path(p).absolute() for p in roots] if roots is not None else [s.root]
    status("파일 수집 중");scan(s,recursive,stop,progress)
    status("고유 파일과 사본 확인 중");identify_files(s.files,stop,progress)
    status("파일명과 메타데이터 분석 중");extract(s.files,stop,progress)
    status("파일 비교 준비 중")
    saved=feedback.load(s.files);s.revision=saved.revision
    rules=Constraints(s.files,saved);s.rules=rules
    rules.hold.update(f.index for f in s.files if f.hold_reason)
    prepare(s);build(s,stop,status,progress)
    provisional=make(s,agglomerate(s,rules,stop,status,progress),rules)
    status("후보 묶음 비교 중")
    s.groups=detect(s,provisional,rules,progress)
    refine(s,rules,stop,status,progress);summarize(s)
    status("그룹별 과목명 확인 중")
    read_covers=deep if course_covers is None else course_covers
    for group in tracked(s.groups,progress):
        stop()
        assign_title(s,group,saved,read_covers)
        if group.title_kind in {"activity","batch"}:
            for file in group.members:
                if file.state=="1차 추천":file.note=group.title_note
    s.groups.sort(key=lambda g:(g.title,g.gid))
    s.ms=round((perf_counter()-start)*1000)
    return s


def extension_study(root,roots,folder_mode,stop,status,progress=None):
    start=perf_counter()
    s=Study(Path(root).absolute(),False)
    s.roots=[Path(p).absolute() for p in roots] if roots else [s.root]
    s.folder_mode=folder_mode
    s.group_by="extension"
    status("파일 수집 중");scan(s,False,stop,progress)
    status("고유 파일과 사본 확인 중");identify_files(s.files,stop,progress)
    status("확장자 확인 중")
    saved=feedback.load(s.files)
    s.revision=saved.revision
    s.rules=Constraints(s.files,saved)
    buckets=defaultdict(list)
    for f in tracked(s.files,progress):
        f.ext=f.path.suffix[1:].lower()
        if f.hold_reason or not f.ext or f.index in s.rules.hold:
            f.note=f.hold_reason or ("사용자가 미분류로 지정" if f.ext else "확장자 없음")
            continue
        buckets[f.ext].append(f)
    status("확장자별로 묶는 중")
    for ext,members in tracked(sorted(buckets.items()),progress):
        stop()
        gid=str(uuid5(NAMESPACE_URL,"extension/"+str(s.root)+"/"+ext))
        title=folder_name(saved.names.get(gid,ext.upper()))
        g=Group(gid,title,members,title_kind="extension",title_note="확장자 · "+ext.upper())
        if folder_mode=="reuse":
            for parent in s.roots:
                try:
                    g.destination=check_directory(parent/title)
                    break
                except OSError:
                    continue
        for f in members:
            f.group=g;f.state="확장자 분류";f.note=g.title_note
        s.groups.append(g)
    status("이동 경로 확인 중")
    eligible_groups(s,plan_group_folders(s,mode=folder_mode,progress=progress))
    s.ms=round((perf_counter()-start)*1000)
    return s


def analyze(root,recursive=False,deep=True,stop=lambda:None,status=lambda text:None,*,course_covers=None,
            roots=None,min_confidence=.7,folder_mode="new",group_by="related",progress=None):
    if group_by=="extension":
        return extension_study(root,roots,folder_mode,stop,status,progress)
    study = discover_relations(root,recursive,deep,stop,status,course_covers=course_covers,
                               roots=roots,min_confidence=min_confidence,progress=progress)
    study.folder_mode = folder_mode
    if folder_mode == "reuse":
        recommend(study,stop,status,progress)
    status("이동 경로 확인 중")
    eligible_groups(study,plan_group_folders(study,mode=folder_mode,progress=progress))
    summarize(study)
    study.groups.sort(key=lambda g:(g.title,g.gid))
    return study
