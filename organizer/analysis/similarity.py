from collections import Counter
from math import log, sqrt
import os
from datetime import datetime
from urllib.parse import urlsplit
from organizer.analysis.features import LEXICON, ALIASES, TASK_GENERIC, TASK_SEPARATOR, VERSION, clean, tokenize, task_name, task_prefixes
from organizer.models import Vector
from organizer.analysis import course_source
from organizer.analysis.topics import TAG, activities, activity_relation, bilingual_topics, display, opaque_format
import re

NEIGHBORS={}
for context,words in LEXICON.items():
    for word in words:
        NEIGHBORS.setdefault(ALIASES.get(word,word),set()).add(context)

def unit(values):
    length=sqrt(sum(x*x for x in values.values()))
    return {k:v/length for k,v in values.items()} if length else {}

def vector(tokens,idf):
    counts=Counter(w for w in tokens if w not in TASK_GENERIC)
    literal={w:(1+log(n))*idf.get(w,1.5) for w,n in counts.items()}
    context:dict[str,float]={}
    for w in counts:
        for link in NEIGHBORS.get(w,()):context[link]=context.get(link,0)+1+log(counts[w])
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

def source_page_key(url):
    """Keep query identifiers: /project?id=A and /project?id=B are not one page."""
    if not url:return None
    try:
        page=urlsplit(url)
        if page.scheme=="https" and page.hostname and not page.username and page.path.strip("/"):
            return page.netloc.casefold(),page.path.rstrip("/"),page.query
    except ValueError:
        pass

def same_source_page(a,b):
    x,y=source_page_key(a.download.source_page),source_page_key(b.download.source_page)
    return bool(x and x==y)

def task_conflict(s,i,j):
    relation=activity_relation(s.activities[i],s.activities[j])
    if relation:
        return relation < 0
    x,y=s.task_prefixes[i],s.task_prefixes[j]
    a,b=s.files[i],s.files[j]
    return bool(x and y and (x!=y or (a.year and b.year and a.year!=b.year)))

def compare(s,i,j,details=False):
    a,b=s.files[i],s.files[j]
    lex,sem,char=channels(s.vectors[i],s.vectors[j])
    base=fuse(lex,sem,char)
    seq=bool(a.pattern and a.pattern==b.pattern and abs(a.number-b.number)<=2)
    same_dir=bool(s.parents[i] and s.parents[i]==s.parents[j])
    timing=.5*bool(a.created and b.created and abs(a.created-b.created)<=86400)+.5*bool(a.modified and b.modified and abs(a.modified-b.modified)<=172800)
    downloaded=s.download_times[i],s.download_times[j]
    if all(downloaded) and abs(downloaded[0]-downloaded[1])<=86400:timing=1
    host=bool(a.host and a.host==b.host)
    source_page=bool(s.source_pages[i] and s.source_pages[i]==s.source_pages[j])
    task=bool(s.task_prefixes[i] and s.task_prefixes[i]==s.task_prefixes[j])
    variant=task and s.task_heads[i]!=s.task_heads[j]
    if variant and not (same_dir or timing or source_page):task=False
    if task:base+=(1-base)*(.68 if variant else .55)
    version=bool((a.versions or b.versions) and a.normalized==b.normalized and s.vectors[i].literal)
    context=.035*seq+.045*same_dir+.03*timing+.018*host+.012*bool(host and a.download.directory and a.download.directory==b.download.directory)+.02*bool(s.role_sets[i]&s.role_sets[j])+.08*version+.05*source_page
    # A cited publication year alone says nothing about the term of a course.
    different_term = a.academic_year and b.academic_year and a.academic_year!=b.academic_year
    different_edition = a.year and b.year and a.year!=b.year and a.normalized==b.normalized
    if different_edition and not different_term:base*=.55
    score=base+(1-base)*context
    if s.bilingual_topics[i] and s.bilingual_topics[i]==s.bilingual_topics[j] and not (a.year and b.year and a.year!=b.year):
        score=max(score,.92)
    scope=course_source.relation(a,b)
    activity=activity_relation(s.activities[i],s.activities[j])
    if activity==1:
        score=max(score,.96)
    batch=False
    if s.opaque_formats[i] or s.opaque_formats[j]:
        close_downloads=all(t is not None for t in downloaded) and abs(downloaded[0]-downloaded[1])<=300
        same_origin_creation=(downloaded==(None,None) and host and a.created and b.created
                              and abs(a.created-b.created)<=120)
        batch=bool(s.opaque_formats[i] and s.opaque_formats[i][1]>=16 and s.opaque_formats[i]==s.opaque_formats[j]
                   and a.ext==b.ext and a.path.parent==b.path.parent and (close_downloads or same_origin_creation))
        score=.82 if batch else 0.
    if scope==1:
        inferred=a.course_scope and a.course_scope[0][-1]=="attachment"
        score=score+(1-score)*(.26 if inferred else .76)
    elif scope==-1:score=min(score,.45)
    if activity<0 or (task_conflict(s,i,j) and scope!=1):score=min(score,.45)
    if different_term:score*=.55
    if details:return dict(literal=lex,semantic=sem,string=char,context=context,sequence=seq,folder=same_dir,time=timing,source=host,source_page=source_page,version=version,course=scope,task=task,activity=activity==1,batch=batch)
    return round(100*score)

def prepare(study):
    course_source.prepare(study.files)
    study.activities=activities(study.files)
    study.bilingual_topics=bilingual_topics(study.files)
    study.opaque_formats=[opaque_format(f.path.stem) for f in study.files]
    authors=set()
    for f in study.files:
        authors.update(re.findall(r"(?:작성자|제출자|담당자|\d+반)[ _:.-]*([가-힣]{2,4})(?![가-힣])", f.path.stem))
        authors.update(re.findall(r"(?:^|[_ (.-])([가-힣]{2,4})\s*\(\d{4,10}\)",f.path.stem))
        authors.update(re.findall(r"(?:^|[_ -])\d{6,10}[_ -]+([가-힣]{2,4})$",f.path.stem))
    study.task_prefixes=task_prefixes(study.files)
    study.task_prefixes=["" if p in authors else p for p in study.task_prefixes]
    study.task_heads=[TASK_SEPARATOR.split(VERSION.sub("",clean(f.path.stem)),maxsplit=1)[0].strip() for f in study.files]
    study.parents=[os.path.normcase(os.path.abspath(f.path.parent)) if clean(f.path.parent.name) not in
                   TASK_GENERIC|{"공용","inbox"} else "" for f in study.files]
    study.source_pages=[source_page_key(f.download.source_page) for f in study.files]
    study.role_sets=[frozenset(f.roles) for f in study.files]
    study.download_times=[]
    for f in study.files:
        try:
            timestamp=datetime.fromisoformat(f.download.downloaded_at)
            study.download_times.append(timestamp.timestamp() if timestamp.tzinfo else None)
        except (ValueError,OverflowError,OSError):
            study.download_times.append(None)
    df=Counter(w for f in study.files for w in set(f.tokens))
    study.idf={w:1+log((len(study.files)+1)/(n+1)) for w,n in df.items()}
    study.vectors=[]
    for f,fmt in zip(study.files,study.opaque_formats):
        stem=display(f.path.stem)
        labels={tag.casefold() for tag in TAG.findall(stem)}
        if labels:
            labels.difference_update(tokenize(TAG.sub(" ",stem)))
        study.vectors.append(vector(() if fmt else (w for w in f.tokens if w not in authors and w not in labels),
                                    study.idf))
    known={p for p in study.task_prefixes if p}
    for i,f in enumerate(study.files):
        parent,_=task_name(f.path.parent.name+"_file")
        if not study.vectors[i].literal and parent in known:study.task_prefixes[i]=parent

def content_vector(study,text):
    words=tokenize(text)
    vocab=set(study.idf)|set(NEIGHBORS)
    return vector((w for w in words if w in vocab),study.idf)

def refined(study,i,j):
    base=study.primary[i][j]/100
    scope=course_source.relation(study.files[i],study.files[j])
    if (scope==-1 or activity_relation(study.activities[i],study.activities[j])<0
            or study.opaque_formats[i] or study.opaque_formats[j] or (task_conflict(study,i,j) and scope!=1)):
        return study.primary[i][j]
    values=[]
    for changed,other in ((i,j),(j,i)):
        # A descriptive filename needs its own link to this topic. A word in
        # a long excerpt is enough to complement a blank title, not replace one.
        if changed in study.extras and (not study.vectors[changed].literal or base>=.50):
            values.append(fuse(*channels(study.extras[changed],study.vectors[other])))
    if i in study.extras and j in study.extras and base>=.50:
        values.append(fuse(*channels(study.extras[i],study.extras[j])))
    evidence=max(values,default=0)
    return round(100*(base+(1-base)*.91*evidence))
