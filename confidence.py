from dataclasses import dataclass
from candidates import cohesion
from course_source import relation as course_relation
from models import Group

@dataclass
class Ranking:
    group:Group|None=None
    affinity:float=0
    margin:float=0
    neighbor:float=0
    cohesion:float=0
    confidence:float=0
    @property
    def high(self):
        runner=self.affinity-self.margin
        required_gap=.25 if runner>=.60 else .10
        return self.group is not None and self.affinity>=.60 and self.margin>=required_gap and self.confidence>=.62
    def describe(self):
        return f"가장 가까운 묶음 {self.affinity:.2f} · 차점과 차이 {self.margin:.2f} · 가까운 이웃 {self.neighbor:.2f} · 묶음 내부 {self.cohesion:.2f}"

def rank(study,f,groups,rules):
    candidates=[]
    for g in groups:
        others=[m for m in g.members if m is not f]
        if not others or any(not rules.allowed(f.index,m.index) for m in others):continue
        vals=[study.matrix[f.index][m.index]/100 for m in others]
        neighbors=sorted(vals,reverse=True)[:3]
        nearest=sum(neighbors)/len(neighbors)
        average=sum(vals)/len(vals)
        candidates.append((.65*average+.35*nearest,nearest,g))
    if not candidates:return Ranking()
    candidates.sort(key=lambda x:-x[0])
    best,nearest,g=candidates[0];margin=best-(candidates[1][0] if len(candidates)>1 else 0)
    core=g.cohesion if len(g.members)>1 else nearest
    conf=.44*best+.20*nearest+.18*core+.18*min(1,margin/.30)
    return Ranking(g,best,margin,nearest,core,conf)

def detect(study,groups,rules):
    from readers import SUPPORTED
    for g in groups:g.cohesion=cohesion(study.matrix,g.members)
    owners={m.index:g for g in groups for m in g.members}
    anchors=[m for g in groups for m in g.members]
    for f in study.files:
        if f.index in rules.fixed:
            f.group=owners.get(f.index)
            f.state="직접 지정";f.first_band="확정";f.confidence=None
            f.note="저장한 소속 또는 같은 그룹 관계를 적용했습니다." if f.group else "사용자가 미분류로 확정했습니다."
            f.evidence="직접 지정한 소속은 추천 신뢰도 계산에서 제외합니다."
            continue
        r=rank(study,f,groups,rules);f.confidence=r.confidence;f.evidence=r.describe()
        if r.high and r.group is not None and owners.get(f.index) is r.group:
            f.group=r.group;f.first_band="높음";f.state="1차 추천";f.note="이름과 이웃 파일의 관계가 같은 묶음을 지지합니다."
            if any(m is not f and course_relation(f,m)==1 for m in f.group.members):
                f.note="이 묶음의 다른 자료와 같은 강의 출처 단서가 다운로드 기록에 남아 있습니다."
        elif groups and (r.affinity>=.23 or (not study.vectors[f.index].literal and f.ext in SUPPORTED and
                any(m is not f and rules.allowed(f.index,m.index) and
                    ((f.path.parent==m.path.parent and f.modified and m.modified and abs(f.modified-m.modified)<=172800) or
                     (f.download.directory and f.host==m.host and f.download.directory==m.download.directory))
                    for m in anchors))):
            f.first_band="중간";study.medium.add(f.index);f.note="묶음 간 차이가 작거나 파일명에 작업 단서가 부족합니다."
        else:f.note="관계를 뒷받침하는 단서가 부족합니다."
    for g in groups:
        g.members=[f for f in g.members if f.group is g]
        if len(g.members)==1 and g.members[0].index not in rules.fixed|rules.separate:
            f=g.members.pop();f.group=None;f.state="미분류";f.first_band="중간";study.medium.add(f.index)
        g.cohesion=cohesion(study.matrix,g.members)
    return [g for g in groups if g.members]
