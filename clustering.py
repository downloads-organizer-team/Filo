"""Complete-link agglomeration with a reciprocal nearest-neighbour chain."""
CUT=60

def agglomerate(study,rules,stop):
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
        if b is None or dist[a][b]<CUT:
            result.append(units[a]);active.remove(a);chain.pop()
        elif b==previous:
            del chain[-2:]
            active.remove(a);units[b].extend(units[a])
            for k in active:
                if k!=b:dist[b][k]=dist[k][b]=min(dist[a][k],dist[b][k])
        else:chain.append(b)
    return [sorted(u) for u in result if len(u)>=2 or u[0] in rules.fixed]
