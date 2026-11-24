"""Use immediate subfolders as read-only evidence for a destination."""
from collections import Counter, defaultdict
from itertools import islice
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
import os
import stat

from course_source import relation as course_relation
from features import SERIES, VERSION, task_name
from models import Group
from scanner import check_directory
from topics import NOISE, activity_relation, opaque_format, words


def identity(text):
    return tuple(w for w in words(SERIES.sub(" ", VERSION.sub(" ", text)))
                 if len(w)>1 and not w.isdecimal() and w not in NOISE and not opaque_format(w))


def folder_index(roots, stop):
    labels, examples = defaultdict(dict), defaultdict(dict)
    for root in roots:
        with os.scandir(root) as entries:
            for entry in entries:
                stop()
                path = Path(entry.path)
                if not entry.is_dir(follow_symlinks=False) or path in roots:
                    continue
                try:
                    check_directory(path)
                    label = identity(entry.name)
                    if label:
                        labels[label][path] = .97
                    samples = Counter()
                    with os.scandir(path) as children:
                        for child in islice(children, 100):
                            stop()
                            if not child.is_file(follow_symlinks=False):
                                continue
                            info = child.stat(follow_symlinks=False)
                            if getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                                continue
                            stem = Path(child.name).stem
                            prefix, _ = task_name(stem)
                            keys = {identity(stem), identity(prefix)}
                            samples.update(k for k in keys if k)
                    for key, count in samples.items():
                        score = .93 if count >= 2 else .84
                        examples[key][path] = score
                except InterruptedError:
                    raise
                except OSError:
                    continue
    return labels,examples


def match(index, label_keys, example_keys, minimum):
    scores = {}
    for lookup,keys in zip(index,(label_keys,example_keys)):
        for key in keys:
            for folder, confidence in lookup.get(key, {}).items():
                scores[folder] = max(scores.get(folder, 0), confidence)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    if ranked and ranked[0][1] >= minimum and (len(ranked)==1 or ranked[0][1]-ranked[1][1] >= .08):
        return ranked[0]
    return None


def recommend(study, stop):
    index = folder_index(study.roots, stop)
    if not any(index):
        return
    by_folder = defaultdict(list)
    for group in study.groups:
        titles=[identity(group.title)]
        best = match(index, titles, titles, study.min_confidence)
        if not best:
            votes = [file_match(study, f, index) for f in group.members]
            if votes and all(v and v[0] == votes[0][0] for v in votes):
                best = votes[0]
        if best:
            group.destination = best[0]
            group.title_note += " · 기존 폴더 " + str(best[0])
            by_folder[best[0]].append(group)
    for f in study.files:
        stop()
        if f.group or f.index in study.rules.fixed or study.opaque_formats[f.index]:
            continue
        best = file_match(study, f, index)
        if not best:
            continue
        folder, confidence = best
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
                        title_note="기존 폴더와 일치하는 파일명 · "+str(folder),destination=folder)
            groups.append(group)
            study.groups.append(group)
        f.group, f.confidence, f.state = group, confidence, "기존 폴더 추천"
        f.note = "폴더 이름 또는 안에 보관된 파일의 작업명이 일치합니다. " + str(folder)
        f.evidence = f.note
        group.members.append(f)


def file_match(study, f, index):
    tokens = identity(f.path.stem)
    activity = study.activities[f.index]
    if activity:
        keys={tokens,identity(activity.title)}
        if activity.edition and activity.kind=="프로그램":
            keys.add(identity(activity.title+" "+activity.edition+"기"))
        examples=keys
    else:
        keys={tokens[i:j] for i in range(len(tokens)) for j in range(i+1,min(len(tokens),i+10)+1)}
        prefix,_=task_name(f.path.stem)
        examples={tokens,identity(prefix)}
    return match(index, keys, examples, study.min_confidence)
