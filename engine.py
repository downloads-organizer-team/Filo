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
import feedback

def analyze(root,recursive=True,deep=True,stop=lambda:None,status=lambda text:None,*,course_covers=None):
    start=perf_counter()
    s=Study(Path(root).resolve(),deep)
    status("파일 스캔 중");scan(s,recursive,stop)
    status("파일명과 메타데이터 분석 중");extract(s.files,stop)
    saved=feedback.load(s.files);s.revision=saved.revision
    rules=Constraints(s.files,saved);s.rules=rules
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
    s.groups.sort(key=lambda g:(g.title,g.gid))
    s.ms=round((perf_counter()-start)*1000)
    return s
