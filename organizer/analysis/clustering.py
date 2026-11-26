"""Complete-link agglomeration with a reciprocal nearest-neighbour chain."""
from organizer.analysis.confidence import affinity_floor
from organizer.analysis.course_source import relation
from organizer.analysis.topics import activity_relation


def supported_pair(study,i,j):
    a,b=study.files[i],study.files[j]
    return (activity_relation(study.activities[i],study.activities[j])==1
            or study.opaque_formats[i] and study.opaque_formats[j]
            or study.task_prefixes[i] and study.task_prefixes[i]==study.task_prefixes[j]
            or not study.vectors[i].literal.keys().isdisjoint(study.vectors[j].literal)
            or relation(a,b)==1)

def agglomerate(study,rules,stop,status=lambda text:None,progress=None):
    cutoff=round(100*affinity_floor(study.min_confidence))
    units=[remaining for unit in rules.units.values() if (remaining:=[i for i in unit if i not in rules.hold])]
    count=len(units)
    status("군집 간 거리 계산 중")
    pairs=count*(count-1)//2
    if progress:
        progress(0,pairs)
    # A forbidden edge stays zero under the minimum update for complete linkage.
    dist=[bytearray(count) for _ in units]
    for i,members in enumerate(units):
        stop()
        for j in range(i):
            score=min((study.matrix[a][b] if rules.allowed(a,b) else 0)
                      for a in members for b in units[j])
            dist[i][j]=dist[j][i]=score
        if progress:
            progress(i*(i+1)//2,pairs)
    active=set(range(count));chain=[];result=[]
    status("계층 군집화 중")
    if progress:
        progress(0,count)
    while active:
        stop()
        if not chain:chain.append(min(active))
        a=chain[-1];previous=chain[-2] if len(chain)>1 else None
        candidates=(b for b in active if b!=a)
        b=max(candidates,key=lambda k:(dist[a][k],k==previous,-k),default=None)
        if b is None or dist[a][b]<cutoff:
            result.append(units[a]);active.remove(a);chain.pop()
        elif b==previous:
            del chain[-2:]
            active.remove(a);units[b].extend(units[a])
            for k in active:
                if k!=b:dist[b][k]=dist[k][b]=min(dist[a][k],dist[b][k])
        else:
            chain.append(b)
            continue
        if progress:
            progress(count-len(active),count)
    return [sorted(u) for u in result if len(u)>2 or any(i in rules.fixed for i in u)
            or (len(u)==2 and (any(i in rules.separate for i in u) or supported_pair(study,*u)))]
