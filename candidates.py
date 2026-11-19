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
    name,note,group.title_kind=find_title(group.members,read_covers)
    if name:
        group.title,group.title_note=name,note
        return
    if group.title_kind=="conflict":
        group.title,group.title_note="과목명 확인 필요",note
        return
    vectors=[study.vectors[f.index] for f in group.members]
    literal=Counter(k for vec in vectors for k in vec.literal if not SESSION_LABEL.fullmatch(k))
    context=Counter(k for vec in vectors for k in vec.context)
    shared=[k for k,n in literal.items() if n==len(vectors)]
    group.title_note=note or "파일명에서 추정한 작업 · 그룹 이름을 확인하세요"
    if shared:
        group.title=min(shared,key=lambda k:(-study.idf.get(k,0),k))
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
