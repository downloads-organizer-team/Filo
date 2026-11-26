from organizer.analysis.candidates import cohesion
from organizer.analysis.confidence import rank
from organizer.analysis.matrix import update
from organizer.analysis.readers import read,SUPPORTED
from organizer.analysis.similarity import content_vector
from organizer.analysis.scan_progress import tracked

def refine(study,rules,stop,status=lambda text:None,progress=None):
    if not study.deep or not study.groups or not study.medium:return
    status("문서 일부 확인 중")
    for i in tracked(sorted(study.medium),progress):
        stop();f=study.files[i]
        if f.ext not in SUPPORTED:
            f.excerpt_status="본문 미지원 형식";continue
        study.attempted.add(i)
        text,f.excerpt_status=read(f)
        if text:
            study.tried+=1
            v=content_vector(study,text)
            if v.literal or v.context:study.extras[i]=v
    if study.extras:
        status("문서 유사도 갱신 중")
        update(study,stop,progress)
    # Freeze confident anchors. Competing ambiguous files cannot promote one another.
    plans=[]
    status("문서 확인 결과 반영 중")
    for i in tracked(study.medium,progress):
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
