import json
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit
from models import DownloadContext
from course_source import hint as course_hint

LEXICON = json.loads(Path(__file__).with_name("terms.json").read_text(encoding="utf-8"))
ROLES = set("과제 실습 강의 보고서 기말 중간 제출물 프로젝트 발표 제안서 회의록 견적 예산 자료 요약 결과 참고 사진 안내 파일 첨부 정리 기록 노트 메모 실험 설명서 lab lecture report project assignment homework final notes note draft slides proposal budget".split())
GENERIC = set("개론 개요 기초 입문 분석 문서 수업 계획서 소개 강의소개 강의계획서 과목소개 공통 제목없음 scan img dsc untitled document screenshot data 파일 appendix appendix1 chap chapter ch week wk lec practice introduction syllabus orientation".split()) | ROLES
COMMON_PREFIXES={"다운로드","download","downloads","screenshot","스크린샷","image","이미지","제목 없음","attachment"}
TASK_GENERIC=COMMON_PREFIXES|GENERIC|{"여행","travel","trip","vacation","holiday","업무","작업","받은 파일",
    "항공권","숙소","예약","숙소예약","일정","일정표","itinerary","booking","reservation","ticket","hotel"}
ALIASES = {"춘계축제":"봄축제","봄축전":"봄축제","dataanalytics":"데이터분석","springfestival":"봄축제","와이어샤크":"wireshark","packet":"패킷","network":"네트워크","networking":"네트워크","nutrition":"영양학","protein":"단백질","carbohydrate":"탄수화물"}
VERSION = re.compile(r"\(\s*\d+\s*\)|진짜\s*최종(?:본)?\d*|최종(?:본)?\d*|수정(?:본)?\d*|(?<![a-z])(?:final|copy|version|ver|rev|v)\s*\d*(?![a-z])",re.I)
TASK_SEPARATOR = re.compile(r"\s*_+\s*|\s+[-–—]\s+")
PREFIX = re.compile(r"^\s*(\d{1,3}(?:[-.]\d{1,2})?)(?=[\s_.-]|$)")
SERIES = re.compile(r"(?:(\d{1,3})\s*(주차|회차|강(?!의))|(?<![a-z])(week|wk|lecture|lec|chapter|chap|ch|practice)[ _.-]*(\d{1,3}))(?!\d)")
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
            if len(part)<2 or part.isdecimal() or re.fullmatch(r"(img|dsc|scan)\d+",part):continue
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
        f.pattern="주차" if tag in {"주차","week","wk"} else "강의" if tag in {"강","lecture","lec"} else "회차"
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

def download_context(f):
    if os.name!="nt" or f.offline:return
    try:
        with open(str(f.path)+":Zone.Identifier","rb") as stream:data=stream.read(32768)
        enc="utf-16" if data.startswith((b"\xff\xfe",b"\xfe\xff")) else "utf-8-sig"
        values=dict(line.split("=",1) for line in data.decode(enc,errors="replace").splitlines() if "=" in line)
        f.referrer_hint=course_hint(values.get("ReferrerUrl",""))
        for field in ("HostUrl","ReferrerUrl"):
            url=values.get(field,"");uri=urlsplit(url)
            if uri.scheme in ("http","https") and uri.hostname:
                chunks=uri.path.strip("/").split("/")
                f.download=DownloadContext(url,uri.hostname.casefold(),directory="/".join(chunks[:-1]) if len(chunks)>2 else "",
                                           source_page=values.get("ReferrerUrl",""))
                return
    except (OSError,ValueError):pass

def extract(files,stop):
    for f in files:
        stop();filename(f);download_context(f)
