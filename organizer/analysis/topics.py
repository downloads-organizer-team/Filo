"""Recognize activity names independently of word order and document roles."""
from collections import Counter, defaultdict
from dataclasses import dataclass
import re
import unicodedata

from organizer.analysis.features import TASK_GENERIC, TERMS, VERSION

ATTACHMENT = re.compile(r"[\[(]?\s*(?:붙임|별첨|첨부)\s*\d+\s*[\])._-]?\s*", re.I)
EDITION = re.compile(r"[\[(]?\s*제\s*\d+\s*회\s*[\])]?\s*")
COHORT = re.compile(r"(?<![a-z])([a-z]{2,10})[ _-]*(\d{1,2})(?:\s*기|th\b|(?=[\]\s_\-.(]|$))", re.I)
TEAM = re.compile(r"(?:팀[ _]+프로젝트|팀명)\s*[:_ -]+\s*([가-힣]{2,12})|(?:^|[\s\[_(-])([가-힣]{2,12})팀(?:[\]\s_)-]|$)")
PROJECT_PARTS = re.compile(r"[\[\](){}]|[ \t]+[-–—][ \t]+")
TAG = re.compile(r"\[([A-Z]{2,12})\]")
REFERENCE = re.compile(r"(?<![a-z0-9])([a-z]{2,8})-?([0-9]{3,10})(?![a-z0-9])", re.I|re.ASCII)
WORD = re.compile(r"[^\W_]+")
NOISE = TASK_GENERIC | {"붙임","첨부","양식","신청서","참가신청서","작성자","무제","최종본","사본","팀","팀명"}
NON_PROGRAM_CODES = NOISE | TERMS | {"unit","ver","version","rev","cve","iso","pdf","docx","pptx","zip","jpg","png"}
UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", re.I)


def display(text):
    return unicodedata.normalize("NFKC", text)


def words(text):
    return tuple(WORD.findall(display(text).casefold()))


BILINGUAL = re.compile(r"([a-z]+|[가-힣]+)\s*\(\s*([가-힣]+|[a-z]+)\s*\)[ _-]*([가-힣]+|[a-z]+)", re.I)


def bilingual_topics(files):
    """Join a bilingual spelling to a specific two-word phrase seen in plain text."""
    plain = defaultdict(set)
    variants = defaultdict(set)
    spellings = defaultdict(Counter)
    for f in files:
        if f.hold_reason:
            continue
        stem = display(f.path.stem)
        for match in BILINGUAL.finditer(stem):
            outer, inner, following = (part.casefold() for part in match.groups())
            if outer.isascii() == inner.isascii():
                continue
            for token in (outer, inner):
                if min(len(token), len(following)) >= 2 and token not in NOISE and following not in NOISE:
                    variants[(token, following)].add(f.index)
    if not variants:
        return [""] * len(files)
    for f in files:
        if f.hold_reason:
            continue
        # Keep parentheses as boundaries so the alias itself cannot attest the plain phrase.
        for part in re.split(r"[()]", display(f.path.stem)):
            tokens = WORD.findall(part)
            for left, right in zip(tokens, tokens[1:]):
                key = (left.casefold(), right.casefold())
                if key in variants:
                    plain[key].add(f.index)
                    spellings[key][left+" "+right] += 1
    matches = defaultdict(set)
    for key, annotated in variants.items():
        members = plain[key] | annotated
        if plain[key] - annotated and len(members) >= 3:
            title = spellings[key].most_common(1)[0][0]
            for i in members:
                matches[i].add(title)
    return [next(iter(matches[i])) if len(matches[i]) == 1 else "" for i in range(len(files))]


def reference_key(match):
    prefix, number = match.groups()
    if prefix.casefold() in NON_PROGRAM_CODES or (len(number)==4 and number.startswith(("19","20"))):
        return ""
    return prefix.upper()+"-"+number


def project_title(stem):
    for part in PROJECT_PARTS.split(stem):
        part=part.replace("_"," ")
        part=re.sub(r"-(?=(?:프로젝트|project)\b)|(?<=프로젝트)-|(?<=project)-"," ",part,flags=re.I)
        tokens = part.split()
        for index, marker in enumerate(tokens):
            if marker.casefold() not in {"프로젝트","project"}:
                continue
            # Korean names usually precede the marker, English names follow it.
            before = (marker=="프로젝트" and index>0) or index==len(tokens)-1
            adjacent = reversed(tokens[:index]) if before else tokens[index+1:]
            name = []
            for word in adjacent:
                if (word.casefold() in NOISE or not re.fullmatch(r"[\w-]+",word)
                        or re.fullmatch(r"(?:19|20)\d{2}|\d+(?:기|주차|회차)",word)):
                    break
                name.append(word)
            if any(any(c.isalpha() for c in word) for word in name):
                return " ".join([*reversed(name),marker] if before else [marker,*name])
    return ""


def project_spellings(stems):
    titles=[project_title(stem) for stem in stems]
    variants=defaultdict(Counter)
    keys=[]
    for title in titles:
        tokens=title.casefold().split()
        if not tokens:
            keys.append(None)
            continue
        marker=tokens.pop(0) if tokens[0] in {"project","프로젝트"} else tokens.pop()
        key=(marker,*tokens)
        variants[key][title]+=1
        keys.append(key)
    # Pick the most frequent word order, then a spelling actually used in it.
    chosen={}
    for key,forms in variants.items():
        orders=Counter()
        for title,count in forms.items():
            orders[title.casefold()]+=count
        chosen[key]=min(forms,key=lambda t:(-orders[t.casefold()],-forms[t],sum(c.isupper() for c in t),t))
    return [chosen.get(key,"") for key in keys]


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
    marked = set()
    for stem in stems:
        for m in TEAM.finditer(stem):
            team=next(v for v in m.groups() if v)
            team=re.sub(r"(?:레드|블루)$","",team)
            if team and team not in NOISE:teams.add(team)
        if title := event_title(stem):
            events.add(title)
        for m in COHORT.finditer(stem):
            if m[1].casefold() in NON_PROGRAM_CODES:
                continue
            code=m[1].upper()
            cohorts[code].add(m[2])
            if "기" in m[0] or stem[m.end():].startswith("]"):
                marked.add(code)
    # A repeated bracket label can be a visibility or processing status.
    # Require independent use of the same code in a different filename.
    tagged, bare = defaultdict(set), defaultdict(set)
    for i,stem in enumerate(stems):
        for tag in TAG.findall(stem):
            if tag.casefold() not in NON_PROGRAM_CODES:
                tagged[tag].add(i)
        for code in re.findall(r"(?<![a-zA-Z0-9])[A-Z]{2,12}(?![a-zA-Z0-9])",TAG.sub(" ",stem)):
            bare[code].add(i)
    marked.update(tag for tag,indices in tagged.items() if bare[tag] and len(indices|bare[tag])>1)
    codes = sorted(marked, key=lambda x: (-len(x), x))
    program = re.compile(r"(?<![a-z])(" + "|".join(map(re.escape, codes)) + r")(?![a-z])", re.I) if codes else None
    event_names=sorted(events,key=lambda t:(-len(t),t))
    team_names=[(t,re.compile(r"(?<![가-힣])"+re.escape(t)+r"(?=레드팀|블루팀|팀|[^가-힣]|$)"))
                for t in sorted(teams,key=lambda t:(-len(t),t))]
    result = []
    for stem,project in zip(stems,project_spellings(stems)):
        folded = stem.casefold()
        event = next((t for t in event_names if t.casefold() in folded), None)
        team = next((t for t,pattern in team_names if pattern.search(stem)),None)
        if event:
            edition = EDITION.search(stem)
            result.append(Activity(event, "행사", re.search(r"\d+", edition[0])[0] if edition else ""))
        elif team:
            result.append(Activity(team, "팀"))
        elif project:
            year = re.search(r"(?<!\d)20\d\d(?!\d)", stem)
            result.append(Activity(project, "프로젝트", year[0] if year else ""))
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
            refs={key for m in REFERENCE.finditer(UUID.sub(" ",stem)) if (key:=reference_key(m))}
            # A bare serial (including camera counters) is weak evidence on its own.
            described=any(c.isalpha() for c in REFERENCE.sub(" ",stem))
            result.append(Activity(next(iter(refs)),"문서 번호") if len(refs)==1 and described else None)
    return result


def activity_relation(a, b):
    if a is None and b is None:
        return 0
    if a and b and a.title.casefold() == b.title.casefold() and not (a.edition and b.edition and a.edition != b.edition):
        return 1
    # An invoice and a packing slip can carry unrelated kinds of references.
    # Only conflicting serials in the same namespace contradict each other.
    if all(item is None or item.kind=="문서 번호" for item in (a,b)):
        same_namespace=a and b and a.title.partition("-")[0]==b.title.partition("-")[0]
        return -1 if same_namespace else 0
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
