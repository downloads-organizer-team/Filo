"""SQLite repository for group edits, explicit file relations and download events."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from uuid import uuid4
from organizer.analysis.constraints import Rules, Constraints
from organizer.models import DownloadContext
from organizer.files import storage
from organizer.analysis.course_source import group_scope

@contextmanager
def connection():
    storage.HOME.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(storage.HOME/"feedback.sqlite3",timeout=8)
    try:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS groups(gid TEXT PRIMARY KEY,title TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS course_titles(scope TEXT PRIMARY KEY,title TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS lms_sites(origin TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS placements(uid TEXT PRIMARY KEY,gid TEXT);
        CREATE TABLE IF NOT EXISTS relations(a TEXT,b TEXT,kind TEXT CHECK(kind IN ('must','cannot')),PRIMARY KEY(a,b));
        CREATE TABLE IF NOT EXISTS downloads(uid TEXT PRIMARY KEY,url TEXT,domain TEXT,page_title TEXT,downloaded_at TEXT,directory TEXT);
        CREATE TABLE IF NOT EXISTS revision(id INTEGER PRIMARY KEY CHECK(id=1),value INTEGER NOT NULL);
        INSERT OR IGNORE INTO revision VALUES(1,0);
        """)
        optional_columns=("course_name","course_page","source_page")
        if not set(optional_columns).issubset(row[1] for row in db.execute("PRAGMA table_info(downloads)")):
            db.execute("BEGIN IMMEDIATE")
            existing={row[1] for row in db.execute("PRAGMA table_info(downloads)")}
            for column in optional_columns:
                if column not in existing:
                    db.execute(f"ALTER TABLE downloads ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
            db.commit()
        yield db
        db.commit()
    finally:db.close()

def snapshot(db):
    return Rules(dict(db.execute("SELECT uid,gid FROM placements")),dict(db.execute("SELECT gid,title FROM groups")),
                 list(db.execute("SELECT a,b,kind FROM relations")),db.execute("SELECT value FROM revision WHERE id=1").fetchone()[0],
                 dict(db.execute("SELECT scope,title FROM course_titles")))

def load(files):
    with connection() as db:
        db.execute("BEGIN")
        rules=snapshot(db);lookup={f.uid:f for f in files}
        for uid,*fields in db.execute("SELECT uid,url,domain,page_title,downloaded_at,directory,course_name,course_page,source_page FROM downloads"):
            if uid in lookup:
                current=lookup[uid].download
                for name,value in zip(DownloadContext.__dataclass_fields__,fields):
                    if value:setattr(current,name,value)
        return rules

def record_download(uid,context):
    """Optional integration entry point. downloaded_at accepts ISO 8601."""
    with connection() as db:
        db.execute("""INSERT INTO downloads(uid,url,domain,page_title,downloaded_at,directory,course_name,course_page,source_page)
                      VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(uid) DO UPDATE SET
                      url=coalesce(nullif(excluded.url,''),url),domain=coalesce(nullif(excluded.domain,''),domain),
                      page_title=coalesce(nullif(excluded.page_title,''),page_title),
                      downloaded_at=coalesce(nullif(excluded.downloaded_at,''),downloaded_at),
                      directory=coalesce(nullif(excluded.directory,''),directory),
                      course_name=coalesce(nullif(excluded.course_name,''),course_name),
                      course_page=coalesce(nullif(excluded.course_page,''),course_page),
                      source_page=coalesce(nullif(excluded.source_page,''),source_page)""",
                   (uid,context.url,context.domain,context.page_title,context.downloaded_at,context.directory,context.course_name,context.course_page,context.source_page))

class CourseConflict(ValueError):
    pass

def save_edit(study,groups=(),unassigned=(),relation=None,*,allow_cross_course=False):
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        if snapshot(db).revision!=study.revision:
            raise ValueError("다른 창에서 검토 결과를 변경했습니다. 다시 분석한 뒤 적용하세요.")
        for gid,title,members in groups:
            if not title.strip():raise ValueError("묶음 이름을 입력하세요.")
            db.execute("INSERT OR REPLACE INTO groups VALUES(?,?)",(gid,title.strip()))
            db.executemany("INSERT OR REPLACE INTO placements VALUES(?,?)",((f.uid,gid) for f in members))
        db.executemany("INSERT OR REPLACE INTO placements VALUES(?,NULL)",((f.uid,) for f in unassigned))
        if relation:
            a,b,kind=relation;a,b=sorted((a.uid,b.uid))
            if a==b:raise ValueError("서로 다른 파일 두 개를 선택하세요.")
            if kind=="clear":db.execute("DELETE FROM relations WHERE a=? AND b=?",(a,b))
            else:db.execute("INSERT OR REPLACE INTO relations VALUES(?,?,?)",(a,b,kind))
        updated=Constraints(study.files,snapshot(db))
        if not allow_cross_course:
            conflict=updated.new_course_conflict(study.files,study.rules)
            if conflict:
                a,b=conflict
                raise CourseConflict(f"다운로드 기록상 다음 두 파일의 강좌가 다릅니다.\n\n{a.name}\n{b.name}\n\n같은 그룹으로 지정할까요?")
        db.execute("UPDATE revision SET value=value+1 WHERE id=1")

def assign(study,files,destination,*,allow_cross_course=False):
    selected=set(files);changed=[]
    for g in study.groups:
        if g is destination or selected.intersection(g.members):
            members=[m for m in g.members if m not in selected]
            if g is destination:members+=list(files)
            changed.append((g.gid,g.title,members))
    save_edit(study,changed,() if destination else files,allow_cross_course=allow_cross_course)

def merge(study,source,target,*,allow_cross_course=False):
    if source is target:raise ValueError("서로 다른 묶음을 선택하세요.")
    save_edit(study,[(target.gid,target.title,target.members+source.members)],allow_cross_course=allow_cross_course)

def split(study,source,chosen,title,*,allow_cross_course=False):
    selection=set(chosen)
    if not selection or not selection<set(source.members):raise ValueError("한 묶음에서 분리할 파일 일부만 체크하세요.")
    save_edit(study,[(source.gid,source.title,[f for f in source.members if f not in selection]),
                     (str(uuid4()),title,chosen)],allow_cross_course=allow_cross_course)

def rename(study,group,title,*,allow_cross_course=False):
    save_edit(study,[(group.gid,title,group.members)],allow_cross_course=allow_cross_course)

def set_course_title(study,group,title):
    title=title.strip()
    if not title:raise ValueError("과목명을 입력하세요.")
    scope=group_scope(group.members)
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        if snapshot(db).revision!=study.revision:
            raise ValueError("다른 창에서 결과를 변경했습니다. 다시 분석한 뒤 적용하세요.")
        if scope:
            db.execute("INSERT OR REPLACE INTO course_titles VALUES(?,?)",(scope,title))
            db.execute("UPDATE groups SET title=? WHERE gid=?",(title,group.gid))
        else:
            db.execute("INSERT OR REPLACE INTO groups VALUES(?,?)",(group.gid,title))
        db.execute("UPDATE revision SET value=value+1 WHERE id=1")

def create(study,files,title,*,allow_cross_course=False):
    if not files:raise ValueError("새 묶음에 넣을 파일을 체크하세요.")
    chosen=set(files)
    groups=[(g.gid,g.title,[f for f in g.members if f not in chosen]) for g in study.groups if chosen.intersection(g.members)]
    save_edit(study,[*groups,(str(uuid4()),title,files)],allow_cross_course=allow_cross_course)
