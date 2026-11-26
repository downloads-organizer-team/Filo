from organizer.analysis.similarity import compare, refined
from organizer.models import Study, RelatedFile
from organizer.analysis.scan_progress import tracked

def build(study,stop,status,progress=None):
    status("유사도 행렬 계산 중")
    n=len(study.files)
    pairs=n*(n-1)//2
    if progress:
        progress(0,pairs)
    rows=[bytearray(n) for _ in range(n)]
    for i in range(n):
        stop()
        rows[i][i]=100
        for j in range(i):rows[i][j]=rows[j][i]=compare(study,i,j)
        if progress:
            progress(i*(i+1)//2,pairs)
    study.primary=rows
    study.matrix=[row[:] for row in rows]

def update(study,stop,progress=None):
    for i in tracked(study.extras,progress):
        stop()
        for j in range(len(study.files)):
            if i!=j and not (j in study.extras and j<i):
                study.matrix[i][j]=study.matrix[j][i]=refined(study,i,j)


def related(study:Study,index:int) -> list[RelatedFile]:
    """A bounded local view of evidence, not an additional grouping decision."""
    file=study.files[index]
    peers=[]
    for other in study.files:
        if other.index==index:continue
        if study.rules is not None and not study.rules.allowed(index,other.index):continue
        score=study.matrix[index][other.index]
        together=file.group is not None and file.group is other.group
        if score<35 and not together:continue
        peers.append((score,other))
    result=[]
    for score,other in sorted(peers,key=lambda p:(-p[0],p[1].name.casefold()))[:5]:
        evidence=compare(study,index,other.index,details=True)
        assert isinstance(evidence,dict)
        signals=[]
        for key,label in (("activity","같은 활동 이름"),("batch","일괄 다운로드 단서"),
                          ("task","작업명"),("version","버전"),("sequence","번호 패턴"),
                          ("folder","같은 폴더"),("source_page","같은 출처 페이지")):
            if evidence[key]:signals.append(label)
        if evidence["literal"]>=.2:signals.append("파일명 단어")
        if evidence["semantic"]>=.4:signals.append("관련 용어")
        if evidence["time"]:signals.append("가까운 파일 시각")
        if file.group is not None and file.group is other.group:signals.append("같은 검토 묶음")
        result.append(RelatedFile(id=other.index,name=other.name,score=score,
                                  group=other.group.gid if other.group else None,signals=signals))
    return result
