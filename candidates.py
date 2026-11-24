from collections import Counter
import re
from uuid import uuid5, NAMESPACE_URL
from course_source import group_scope
from course_titles import find_title
from features import LEXICON
from models import Group
from readers import SESSION_LABEL

def assign_title(study,group,rules,read_covers=False):
    if group.gid in rules.names:
        group.title,group.title_note=rules.names[group.gid],"사용자가 지정한 그룹 이름"
        group.title_kind="manual"
        return
    scope=group_scope(group.members)
    if scope in rules.course_titles:
        group.title,group.title_note=rules.course_titles[scope],"사용자가 확인한 과목명 · 같은 강좌 출처"
        group.title_kind="confirmed"
        return
    activities=[study.activities[f.index] for f in group.members]
    named_activity=all(activities) and len({a.title.casefold() for a in activities})==1
    name,note,group.title_kind=find_title(group.members,read_covers and not named_activity,
                                         filename_prefix=not named_activity)
    if name:
        group.title,group.title_note=name,note
        return
    if group.title_kind=="conflict":
        group.title,group.title_note="과목명 확인 필요",note
        return
    if named_activity:
        activity=activities[0]
        editions={a.edition for a in activities if a.edition}
        suffix=" "+next(iter(editions))+"기" if activity.kind=="프로그램" and len(editions)==1 else ""
        group.title=activity.title+suffix
        group.title_kind="activity"
        group.title_note=f"파일명에 공통으로 적힌 {activity.kind} · {group.title}"
        return
    if all(study.opaque_formats[f.index] for f in group.members) and all(
            study.primary[a.index][b.index]>=82 for i,a in enumerate(group.members) for b in group.members[:i]):
        from datetime import datetime
        recorded=all(study.download_times[f.index] is not None for f in group.members)
        stamp=datetime.fromtimestamp(min(study.download_times[f.index] if recorded else f.created for f in group.members))
        group.title=stamp.strftime("%Y-%m-%d %H시 %M분 다운로드")
        group.title_kind="batch"
        group.title_note=("형식이 같은 긴 식별자 · 기록된 다운로드 시각 차이 5분 이내" if recorded
                          else "형식이 같은 긴 식별자 · 같은 다운로드 사이트와 2분 이내의 파일 생성 시각")
        return
    vectors=[study.vectors[f.index] for f in group.members]
    literal=Counter(k for vec in vectors for k in vec.literal if not SESSION_LABEL.fullmatch(k))
    context=Counter(k for vec in vectors for k in vec.context)
    shared=[k for k,n in literal.items() if n==len(vectors)]
    group.title_note=note or "파일명에서 추정한 작업 · 그룹 이름을 확인하세요"
    if shared:
        from topics import common_phrase
        phrase=common_phrase(group.members,shared)
        group.title=phrase or min(shared,key=lambda k:(-study.idf.get(k,0),k))
        group.title_note="모든 파일 이름에 공통으로 나타난 주제 · "+group.title
    elif context:
        group.title=max(context,key=lambda k:(context[k],len(LEXICON[k])))
    else:
        topics=[]
        for token,_ in literal.most_common(2):
            spelling=next((m.group() for f in group.members
                           if (m:=re.search(re.escape(token),f.path.stem,re.I))),token)
            topics.append(spelling)
        group.title=" · ".join(topics) or ("강의 자료" if scope else "이름 미정")
        group.title_note=note or "임시 이름 · 그룹 이름을 직접 정할 수 있어요"

def make(study,clusters,constraints):
    groups=[]
    for ids in clusters:
        members=[study.files[i] for i in ids]
        pinned=next((constraints.pinned[constraints.component[i]] for i in ids if constraints.component[i] in constraints.pinned),None)
        gid=pinned or str(uuid5(NAMESPACE_URL,"moa/"+"|".join(sorted(f.uid for f in members))))
        groups.append(Group(gid,"",members))
    return groups

def cohesion(matrix,members):
    n=len(members)
    if n<2:return 0.
    return sum(matrix[a.index][b.index] for i,a in enumerate(members) for b in members[:i])/(100*n*(n-1)/2)
