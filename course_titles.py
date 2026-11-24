"""Find a course name after clustering, independently of membership scores."""
from collections import defaultdict
import re
import unicodedata

from features import GENERIC, VERSION
from readers import course_cover, labelled_title, usable_title


def key(text):
    return "".join(unicodedata.normalize("NFKC",text).casefold().split())


PREFIX=re.compile(r"^\s*(?:\d{1,3}[. )_-]+)?(.{2,70}?)[ _-]+(?:제?\d+\s*주(?:차|째)|강의\s*(?:보충|자료|\d)|(?:week|lecture|lec|chapter|chap)[ ._-]*\d)",re.I)


def find_title(members,read_covers,*,filename_prefix=True):
    if len({f.course_scope for f in members if f.course_scope})>1:
        return "","서로 다른 강좌 출처 · 과목명 확인 필요","conflict"

    page_titles={}
    prefixes=defaultdict(set)
    spellings={}
    for f in members:
        if f.download.course_name and usable_title(f.download.course_name):
            page_titles[key(f.download.course_name)]=f.download.course_name
        # A browser page title can also be a post title or the LMS brand.
        # Only an explicitly labelled course name is usable.
        lines=re.split(r"[|\n]",f.download.page_title or "")
        for line in lines:
            name=labelled_title([line.strip()])
            if name:page_titles[key(name)]=name
        match=PREFIX.match(f.path.stem) if filename_prefix else None
        if match:
            prefix=match[1].replace("_"," ").strip(" ._-")
            if usable_title(prefix) and key(prefix) not in GENERIC:
                token=key(prefix)
                prefixes[token].add(key(VERSION.sub("",f.path.stem)))
                spellings[token]=prefix
    repeated={k:spellings[k] for k,stems in prefixes.items() if len(stems)>=2}
    if len(page_titles)>1 or len(repeated)>1:
        return "","자료에 서로 다른 과목명 후보가 있어요 · 확인 필요","conflict"
    if page_titles:
        k,name=next(iter(page_titles.items()))
        if repeated and k not in repeated:
            return "","LMS 과목명과 파일명의 표기가 달라요 · 확인 필요","conflict"
        return name,"다운로드 당시 LMS에 표시된 과목명","lms"
    if read_covers:
        name,source=course_cover(members)
        if name:
            if repeated and key(name) not in repeated:
                return "","강의 표지와 파일명의 표기가 달라요 · 과목명 확인 필요","conflict"
            return name,"강의 표지에서 읽은 이름 · "+source,"cover"
    if repeated:
        k,name=next(iter(repeated.items()))
        return name,f"파일명 {len(prefixes[k])}개에 반복된 과목명 후보 · 확인 가능","filename"
    return "","","topic"
