"""Complete-link agglomeration with a reciprocal nearest-neighbour chain."""
from confidence import affinity_floor
from course_source import relation


def supported_pair(study,i,j):
    a,b=study.files[i],study.files[j]
    return (study.activities[i] is not None and study.activities[i]==study.activities[j]
            or study.opaque_formats[i] and study.opaque_formats[j]
            or study.task_prefixes[i] and study.task_prefixes[i]==study.task_prefixes[j]
            or not study.vectors[i].literal.keys().isdisjoint(study.vectors[j].literal)
            or relation(a,b)==1)

def agglomerate(study,rules,stop):
    cutoff=round(100*affinity_floor(study.min_confidence))
    units=[v[:] for v in rules.units.values() if v[0] not in rules.hold]
    count=len(units)
    # A forbidden edge stays zero under the minimum update for complete linkage.
    dist=[bytearray(count) for _ in units]
    for i,members in enumerate(units):
        stop()
        for j in range(i):
            score=min((study.matrix[a][b] if rules.allowed(a,b) else 0)
                      for a in members for b in units[j])
            dist[i][j]=dist[j][i]=score
    active=set(range(count));chain=[];result=[]
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
        else:chain.append(b)
    return [sorted(u) for u in result if len(u)>2 or any(i in rules.fixed for i in u)
            or (len(u)==2 and (any(i in rules.separate for i in u) or supported_pair(study,*u)))]
