from similarity import compare, refined

def build(study,stop,status):
    n=len(study.files)
    rows=[bytearray(n) for _ in range(n)]
    for i in range(n):
        stop()
        if i%32==0:status(f"유사도 행렬 계산 중   {i:,} / {n:,}")
        rows[i][i]=100
        for j in range(i):rows[i][j]=rows[j][i]=compare(study,i,j)
    study.primary=rows
    study.matrix=[row[:] for row in rows]

def update(study,stop):
    for i in study.extras:
        stop()
        for j in range(len(study.files)):
            if i!=j and not (j in study.extras and j<i):
                study.matrix[i][j]=study.matrix[j][i]=refined(study,i,j)
