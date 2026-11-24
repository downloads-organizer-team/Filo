"""Recognize activity names independently of word order and document roles."""
from collections import defaultdict
from dataclasses import dataclass
import re
import unicodedata

from features import TASK_GENERIC, TERMS, VERSION

ATTACHMENT = re.compile(r"[\[(]?\s*(?:붙임|별첨|첨부)\s*\d+\s*[\])._-]?\s*", re.I)
EDITION = re.compile(r"[\[(]?\s*제\s*\d+\s*회\s*[\])]?\s*")
COHORT = re.compile(r"(?<![a-z])([a-z]{2,10})[ _-]*(\d{1,2})(?:\s*기|th\b|(?=[\]\s_\-.(]|$))", re.I)
TEAM = re.compile(r"(?:팀[ _]+프로젝트|팀명)\s*[:_ -]+\s*([가-힣]{2,12})|(?:^|[\s\[_(-])([가-힣]{2,12})팀(?:[\]\s_)-]|$)")
PROJECT = re.compile(r"(?<![가-힣a-z])([가-힣a-z]{2,20})[ _-]+프로젝트", re.I)
WORD = re.compile(r"[^\W_]+")
NOISE = TASK_GENERIC | {"붙임","첨부","양식","신청서","참가신청서","작성자","무제","최종본","사본","팀","팀명"}
UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", re.I)


def display(text):
    return unicodedata.normalize("NFKC", text)


def words(text):
    return tuple(WORD.findall(display(text).casefold()))


def opaque_format(stem):
    stem = re.sub(r"\s*\(\d+\)$","",stem).strip()
    if UUID.fullmatch(stem):
        return "uuid",36,(8,4,4,4,12)
    parts=re.split(r"[-_]",stem)
    compact="".join(parts)
    if len(compact)<8 or len(set(compact.casefold()))<6 or not re.fullmatch(r"[a-zA-Z0-9]+",compact):
        return None
    if compact.isdecimal() and len(compact)>=16:
        kind="digits"
    elif re.fullmatch(r"[a-fA-F0-9]+",compact) and any(c.isdigit() for c in compact):
        kind="hex"
    elif len(re.findall(r"\d+[a-z]|[a-z]+\d",compact,re.I))>=3:
        kind="alnum"
    else:
        return None
    return kind,len(compact),tuple(map(len,parts))


def event_title(stem):
    if not (ATTACHMENT.search(stem) or EDITION.search(stem)):
        return ""
    stem = EDITION.sub("", ATTACHMENT.sub("", stem))
    for part in re.split(r"[\[\]()_]| - ", stem):
        part = part.strip(" .-")
        part=re.sub(r"\s+(?:참가\s*신청서|취약점\s*신고서|안내문|제출\s*양식|양식)(?:\s.*)?$","",part)
        if len(words(part)) >= 2 and set(words(part)) - NOISE and not re.search(r"양식|신청서|신고서", part):
            return part
    return ""


@dataclass(frozen=True)
class Activity:
    title: str
    kind: str
    edition: str = ""


def activities(files):
    stems = [display(f.path.stem) for f in files]
    teams = set()
    events = set()
    cohorts = defaultdict(set)
    for stem in stems:
        for m in TEAM.finditer(stem):
            team=next(v for v in m.groups() if v)
            team=re.sub(r"(?:레드|블루)$","",team)
            if team and team not in NOISE:teams.add(team)
        if title := event_title(stem):
            events.add(title)
        for code, number in COHORT.findall(stem):
            if code.lower() not in NOISE and not re.fullmatch(r"img|dsc|scan|unit|ver|rev|cve|iso", code, re.I):
                cohorts[code.upper()].add(number)
    # Only a marked cohort (brackets, 기, etc.) establishes an acronym as a program.
    marked = {m[1].upper() for stem in stems for m in COHORT.finditer(stem)
              if "기" in m[0] or stem[m.end():].startswith("]")}
    tags=set()
    excluded=NOISE|TERMS|{"pdf","docx","pptx","zip","jpg","png"}
    for stem in stems:
        for tag in re.findall(r"\[([A-Z]{2,8})\]",stem):
            if tag.casefold() not in excluded:
                tags.add(tag)
    # A bracketed program tag can also recur without a cohort number.
    marked.update(tag for tag in tags if sum(bool(re.search(r"(?<![a-z])"+tag+r"(?![a-z])",s,re.I))
                                             for s in stems)>=2)
    codes = sorted(marked, key=lambda x: (-len(x), x))
    program = re.compile(r"(?<![a-z])(" + "|".join(map(re.escape, codes)) + r")(?![a-z])", re.I) if codes else None
    event_names=sorted(events,key=lambda t:(-len(t),t))
    team_names=[(t,re.compile(r"(?<![가-힣])"+re.escape(t)+r"(?=레드팀|블루팀|팀|[^가-힣]|$)"))
                for t in sorted(teams,key=lambda t:(-len(t),t))]
    result = []
    for stem in stems:
        folded = stem.casefold()
        event = next((t for t in event_names if t.casefold() in folded), None)
        team = next((t for t,pattern in team_names if pattern.search(stem)),None)
        project = PROJECT.search(stem)
        if event:
            edition = EDITION.search(stem)
            result.append(Activity(event, "행사", re.search(r"\d+", edition[0])[0] if edition else ""))
        elif team:
            result.append(Activity(team, "팀"))
        elif project and project[1].casefold() not in NOISE:
            year = re.search(r"(?<!\d)20\d\d(?!\d)", stem)
            result.append(Activity(project[1]+" 프로젝트", "프로젝트", year[0] if year else ""))
        elif program and (matches := list(program.finditer(stem))):
            programs=set()
            for match in matches:
                code=match[0].upper()
                cohort=COHORT.match(stem,match.start())
                edition=cohort[2] if cohort else next(iter(cohorts[code])) if len(cohorts[code])==1 else ""
                programs.add((code,edition))
            if len(programs)==1:
                code,edition=programs.pop()
                result.append(Activity(code,"프로그램",edition))
            else:
                title=" · ".join(code+(" "+n+"기" if n else "") for code,n in sorted(programs))
                result.append(Activity(title,"프로그램"))
        else:
            result.append(None)
    return result


def activity_relation(a, b):
    if a is None and b is None:
        return 0
    if a and b and a.title.casefold() == b.title.casefold() and not (a.edition and b.edition and a.edition != b.edition):
        return 1
    return -1


def common_phrase(members, shared):
    """Preserve the spelling and order of a shared phrase, including internal roles."""
    rows = [WORD.findall(VERSION.sub(" ", display(f.path.stem))) for f in members]
    keys = [tuple(w.casefold() for w in row) for row in rows]
    first = min(range(len(rows)), key=lambda i: len(rows[i]))
    tokens = keys[first]
    common = set(shared)
    for width in range(min(12,len(tokens)), 0, -1):
        for start in range(len(tokens)-width+1):
            part=tokens[start:start+width]
            if part[0] not in common or part[-1] not in common:
                continue
            if all(any(row[i:i+width]==part for i in range(len(row)-width+1)) for row in keys):
                return " ".join(rows[first][start:start+width])
    return ""
