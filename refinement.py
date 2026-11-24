from candidates import cohesion
from confidence import rank
from matrix import update
from readers import read,SUPPORTED
from similarity import content_vector

def refine(study,rules,stop):
    if not study.deep or not study.groups:return
    for i in sorted(study.medium):
        stop();f=study.files[i]
        if f.ext not in SUPPORTED:
            f.excerpt_status="본문 미지원 형식";continue
        study.attempted.add(i)
        text,f.excerpt_status=read(f)
        if text:
            study.tried+=1
            v=content_vector(study,text)
            if v.literal or v.context:study.extras[i]=v
    update(study,stop)
    # Freeze confident anchors. Competing ambiguous files cannot promote one another.
    plans=[]
    for i in study.medium:
        stop();f=study.files[i];r=rank(study,f,study.groups,rules)
        f.confidence=r.confidence;f.evidence=r.describe()
        if i in study.extras and r.qualifies(study.min_confidence):plans.append((r.confidence,i,r.group))
    for conf,i,g in sorted(plans,key=lambda row:(-row[0],row[1])):
        if any(not rules.allowed(i,m.index) for m in g.members):continue
        f=study.files[i];f.group=g;f.state="2차 추천";f.note="문서 일부를 반영한 뒤 이 묶음과의 관련도가 높아졌습니다."
        g.members.append(f);study.rescued+=1

def summarize(study):
    for g in study.groups:
        g.cohesion=cohesion(study.matrix,g.members)
        scores=[f.confidence for f in g.members if f.confidence is not None]
        g.confidence=sum(scores)/len(scores) if scores else None
