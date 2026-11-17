"""Line-delimited IPC for the desktop window. The Python engine owns all file paths and moves."""
from datetime import datetime
import json
import os
from pathlib import Path
from queue import Queue
import sys
from threading import Event, Thread
from uuid import uuid4

import engine
import feedback
import storage
from readers import course_cover
from similarity import compare


class Desktop:
    def __init__(self, status=lambda message:None):
        self.study=None
        self.status=status
        self.cancel=Event()
        self.plan=None
        self.generation=""

    def options(self):
        return dict(zip(("recursive","deep","covers"),storage.scan_options()))

    def scan(self,args):
        settings=dict(self.options(),**{k:v for k,v in args.items()
                                      if k in ("recursive","deep","covers") and isinstance(v,bool)})
        def check():
            if self.cancel.is_set():raise InterruptedError("분석을 취소했습니다.")
        self.plan=None
        study=engine.analyze(storage.downloads_folder(),settings["recursive"],settings["deep"],
                             check,self.status,course_covers=settings["covers"])
        storage.remember_options(settings["recursive"],settings["deep"],settings["covers"])
        self.study=study
        self.generation=uuid4().hex
        files=[dict(id=f.index,name=f.name,ext=f.ext,group=f.group.gid if f.group else None,
                    state=f.state,confidence=f.confidence,size=f.size,host=f.host) for f in study.files]
        groups=[dict(id=g.gid,title=g.title,note=g.title_note,confidence=g.confidence,count=len(g.members))
                for g in study.groups]
        return dict(root=str(study.root),files=files,groups=groups,options=settings,
                    generation=self.generation,time=datetime.now().strftime("%H:%M"),
                    elapsed=study.ms,medium=len(study.medium),attempted=len(study.attempted),
                    rescued=study.rescued,covers=sum(f.course_cover_checked for f in study.files))

    def group(self,gid):
        if not gid:return None
        return next(g for g in self.study.groups if g.gid==gid)

    def file(self,index):
        if type(index) is not int or not 0<=index<len(self.study.files):raise ValueError("파일을 다시 선택하세요.")
        return self.study.files[index]

    def selected(self,args):
        return [self.file(i) for i in dict.fromkeys(args.get("files",[]))]

    def detail(self,args):
        f=self.file(args["id"])
        clock=lambda t:datetime.fromtimestamp(t).strftime("%Y.%m.%d %H:%M")
        return dict(note=f.note,evidence=f.evidence,normalized=f.normalized,sequence=f.sequence,
                    versions=f.versions,tokens=f.tokens,roles=f.roles,path=str(f.path),
                    created=clock(f.created),modified=clock(f.modified),excerpt=f.excerpt_status,
                    course=f.download.course_name,page=f.download.page_title,source_page=f.download.source_page,
                    band=f.first_band)

    def matrix(self,args):
        start=max(0,int(args.get("start",0)));col=max(0,int(args.get("col",0)))
        return [list(row[col:col+10]) for row in self.study.matrix[start:start+10]]

    def pair(self,args):
        a,b=self.file(args["a"]),self.file(args["b"])
        s=self.study
        key=tuple(sorted((a.uid,b.uid)))
        rule=next((k for x,y,k in s.rules.rules.relations if (x,y)==key),None)
        return dict(primary=s.primary[a.index][b.index],score=s.matrix[a.index][b.index],
                    rule=rule,features=compare(s,a.index,b.index,details=True))

    def edit(self,args):
        files=self.selected(args);g=self.group(args.get("group"));dest=self.group(args.get("target"))
        kind=args["kind"];title=args.get("title","").strip()
        kw=dict(allow_cross_course=args.get("confirm") is True)
        if kind in ("rename","split","merge","course") and not g:raise ValueError("그룹을 선택하세요.")
        if kind in ("assign","split","create") and not files:raise ValueError("파일을 선택하세요.")
        if kind=="assign":feedback.assign(self.study,files,dest,**kw)
        elif kind=="create":feedback.create(self.study,files,title,**kw)
        elif kind=="split":feedback.split(self.study,g,files,title,**kw)
        elif kind=="merge" and dest:feedback.merge(self.study,g,dest,**kw)
        elif kind=="rename":feedback.rename(self.study,g,title,**kw)
        elif kind=="course":feedback.set_course_title(self.study,g,title)
        elif kind in ("must","cannot","clear") and len(files)==2:
            feedback.save_edit(self.study,relation=(*files,kind),**kw)
        else:raise ValueError("그룹과 파일 선택을 확인하세요.")
        self.plan=None
        return True

    def preview(self,args):
        s=self.study;kind=args.get("kind","organize");token=uuid4().hex
        self.plan=None
        if kind=="undo":
            log,records=storage.latest()
            if not log:raise ValueError("되돌릴 이동 기록이 없습니다.")
            rows=[dict(name=Path(r["dst"]).name,source=r["dst"],target=r["src"],skip="") for r in records if storage.pending(r)]
            plan=log
        else:
            if kind=="organize":
                plan=storage.plan_group_folders(s,self.group(args.get("group")))
            elif kind=="manual":
                destination=Path(args["destination"])
                if not destination.is_absolute() or not destination.is_dir():raise ValueError("대상 폴더를 확인하세요.")
                plan=[storage.FolderMove(f,destination/f.name,"같은 이름의 파일이 있습니다" if (destination/f.name).exists() else "")
                      for f in self.selected(args)]
            else:raise ValueError("지원하지 않는 작업입니다.")
            rows=[dict(name=p.file.name,source=str(p.file.path),target=str(p.target),skip=p.skip) for p in plan]
        self.plan=(token,kind,plan)
        return dict(token=token,rows=rows)

    def execute(self,args):
        if not self.plan or self.plan[0]!=args.get("token"):raise ValueError("미리보기를 다시 여세요.")
        _,kind,plan=self.plan;self.plan=None
        if kind=="undo":return storage.undo(plan)
        if feedback.load([]).revision!=self.study.revision:raise ValueError("그룹이 변경됐습니다. 다시 분석하세요.")
        return storage.move_files(plan,self.study.root if kind=="organize" else None)

    def run(self,action,args):
        if action=="scan":return self.scan(args)
        if action=="options":return self.options()
        if action=="openDownloads":
            os.startfile(storage.downloads_folder())
            return True
        if action=="bridge":
            from browser_bridge import register
            return str(register())
        if not self.study or args.get("generation")!=self.generation:raise ValueError("목록을 다시 분석하세요.")
        if action=="cover":
            g=self.group(args["group"])
            if g.title_kind in {"lms","cover","manual","confirmed"}:return [g.title,g.title_note]
            title,source=course_cover(g.members)
            return [title or g.title,source]
        if action not in ("detail","matrix","pair","edit","preview","execute"):raise ValueError("알 수 없는 작업입니다.")
        return getattr(self,action)(args)


def emit(payload):
    print(json.dumps(payload,ensure_ascii=False,separators=(",",":")),flush=True)

def main():
    desk=Desktop(lambda msg:emit({"status":msg}))
    pending=Queue()
    def receive():
        for line in sys.stdin:
            request=json.loads(line)
            if request["action"]=="cancel":desk.cancel.set()
            else:pending.put(request)
        desk.cancel.set();pending.put(None)
    Thread(target=receive,daemon=True).start()
    while (req:=pending.get()) is not None:
        try:
            if req["action"]=="scan":desk.cancel.clear()
            value=desk.run(req["action"],req.get("args",{}))
            emit(dict(id=req["id"],ok=True,value=value))
        except Exception as exc:
            emit(dict(id=req["id"],ok=False,error=str(exc) or type(exc).__name__,
                      code="courseConflict" if isinstance(exc,feedback.CourseConflict) else "error"))

if __name__=="__main__":main()
