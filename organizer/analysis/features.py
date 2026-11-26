import json
import os
import re
import unicodedata
from collections import defaultdict
from itertools import groupby
from pathlib import Path
from urllib.parse import urlsplit
from organizer.models import DownloadContext
from organizer.analysis.course_source import hint as course_hint
from organizer.analysis.scan_progress import tracked

LEXICON = json.loads(Path(__file__).with_name("terms.json").read_text(encoding="utf-8"))
ROLES = set("과제 실습 강의 보고서 기말 중간 제출물 프로젝트 발표 제안서 회의록 견적 예산 자료 요약 결과 참고 사진 안내 파일 첨부 정리 기록 노트 메모 실험 설명서 lab lecture report project assignment homework final notes note draft slides proposal budget".split())
GENERIC = set("개론 개요 기초 입문 분석 문서 수업 계획서 소개 강의소개 강의계획서 과목소개 공통 제목없음 scan img dsc untitled document screenshot data 파일 appendix appendix1 chap chapter ch week wk lec practice introduction syllabus orientation".split()) | ROLES
COMMON_PREFIXES={"다운로드","download","downloads","screenshot","스크린샷","image","이미지","제목 없음","attachment"}
# A document type describes its purpose across many unrelated clients and projects.
DOCUMENT_TYPES={"영수증","청구서","견적서","발주서","납품서","인수증","계약서","명세서","신청서",
                "receipt","invoice","quotation","estimate","contract","statement","form","forms","application",
                "documents","minutes","memo"}
TASK_GENERIC=COMMON_PREFIXES|GENERIC|DOCUMENT_TYPES|{"여행","travel","trip","vacation","holiday","업무","작업","받은 파일",
    "항공권","숙소","예약","숙소예약","일정","일정표","itinerary","booking","reservation","ticket","hotel",
    "무제","제목없음","제목","없음","붙임","별첨","양식","제출","작성자","사본","강의자료","작성","제출자"}
ALIASES = {"춘계축제":"봄축제","봄축전":"봄축제","dataanalytics":"데이터분석","springfestival":"봄축제","와이어샤크":"wireshark","packet":"패킷","network":"네트워크","networking":"네트워크","nutrition":"영양학","protein":"단백질","carbohydrate":"탄수화물"}
VERSION = re.compile(r"\(\s*\d+\s*\)|진짜\s*최종(?:본)?\d*|최종(?:본)?\d*|수정(?:본)?\d*|(?<![a-z])(?:final|copy|version|ver|rev|v)\s*\d*(?![a-z])",re.I)
TASK_SEPARATOR = re.compile(r"\s*_+\s*|\s+[-–—]\s+")
PREFIX = re.compile(r"^\s*(\d{1,3}(?:[-.]\d{1,2})?)(?=[\s_.-]|$)")
SERIES = re.compile(r"(?:(\d{1,3})\s*(주차|회차|강(?!의))|(?<![a-z0-9])(week|wk|w|lecture|lec|chapter|chap|ch|practice|episode|ep)[ _.-]*(\d{1,3}))(?!\d)")
YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
ACADEMIC_YEAR = re.compile(r"(?<!\d)(20\d{2})\s*(?:학년도|학번|(?:년\s*)?[-_. ]?\s*[12]\s*학기)")
ATOMS = re.compile(r"[a-z]+[0-9]*|[가-힣]+[a-z0-9]*|[0-9]+|[^\W_]+",re.I)
TERMS = {w for ws in LEXICON.values() for w in ws}
SPLIT = re.compile("("+"|".join(map(re.escape,sorted({w for w in TERMS|ROLES|GENERIC if re.fullmatch("[가-힣]+",w) and len(w)>=2},key=lambda w:(-len(w),w))))+")")

def clean(text):
    text=unicodedata.normalize("NFKC",text).casefold()
    return re.sub(r"spring[ _-]+festival","springfestival",re.sub(r"data[ _-]+analytics","dataanalytics",text))

def tokenize(text):
    result=[]
    for word in ATOMS.findall(clean(text)):
        if word in ALIASES:word=ALIASES[word]
        # Keep identifiers such as 프로젝트A and 과제01 intact.
        chunks = SPLIT.split(word) if re.fullmatch("[가-힣]+",word) else [word]
        for part in chunks:
            if len(part)<2 or part.isdecimal() or re.fullmatch(r"(img|dsc|scan|untitled|무제)\d+",part):continue
            result.append(ALIASES.get(part,part))
    return result

def filename(f):
    text=clean(f.path.stem);f.ext=f.path.suffix.lower().lstrip(".")
    f.versions=tuple(m.group().strip() for m in VERSION.finditer(text))
    text=VERSION.sub(" ",text)
    f.numbers=tuple(re.findall(r"\d+(?:-\d+)?",text))
    yr=YEAR.search(text);f.year=int(yr[1]) if yr else None
    academic=ACADEMIC_YEAR.search(text);f.academic_year=int(academic[1]) if academic else None
    s=SERIES.search(text);pre=PREFIX.match(text)
    if s:
        tag=s[2] or s[3];f.sequence=s[0];f.number=int(s[1] or s[4])
        f.pattern="주차" if tag in {"주차","week","wk","w"} else "강의" if tag in {"강","lecture","lec"} else "회차"
        text=text[:s.start()]+" "+text[s.end():]
    elif pre:
        f.sequence=pre[1];f.pattern="순번";f.number=int(re.split(r"[.-]",pre[1])[0]);text=text[pre.end():]
    else:
        tail=re.search(r"(?:[\s_.-]|(?P<stem>[a-z가-힣]{2,}))(\d{1,3})$",text.strip())
        if tail and tail["stem"] not in {"과제","프로젝트","팀","team","prj","project","img","dsc","scan"}:
            f.sequence=tail[2];f.number=int(tail[2]);f.pattern="순번"
            text=text[:tail.start(2)]
    text=YEAR.sub(" ",text)
    words=tokenize(text)
    f.tokens=tuple(dict.fromkeys(words))
    f.normalized=" ".join(words)
    roles=[x for x in words if x in ROLES]
    if s and s[3]=="practice":roles.append("실습")
    if any(v.startswith("final") for v in f.versions):roles.append("final")
    f.roles=tuple(dict.fromkeys(roles))

def task_name(stem):
    parts=TASK_SEPARATOR.split(VERSION.sub("",clean(stem)),maxsplit=1)
    if len(parts)!=2:return "",""
    head,tail=(p.strip() for p in parts)
    # A role suffix can vary while the identifying place or project stays intact.
    name=re.sub(r"\s*여행$","",head).strip() if head.endswith("여행") else head
    words=set(tokenize(name))-TASK_GENERIC
    if (len(name)>=2 and head not in TASK_GENERIC and words and not SERIES.search(head) and not head[:1].isdigit()
            and any(c.isalpha() for c in tail) and re.fullmatch(r"[\w -]+",head)):
        return name,tail
    return "",""

def task_prefixes(files):
    """Recognize a repeated task name before a delimiter across distinct deliverables."""
    prefixes=[]
    tails={}
    for f in files:
        prefix,tail=task_name(f.path.stem)
        if prefix:tails.setdefault(prefix,set()).add(tail)
        prefixes.append(prefix)
    return [p if p and len(tails[p])>=2 else "" for p in prefixes]


def numbered_series(files):
    """Find runs with an unambiguous episode title and recurring deliverables."""
    buckets = defaultdict(lambda: defaultdict(list))
    for f in files:
        if f.hold_reason or not f.ext or f.number is None:
            continue
        stem = VERSION.sub(" ", clean(f.path.stem))
        marker = SERIES.search(stem)
        if not marker:
            continue
        prefix = stem[:marker.start()].strip(" ._-")
        title = re.sub(r"[\W_]+", "", stem[marker.end():])
        if not title or not any(c.isalpha() for c in title):
            continue
        tag = marker[2] or marker[3]
        buckets[f.path.parent, prefix, tag][f.number].append((title, f))

    result = [None] * len(files)
    for (_, prefix, _), slots in buckets.items():
        # A repeated slot with different titles can signal interleaved courses.
        if any(len({title for title, _ in rows}) != 1 for rows in slots.values()):
            continue
        named = bool(set(tokenize(prefix)) - TASK_GENERIC)
        # A lone file at the edge of an unnamed series should not veto the run.
        supported = sorted(n for n, rows in slots.items() if named or len({f.ext for _, f in rows}) >= 2)
        for _, run in groupby(enumerate(supported), key=lambda pair: pair[1] - pair[0]):
            numbers = [number for _, number in run]
            if len(numbers) < 3:
                continue
            formats = [{f.ext for _, f in slots[n]} for n in numbers]
            if not named and len(set.intersection(*formats)) < 2:
                continue
            if len({slots[n][0][0] for n in numbers}) < 3:
                continue
            members = [f for n in numbers for _, f in slots[n]]
            if len({f.course_scope for f in members if f.course_scope}) > 1:
                continue
            series_id = min(f.index for f in members)
            for f in members:
                result[f.index] = series_id
    return result

def zone_transfer(path):
    if os.name!="nt":return {}
    try:
        with open(str(path)+":Zone.Identifier","rb") as stream:data=stream.read(32768)
        enc="utf-16" if data.startswith((b"\xff\xfe",b"\xfe\xff")) else "utf-8-sig"
        return dict(line.split("=",1) for line in data.decode(enc,errors="replace").splitlines() if "=" in line)
    except (OSError,ValueError):return {}


def download_context(f):
    if f.offline:return
    values=zone_transfer(f.path)
    if not values:return
    try:
        f.referrer_hint=course_hint(values.get("ReferrerUrl",""))
        for field in ("HostUrl","ReferrerUrl"):
            url=values.get(field,"");uri=urlsplit(url)
            if uri.scheme in ("http","https") and uri.hostname:
                chunks=uri.path.strip("/").split("/")
                f.download=DownloadContext(url,uri.hostname.casefold(),directory="/".join(chunks[:-1]) if len(chunks)>2 else "",
                                           source_page=values.get("ReferrerUrl",""))
                return
    except (OSError,ValueError):pass

def extract(files,stop,progress=None):
    for f in tracked(files,progress):
        stop();filename(f);download_context(f)
