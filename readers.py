"""Bounded, read-only excerpt providers. Register further formats in READERS."""
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from codecs import getincrementaldecoder
import posixpath
import sys
import re

LIMIT=2400
def plain(path):
    with path.open("rb") as f:data=f.read(8192)
    enc="utf-16" if data.startswith((b"\xff\xfe",b"\xfe\xff")) else "utf-8-sig"
    try:return getincrementaldecoder(enc)().decode(data,final=len(data)<8192)[:LIMIT]
    except UnicodeError:return data.decode("cp949",errors="replace")[:LIMIT]

def xml_prefix(z,name,tags,max_bytes):
    try:entry=z.open(name)
    except KeyError:return ""
    parser=ET.XMLPullParser(events=("end",))
    pieces=[];length=0
    with entry:
        scanned=b""
        for _ in range(max_bytes//2048):
            buf=entry.read(2048)
            if not buf:break
            check=(scanned+buf).upper()
            if b"<!DOCTYPE" in check or b"<!ENTITY" in check:return ""
            scanned=buf[-16:]
            parser.feed(buf)
            for _,node in parser.read_events():
                if node.tag.rsplit("}",1)[-1] in tags and node.text:
                    pieces.append(node.text);length+=len(node.text)
                node.clear()
                if length>=LIMIT:return " ".join(pieces)[:LIMIT]
    return " ".join(pieces)[:LIMIT]

def office(path):
    with ZipFile(path) as z:
        title=xml_prefix(z,"docProps/core.xml",{"title"},16384)
        if path.suffix.lower()==".docx":part="word/document.xml"
        elif path.suffix.lower()==".pptx":part="ppt/slides/slide1.xml"
        elif path.suffix.lower()==".hwpx":part="Contents/section0.xml"
        else:part="xl/sharedStrings.xml" if "xl/sharedStrings.xml" in z.namelist() else "xl/worksheets/sheet1.xml"
        return (title+" "+xml_prefix(z,part,{"t"},131072))[:LIMIT]

def pdf(path,*,cover_only=False):
    vendor=str(Path(__file__).with_name("vendor")/"pypdf.zip")
    if vendor not in sys.path:sys.path.insert(0,vendor)
    from pypdf import PdfReader
    with path.open("rb") as stream:
        reader=PdfReader(stream,strict=False)
        if reader.is_encrypted: return ""
        page=next(iter(reader.pages),None)
        text=page.extract_text() if page is not None else ""
        if cover_only:return (text or "")[:LIMIT]
        metadata=reader.metadata
        title=metadata.title or "" if metadata else ""
        return (title+" "+(text or ""))[:LIMIT]

INTRO=re.compile(r"(?:강의|과목|수업|교과목)\s*(?:개요|소개|계획서)|\bsyllabus\b|\borientation\b|\bOT\b|\bcourse[ -]*(?:overview|introduction)\b",re.I)
EARLY_INTRO=re.compile(r"(?:\[?(?:lec(?:ture)?|chap(?:ter)?|week)?[ .-]*0?[01]\]?[ .-]+)introduction",re.I)
COURSE_LABEL=re.compile(r"(?:교과목명|과목명|강좌명|course (?:title|name))\s*(?:[:：]\s*(.*)|\s+(.+))?",re.I)
AFFILIATION=re.compile(r"(?:대학교?|학과|학부|전공|대학원|\buniv\.?|\buniversity)\s*$|^(?:department of|faculty of|school of|college of)\b",re.I)
STAFF=re.compile(r"^(?:담당\s*교수|교수자|강사|교수|prof(?:essor)?\.?|instructor)\b|(?:교수|강사)\s*$",re.I)
SESSION_LABEL=re.compile(r"(?:제?\d+\s*)?(?:주차?|차시)\s*(?:별\s*)?(?:내용|자료)?|내용",re.I)
FIRST_WEEK=re.compile(r"(?<![0-9A-Za-z])(?:제\s*)?0*1\s*주(?:차)?\s*[._ -]*(?:제\s*)?0*1\s*차시|\bweek[ .-]*0*1\s*[ .-]*(?:lesson|lecture|session)[ .-]*0*1\b",re.I)

def usable_title(title):
    return (2<=len(title)<=80 and any(c.isalpha() for c in title)
            and not any(c in title for c in ("@","http://","https://"))
            and not AFFILIATION.search(title) and not STAFF.search(title) and not INTRO.fullmatch(title)
            and not SESSION_LABEL.fullmatch(title)
            and not re.match(r"^(?:chap(?:ter)?|ch|lec(?:ture)?|week)[ ._-]*\d|^제?\d+\s*(?:장|주|차시|강)",title,re.I)
            and title.casefold() not in {"introduction","수업","강의","학기","교수","교과목명","강의자료",
                                        "강의실","공지사항","과제","자료실","lms","dashboard",
                                        "powerpoint 프레젠테이션","powerpoint presentation","제목을 입력하십시오"})

def labelled_title(lines):
    for i,line in enumerate(lines):
        label=COURSE_LABEL.fullmatch(line)
        if label:
            name=(label[1] or label[2] or next(iter(lines[i+1:i+2]),"")).strip()
            if usable_title(name):return name
    return ""

def title_from_cover(text):
    lines=[" ".join(line.split()) for line in text.splitlines() if line.strip()][:12]
    explicit=labelled_title(lines)
    if explicit:return explicit
    for line in lines[:4]:
        if (AFFILIATION.search(line) or re.fullmatch(r"(?:20\d\d년?(?:학년도)?[ ./-]*)?(?:[12]\s*학기|(?:Spring|Fall)\s*20\d\d)|20\d\d",line,re.I)):
            continue
        return line if usable_title(line) else ""
    return ""

def package_xml(archive,part):
    entry=archive.getinfo(part)
    if entry.file_size>1024*1024:
        raise ValueError("슬라이드 XML 크기 한도 초과")
    data=archive.read(entry)
    # OOXML uses UTF-8 or UTF-16. Strip null bytes only for the declaration check.
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b",data.replace(b"\x00",b""),re.I):
        raise ValueError("지원하지 않는 XML 선언")
    return ET.fromstring(data)

def first_slide_part(archive):
    pres=package_xml(archive,"ppt/presentation.xml")
    slide=pres.find("./{*}sldIdLst/{*}sldId")
    if slide is None:return ""
    rid=next((v for k,v in slide.attrib.items() if k.endswith("}id")),None)
    rels=package_xml(archive,"ppt/_rels/presentation.xml.rels")
    for rel in rels:
        if (rid and rel.get("Id")==rid and rel.get("Type","").endswith("/slide")
                and rel.get("TargetMode","Internal")=="Internal"):
            target=rel.get("Target","")
            part=posixpath.normpath(posixpath.join("/ppt",target)).lstrip("/")
            if part.startswith("ppt/slides/") and part.endswith(".xml"):return part
    return ""

def pptx_course_title(path,*,intro):
    with ZipFile(path) as archive:
        part=first_slide_part(archive)
        if not part:return ""
        slide=package_xml(archive,part)

    labelled=set()
    headings=set()
    boxes={}
    has_byline=False
    for shape in slide.findall(".//{*}sp"):
        body=shape.find("./{*}txBody")
        if body is None:continue
        lines=[]
        for p in body.findall("./{*}p"):
            raw="".join((e.text or "") if e.tag.endswith("}t") else " "
                        for e in p.iter() if e.tag.endswith(("}t","}br")))
            if raw.strip():lines.append(" ".join(raw.split()))
        if not lines:continue
        explicit=labelled_title(lines)
        if explicit:labelled.add(explicit)
        if any(AFFILIATION.search(line) or STAFF.search(line) for line in lines):
            has_byline=True
            continue
        title=" ".join(lines)
        if not usable_title(title):continue
        ph=shape.find("./{*}nvSpPr/{*}nvPr/{*}ph")
        if ph is not None:
            if ph.get("type") in {"title","ctrTitle"}:headings.add(title)
        else:
            sizes=[int(size) for e in body.iter() if re.fullmatch(r"[0-9]{1,6}",size:=e.get("sz",""))]
            if sizes:boxes[title]=max(boxes.get(title,0),max(sizes))
    if labelled:return next(iter(labelled)) if len(labelled)==1 else ""
    if not (intro or has_byline):return ""
    if headings:return next(iter(headings)) if len(headings)==1 else ""
    if boxes:
        largest=max(boxes.values())
        top=[title for title,size in boxes.items() if size==largest]
        if len(top)==1:return top[0]
    return ""

def course_cover(members):
    candidates=[]
    for f in members:
        if f.ext not in {"pdf","pptx"} or f.offline or f.size>48*1024*1024:continue
        stem=f.path.stem.replace("_"," ")
        if INTRO.search(stem):priority=0
        elif EARLY_INTRO.fullmatch(stem):priority=1
        elif f.ext=="pptx" and FIRST_WEEK.search(stem):priority=2
        else:continue
        candidates.append((priority,f))
    if not candidates:return "","강의소개·OT 자료나 1주 1차시 PPTX를 찾지 못했습니다."
    priority,chosen=min(candidates,key=lambda item:(item[0],item[1].number if item[1].number is not None else 9999,item[1].name))
    chosen.course_cover_checked=True
    source=chosen.name+(" · 첫 슬라이드" if chosen.ext=="pptx" else " · 첫 페이지")
    try:
        if chosen.ext=="pptx":title=pptx_course_title(chosen.path,intro=priority<2)
        else:title=title_from_cover(pdf(chosen.path,cover_only=True))
    except Exception:
        title=""
    return title,source

READERS={"pdf":pdf,**dict.fromkeys(("docx","pptx","xlsx","hwpx"),office),
         **dict.fromkeys(("txt","md","csv","tsv","log"),plain)}
SUPPORTED=set(READERS)
def read(f):
    if f.ext not in READERS:return "","지원하지 않는 형식"
    if f.offline:return "","오프라인 파일"
    if f.ext in {"pdf","docx","pptx","xlsx","hwpx"} and f.size>48*1024*1024:return "","48MiB 크기 한도 초과"
    try:text=READERS[f.ext](f.path).strip()
    except Exception as error:
        return "",f"읽기 실패 ({type(error).__name__})"
    return text,"일부 판독" if text else "판독 가능한 텍스트 없음"
