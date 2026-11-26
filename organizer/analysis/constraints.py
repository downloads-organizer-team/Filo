from collections import defaultdict
from dataclasses import dataclass, field

@dataclass
class Rules:
    pins:dict=field(default_factory=dict)
    names:dict=field(default_factory=dict)
    relations:list=field(default_factory=list)
    revision:int=0
    course_titles:dict=field(default_factory=dict)

class Constraints:
    def __init__(self,files,rules):
        self.rules=rules
        parent={}
        def root(key):
            parent.setdefault(key,key)
            while parent[key]!=key:
                parent[key]=parent[parent[key]]
                key=parent[key]
            return key
        def join(a,b):parent[root(a)]=root(b)
        first={}
        for uid,gid in rules.pins.items():
            if gid is not None:join(uid,first.setdefault(gid,uid))
        for a,b,kind in rules.relations:
            if kind=="must":join(a,b)
        self.blocked=set()
        for a,b,kind in rules.relations:
            if kind=="cannot":
                x,y=root(a),root(b)
                if x==y:raise ValueError("이미 같은 묶음으로 확정한 파일입니다. 기존 같은 그룹 관계를 해제하거나 묶음을 먼저 분리하세요.")
                self.blocked.add(frozenset((x,y)))
        self.pinned={}
        for uid,gid in rules.pins.items():
            x=root(uid)
            if x in self.pinned and self.pinned[x]!=gid:raise ValueError("확정된 소속이 충돌합니다. 파일 소속이나 기존 파일 관계를 수정하세요.")
            self.pinned[x]=gid
        for a,b,kind in rules.relations:
            if kind=="must" and root(a) in self.pinned and self.pinned[root(a)] is None:
                raise ValueError("미분류로 확정한 파일입니다. 먼저 해당 파일을 묶음에 추가하세요.")
        self.component=[root(f.uid) for f in files]
        separated={x for pair in self.blocked for x in pair}
        self.separate={i for i,x in enumerate(self.component) if x in separated}
        self.fixed={i for i,f in enumerate(files) if self.component[i] in self.pinned}
        must_roots={root(a) for a,b,k in rules.relations if k=="must"}
        self.fixed.update(i for i,x in enumerate(self.component) if x in must_roots)
        self.units=defaultdict(list)
        for i,x in enumerate(self.component):self.units[x].append(i)
        self.hold={i for i,x in enumerate(self.component) if x in self.pinned and self.pinned[x] is None}
    def allowed(self,i,j):
        x,y=self.component[i],self.component[j]
        if i in self.hold or j in self.hold:return False
        if x==y:return True
        if x in self.pinned and y in self.pinned and self.pinned[x]!=self.pinned[y]:return False
        return not self.blocked or frozenset((x,y)) not in self.blocked

    def new_course_conflict(self,files,previous):
        """Find two files this edit newly links despite distinct course IDs on one LMS."""
        for indices in self.units.values():
            old_units=defaultdict(list)
            for i in indices:
                if files[i].course_scope:old_units[previous.component[i]].append(files[i])
            if len(old_units)<2:continue
            seen=defaultdict(dict)
            for members in old_units.values():
                for f in members:
                    namespace,course=f.course_scope
                    for other_course,other in seen[namespace].items():
                        if other_course!=course:return other,f
                for f in members:
                    namespace,course=f.course_scope
                    seen[namespace].setdefault(course,f)
        return None
