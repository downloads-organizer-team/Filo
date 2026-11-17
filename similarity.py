from collections import Counter
from dataclasses import dataclass
from math import log, sqrt
from urllib.parse import urlsplit
from features import GENERIC, LEXICON, ALIASES, tokenize, task_prefixes
import course_source

NEIGHBORS={}
for context,words in LEXICON.items():
    for word in words:
        NEIGHBORS.setdefault(ALIASES.get(word,word),set()).add(context)

@dataclass
class Vector:
    literal: dict
    context: dict
    grams: frozenset

def unit(values):
    length=sqrt(sum(x*x for x in values.values()))
    return {k:v/length for k,v in values.items()} if length else {}

def vector(tokens,idf):
    counts=Counter(w for w in tokens if w not in GENERIC)
    literal={w:(1+log(n))*idf.get(w,1.5) for w,n in counts.items()}
    context=Counter()
    for w in counts:
        for link in NEIGHBORS.get(w,()):context[link]+=1+log(counts[w])
    grams=frozenset(w[k:k+2] for w in counts for k in range(len(w)-1))
    return Vector(unit(literal),unit(context),grams)

def dot(a,b):
    if len(a)>len(b):a,b=b,a
    return min(1,sum(v*b.get(k,0) for k,v in a.items()))

def channels(a,b):
    lex=dot(a.literal,b.literal)
    sem=dot(a.context,b.context)
    char=(2*len(a.grams & b.grams)/(len(a.grams)+len(b.grams))) if a.grams and b.grams else 0
    return lex,sem,char

def fuse(lex,sem,char):
    # Alternative evidence channels saturate instead of counting synonyms twice.
    return 1-(1-.92*lex)*(1-.88*sqrt(sem))*(1-.43*char**2)

def same_source_page(a,b):
    """A weak clue when both downloads came from the same HTTPS page path."""
    if not a.download.source_page or not b.download.source_page:return False
    try:
        x,y=urlsplit(a.download.source_page),urlsplit(b.download.source_page)
        return (x.scheme==y.scheme=="https" and x.netloc.casefold()==y.netloc.casefold()
                and x.path.rstrip("/")==y.path.rstrip("/"))
    except ValueError:
        return False

def compare(s,i,j,details=False):
    a,b=s.files[i],s.files[j]
    lex,sem,char=channels(s.vectors[i],s.vectors[j])
    base=fuse(lex,sem,char)
    task=bool(s.task_prefixes[i] and s.task_prefixes[i]==s.task_prefixes[j])
    if task:base+=(1-base)*.55
    seq=bool(a.pattern and a.pattern==b.pattern and abs(a.number-b.number)<=2)
    same_dir=a.rel==b.rel and a.rel.casefold() not in {".","다운로드","downloads","공용","자료","inbox"}
    timing=.5*(abs(a.created-b.created)<=86400)+.5*(abs(a.modified-b.modified)<=172800)
    host=bool(a.host and a.host==b.host)
    source_page=same_source_page(a,b)
    version=bool((a.versions or b.versions) and a.normalized==b.normalized and s.vectors[i].literal)
    context=.035*seq+.045*same_dir+.03*timing+.018*host+.012*bool(host and a.download.directory and a.download.directory==b.download.directory)+.02*bool(set(a.roles)&set(b.roles))+.08*version+.05*source_page
    # A cited publication year alone says nothing about the term of a course.
    different_term = a.academic_year and b.academic_year and a.academic_year!=b.academic_year
    different_edition = a.year and b.year and a.year!=b.year and a.normalized==b.normalized
    if different_edition and not different_term:base*=.55
    score=base+(1-base)*context
    scope=course_source.relation(a,b)
    if scope==1:score=score+(1-score)*.76
    elif scope==-1:score=min(score,.45)
    if different_term:score*=.55
    if details:return dict(literal=lex,semantic=sem,string=char,context=context,sequence=seq,folder=same_dir,time=timing,source=host,source_page=source_page,version=version,course=scope,task=task)
    return round(100*score)

def prepare(study):
    course_source.prepare(study.files)
    study.task_prefixes=task_prefixes(study.files)
    df=Counter(w for f in study.files for w in set(f.tokens))
    study.idf={w:1+log((len(study.files)+1)/(n+1)) for w,n in df.items()}
    study.vectors=[vector(f.tokens,study.idf) for f in study.files]

def content_vector(study,text):
    words=tokenize(text)
    vocab=set(study.idf)|set(NEIGHBORS)
    return vector((w for w in words if w in vocab),study.idf)

def refined(study,i,j):
    base=study.primary[i][j]/100
    if course_source.relation(study.files[i],study.files[j])==-1:
        return study.primary[i][j]
    values=[]
    for changed,other in ((i,j),(j,i)):
        if changed in study.extras:
            values.append(fuse(*channels(study.extras[changed],study.vectors[other])))
    if i in study.extras and j in study.extras:
        values.append(fuse(*channels(study.extras[i],study.extras[j])))
    evidence=max(values,default=0)
    return round(100*(base+(1-base)*.91*evidence))
