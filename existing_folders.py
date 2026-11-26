"""Use immediate subfolders as read-only evidence for a destination."""
from collections import defaultdict
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
import os
import re
import stat

from course_source import relation as course_relation
from features import SERIES, VERSION, YEAR, task_name, tokenize, zone_transfer
from models import Group
from similarity import dot, source_page_key, vector
from scanner import check_directory
from topics import NOISE, REFERENCE, activity_relation, opaque_format, project_title, reference_key, words

YEAR_LABEL = re.compile(YEAR.pattern+r"(?:학년도|년도|년)?")
QUALIFIER = re.compile(r"(?<!\d)(\d{1,2})\s*(학기|기|회차)(?![가-힣])|제\s*(\d{1,3})\s*회")

def identity(text):
    # Preserve the serial when tokenizing e.g. AB-12345 and AB12345.
    codes=set()
    def normalize(match):
        code=reference_key(match).replace("-","").casefold()
        if code:codes.add(code)
        return code or match[0]
    text=YEAR_LABEL.sub(" ",REFERENCE.sub(normalize,text))
    tokens=tuple(w for w in words(SERIES.sub(" ", VERSION.sub(" ", text)))
                 if w in codes or (w not in NOISE and not YEAR.fullmatch(w) and not opaque_format(w)))
    # A number or a single character can distinguish names, but is weak by itself.
    return tokens if any(len(w)>1 and not w.isdecimal() for w in tokens) else ()


@dataclass
class Name:
    key: tuple[str,...]
    prefix: tuple[str,...]
    weights: dict[str,float]
    periods: dict[str,set[str]]
    references: set[str]
    page: tuple[str,str,str] | None = None


def describe(stem, idf, page=None):
    key=identity(stem)
    periods=defaultdict(set)
    periods["연도"].update(YEAR.findall(stem))
    for n,kind,edition in QUALIFIER.findall(stem):
        periods[kind or "회차"].add(n or edition)
    references={code for match in REFERENCE.finditer(stem) if (code:=reference_key(match))}
    tokens=[w for term in key if len(term)>1 and not term.isdecimal() for w in tokenize(term) if w not in NOISE]
    prefix,_=task_name(YEAR_LABEL.sub(" ",stem))
    return Name(key,identity(prefix or project_title(stem)),vector(tokens,idf).literal,periods,references,page)


@dataclass
class Folder:
    label: Name
    samples: list[Name]
    recurring_task: tuple[str,...]


def folder_index(roots, idf, stop):
    folders, postings = {}, defaultdict(set)
    for root in roots:
        with os.scandir(root) as entries:
            for entry in entries:
                stop()
                path = Path(entry.path)
                if not entry.is_dir(follow_symlinks=False) or path in roots:
                    continue
                try:
                    check_directory(path)
                    label=describe(entry.name,idf)
                    samples=[]
                    seen=set()
                    with os.scandir(path) as children:
                        for child in islice(children, 100):
                            stop()
                            if not child.is_file(follow_symlinks=False):
                                continue
                            info = child.stat(follow_symlinks=False)
                            attrs=getattr(info,"st_file_attributes",0)
                            if attrs & (stat.FILE_ATTRIBUTE_REPARSE_POINT|stat.FILE_ATTRIBUTE_SYSTEM):
                                continue
                            source=Path(child.path)
                            spelling=VERSION.sub("",source.stem).strip().casefold()
                            if spelling in seen:continue
                            seen.add(spelling)
                            page=None
                            if len(samples)<12 and not attrs & stat.FILE_ATTRIBUTE_OFFLINE:
                                page=source_page_key(zone_transfer(source).get("ReferrerUrl",""))
                            samples.append(describe(source.stem,idf,page))
                    tasks=[sample.prefix for sample in samples if sample.prefix]
                    recurring_task=tasks[0] if len(tasks)>=2 and len(set(tasks))==1 else ()
                    folders[path]=Folder(label,samples,recurring_task)
                    for name in [label,*samples]:
                        for word in (*name.key,*name.weights):
                            postings[word].add(path)
                except InterruptedError:
                    raise
                except OSError:
                    continue
    return folders,postings


def similar_name(a,b):
    shared=a.weights.keys() & b.weights.keys()
    # One word can name a broad subject. Require two terms for an approximate match.
    if len(shared)<2 or dot(a.weights,b.weights)<.60:return False
    a_tags={w for w in a.key if len(w)==1 or w.isdecimal()}
    b_tags={w for w in b.key if len(w)==1 or w.isdecimal()}
    return not (a_tags and b_tags and a_tags!=b_tags)


def periods_fit(source,folder,relevant):
    for kind in source.periods.keys() | folder.label.periods.keys():
        incoming=source.periods.get(kind,set())
        explicit=folder.label.periods.get(kind,set())
        if explicit and (not incoming or not incoming.issubset(explicit)):return False
        if not incoming:continue
        dated=[s.periods[kind] for s in relevant if s.periods.get(kind)]
        if not dated:
            dated=[s.periods[kind] for s in folder.samples if s.periods.get(kind)]
        if not dated or any(incoming.issubset(values) for values in dated):continue
        # Distinct editions in separate filenames establish a multi-edition archive.
        if len({next(iter(values)) for values in dated if len(values)==1})<2:return False
    return True


def folder_score(source,folder,label_keys,example_keys):
    label=folder.label
    if source.references and label.references and source.references.isdisjoint(label.references):return
    label_overlap=bool(label.key and label.key in label_keys)
    # A one-word folder name inside a longer filename needs a second clue.
    label_exact=label_overlap and (len(label.key)>1 or label.key in example_keys or bool(label.references))
    label_similar=similar_name(source,label)
    exact=near=same_page=0
    relevant=[]
    common_terms=None
    conflicting_ref=False
    for sample in folder.samples:
        exact_name=bool(example_keys.intersection((sample.key,sample.prefix)))
        near_name=similar_name(source,sample)
        page=bool(source.page and source.page==sample.page)
        if not (exact_name or near_name or page):continue
        if source.references and sample.references and source.references.isdisjoint(sample.references):
            conflicting_ref=True
            continue
        relevant.append(sample)
        if near_name:
            terms=sample.weights.keys()
            common_terms=set(terms) if common_terms is None else common_terms.intersection(terms)
        exact+=exact_name
        near+=near_name
        same_page+=page
    if conflicting_ref and not relevant:return
    if folder.recurring_task and source.prefix and not relevant:
        if set(source.prefix).isdisjoint(folder.recurring_task):return
    # Recurring qualifiers such as the client or site distinguish related projects.
    if near>=2 and common_terms and not (exact or same_page):
        if common_terms-source.weights.keys() and source.weights.keys()-common_terms:return
    evidence=[]
    if label_overlap or label_similar:evidence.append("폴더명")
    if exact or near:evidence.append("보관 파일명")
    if same_page:evidence.append("다운로드 출처")
    if label_exact:score=.97
    elif exact:score=.93 if exact>=2 else .84
    elif near>=2 or ((label_overlap or label_similar) and near):score=.87
    elif same_page and (label_overlap or label_similar or near):score=.88
    else:return
    if not periods_fit(source,folder,relevant):return
    # Independent corroboration also breaks ties between equally named destinations.
    score+=.10*(len(evidence)-1)
    return score," · ".join(evidence)


def recommend(study, stop):
    index = folder_index(study.roots,study.idf,stop)
    if not index[0]:
        return
    by_folder = defaultdict(list)
    for group in study.groups:
        stop()
        votes=[file_match(study,f,index,group.title) for f in group.members]
        if votes and all(v and v[0]==votes[0][0] for v in votes):
            folder,_,reason=min(votes,key=lambda v:v[1])
            group.destination=folder
            group.destination_reason=reason
            group.title_note+=" · "+reason+" 일치 · 기존 폴더 "+str(folder)
            by_folder[folder].append(group)
    for f in study.files:
        stop()
        if f.group or f.hold_reason or f.index in study.rules.fixed or study.opaque_formats[f.index]:
            continue
        best = file_match(study, f, index)
        if not best:
            continue
        folder, confidence, reason = best
        groups = by_folder[folder]
        if len(groups)>1:
            continue
        if groups:
            group=groups[0]
            if group.title_kind=="manual" or any(
                    not study.rules.allowed(f.index,m.index) or course_relation(f,m)<0
                    or activity_relation(study.activities[f.index],study.activities[m.index])<0
                    for m in group.members):
                continue
        else:
            group=Group(str(uuid5(NAMESPACE_URL, str(folder))),folder.name,[],title_kind="folder",
                        title_note=reason+" 일치 · "+str(folder),destination=folder,destination_reason=reason)
            groups.append(group)
            study.groups.append(group)
        f.group, f.confidence, f.state = group, confidence, "기존 폴더 추천"
        f.note = reason+" 일치 · "+str(folder)
        f.evidence = f.note
        group.members.append(f)


def file_match(study,f,index,title=""):
    source=describe(f.path.stem,study.idf,source_page_key(f.download.source_page))
    tokens=source.key
    activity = study.activities[f.index]
    if activity:
        keys={tokens,identity(activity.title)}
        if activity.edition and activity.kind=="프로그램":
            keys.add(identity(activity.title+" "+activity.edition+"기"))
        examples=set(keys)
    else:
        keys={tokens[i:j] for i in range(len(tokens)) for j in range(i+1,min(len(tokens),i+10)+1)}
        examples={tokens,source.prefix}
    if title:
        title_key=identity(title)
        keys.add(title_key)
        examples.add(title_key)
    examples.discard(())
    folders,postings=index
    candidates=set()
    for word in set(source.weights).union(*keys,*examples):
        candidates.update(postings.get(word,()))
    matches=[]
    for path in candidates:
        result=folder_score(source,folders[path],keys,examples)
        if result:matches.append((path,*result))
    matches.sort(key=lambda row:-row[1])
    if matches:
        path,strength,reason=matches[0]
        confidence=min(.99,strength)
        if confidence>=study.min_confidence and (len(matches)==1 or strength-matches[1][1]>=.08):
            return path,confidence,reason
