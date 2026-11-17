"""Recover course context from local download metadata without network requests."""
from collections import defaultdict
from urllib.parse import parse_qs, urlsplit
import json
import re


def hint(url):
    if not url:
        return None
    try:
        u = urlsplit(url)
        if u.scheme not in {"http", "https"} or not u.hostname or u.username:
            return None
        site = (u.hostname.casefold(), u.port)
        fields = {k.casefold(): v[0] for k,v in parse_qs(u.query,max_num_fields=120).items() if len(v)==1}
    except ValueError:
        return None
    # Prefer explicit course IDs, including course links in a referring LMS page.
    match = re.search(r"/courses/([0-9]+)(?:/|$)",u.path,re.I)
    course_id = fields.get("course_id") or fields.get("courseid") or (match[1] if match else "")
    if not course_id and u.path.endswith("/course/view.php"):
        course_id=fields.get("id","")
    if course_id and course_id!="0":
        return (site, "course"), course_id, None
    # Some LMS attachment endpoints repeat an opaque key over multiple postings.
    # Validate its partition in the corpus before using it as a course signal.
    if all(fields.get(k) for k in ("ky","content_seq","file_seq","lecture_main_div")):
        return (site, u.path, "attachment"), fields["ky"], fields["content_seq"]
    return None


def prepare(files):
    partitions = defaultdict(lambda: defaultdict(set))
    inferred = []
    for f in files:
        f.course_scope = None
        hints = [h for h in (hint(f.download.url), f.referrer_hint, hint(f.download.course_page)) if h]
        explicit = {h[:2] for h in hints if h[2] is None}
        if explicit:
            if len(explicit)==1:f.course_scope=explicit.pop()
            continue
        if hints:
            namespace,key,post = hints[0]
            partitions[namespace][key].add(post)
            inferred.append((f,namespace,key))
    repeated = {ns:{k for k,posts in groups.items() if len(posts)>=2}
                for ns,groups in partitions.items()}
    for f,namespace,key in inferred:
        supported = repeated[namespace]
        if len(supported)>=2 and key in supported:
            f.course_scope = (namespace,key)


def relation(a,b):
    if a.course_scope and b.course_scope and a.course_scope[0]==b.course_scope[0]:
        return 1 if a.course_scope==b.course_scope else -1
    # Without a course ID, two explicit course labels on the same registered LMS
    # can still be compared. A post title or a bare domain supplies no such signal.
    x,y=a.download,b.download
    if x.course_name and y.course_name and x.course_page and y.course_page:
        if urlsplit(x.course_page).netloc==urlsplit(y.course_page).netloc:
            return 1 if x.course_name.casefold().split()==y.course_name.casefold().split() else -1
    return 0


def group_scope(members):
    scopes={f.course_scope for f in members}
    if len(scopes)==1 and None not in scopes:
        return json.dumps(scopes.pop(),ensure_ascii=False,separators=(",",":"))
    return None
