"""Line-delimited IPC for the desktop window. The Python engine owns all file paths and moves."""
from datetime import datetime
import json
import os
from pathlib import Path
from queue import Queue
import sys
from threading import Event, Lock, Thread
from typing import Literal, overload
from uuid import uuid4

from organizer.analysis import engine
from organizer.analysis.scan_progress import ScanProgress
from organizer.files import feedback
from organizer.files import storage
from organizer.files import entry_names
from organizer.analysis.readers import course_cover
from organizer.analysis.similarity import compare
from organizer.models import Study, ScanOptions, ScanResult, FileRow, GroupRow, MoveRow, MovePreview, RelatedFile, HistoryEvent
from organizer.search.file_search import SearchResult
from organizer.search import file_search


def group_reason(group):
    kind=group.title_kind
    if group.destination_reason and group.destination:
        return group.destination_reason+" · "+group.destination.name
    if kind=="extension":return "확장자 · "+group.members[0].ext.upper()
    if kind=="batch":return "다운로드 시각 · "+group.title
    if kind=="manual":return "직접 지정 · "+group.title
    if kind=="folder":return "기존 폴더 · "+group.title
    if kind in {"confirmed","lms","cover"}:
        return {"confirmed":"확인한 과목명","lms":"강좌 출처","cover":"문서 표지"}[kind]+" · "+group.title
    if kind in {"filename","activity"} or group.title_note.startswith(("모든 파일 이름","파일명에 반복된")):
        return "파일명 · "+group.title
    return group.title_note.split(" · 기존 폴더 ")[0]


def layout_rows(plan):
    return [dict(id=p.file.index,mode=p.mode,target=str(p.target),skip=p.skip) for p in plan]


class Desktop:
    def __init__(self, status=lambda message:None):
        self._study:Study|None=None
        self.status=status
        self.cancel=Event()
        self.plan=None
        self.generation=""
        self.name_edit=None
        self.folder_ids={}

    @property
    def study(self) -> Study:
        if self._study is None:raise ValueError("목록을 먼저 분석하세요.")
        return self._study

    @study.setter
    def study(self,value:Study):
        self._study=value

    def options(self) -> ScanOptions:
        storage.recover_interrupted()
        _,deep,covers=storage.scan_options()
        minimum,mode=storage.organization_options()
        return ScanOptions(recursive=False,deep=deep,covers=covers,roots=storage.source_roots(),
                           minConfidence=minimum,folderMode=mode,groupBy=storage.grouping_option())

    def scan(self,args) -> ScanResult:
        self.name_edit=None
        settings=self.options()
        for key in ("deep","covers"):
            if isinstance(args.get(key),bool):settings[key]=args[key]
        def check():
            if self.cancel.is_set():raise InterruptedError("분석을 취소했습니다.")
        self.plan=None
        settings["roots"]=storage.validate_roots(args.get("roots",settings["roots"]))
        if not settings["roots"]:raise ValueError("정리할 폴더를 하나 이상 선택하세요.")
        minimum,mode=storage.validate_criteria(args.get("minConfidence",settings["minConfidence"]),
                                                args.get("folderMode",settings["folderMode"]))
        group_by=args.get("groupBy",settings["groupBy"])
        if group_by not in ("related","extension"):raise ValueError("묶는 기준을 확인하세요.")
        settings.update(minConfidence=minimum,folderMode=mode,groupBy=group_by)
        reporter=ScanProgress(self.status)
        def progress(done,total):
            check()
            reporter.update(done,total)
        study=engine.analyze(settings["roots"][0],False,settings["deep"],check,reporter.stage,progress=progress,
                             course_covers=settings["covers"],roots=settings["roots"],min_confidence=minimum,folder_mode=mode,group_by=group_by)
        reporter.stage("정리 목록 준비 중")
        layout=layout_rows(storage.plan_group_folders(study,mode=mode,progress=progress))
        check()
        storage.remember_options(False,settings["deep"],settings["covers"],settings["roots"],minimum,mode,group_by)
        self.study=study
        self.folder_ids={}
        for group in study.groups:
            if group.destination:
                try:
                    self.folder_ids[group.gid]=entry_names.identity(group.destination)[0]
                except (OSError,ValueError):
                    continue  # A destination can disappear during the scan.
        self.generation=uuid4().hex
        files=[FileRow(id=f.index,name=f.name,path=str(f.path),ext=f.ext,group=f.group.gid if f.group else None,
                    state=f.state,confidence=f.confidence,size=f.size,host=f.host,note=f.note) for f in study.files]
        groups=[GroupRow(id=g.gid,title=g.title,note=g.title_note,reason=group_reason(g),
                         folderEvidence=g.destination_reason.split(" · ") if g.destination_reason else [],
                         confidence=g.confidence,count=len(g.members))
                for g in study.groups]
        return ScanResult(root=str(study.root),roots=list(map(str,study.roots)),files=files,groups=groups,options=settings,
                    layout=layout,
                    generation=self.generation,time=datetime.now().strftime("%H:%M"),
                    elapsed=study.ms,medium=len(study.medium),attempted=len(study.attempted),
                    rescued=study.rescued,covers=sum(f.course_cover_checked for f in study.files))

    def group(self,gid):
        if not gid:return None
        group=next((g for g in self.study.groups if g.gid==gid),None)
        if group is None:raise ValueError("그룹이 변경됐습니다. 다시 분석하고 선택하세요.")
        return group

    def begin_name_edit(self,args):
        kind=args["entry"]
        expected=None
        if kind=="search":
            path=Path(args["source"])  # Supplied by Electron from its current result IDs.
        else:
            if args.get("generation")!=self.generation:raise ValueError("다시 분석하세요.")
            if kind=="file":
                f=self.file(args["id"])
                path,expected=f.path,f.uid
            elif kind=="folder":
                g=self.group(args["id"])
                if not g or not g.destination or g.gid not in self.folder_ids:
                    raise ValueError("기존 폴더를 다시 분석하고 선택하세요.")
                path,expected=g.destination,self.folder_ids[g.gid]
            else:raise ValueError("항목을 다시 선택하세요.")
        uid,folder=entry_names.identity(path)
        if expected and uid!=expected:raise ValueError("선택한 항목이 바뀌었습니다.")
        token=uuid4().hex
        self.name_edit=(token,path,uid)
        return dict(token=token,name=path.name,isFolder=folder)

    def rename_entry(self,args):
        if not self.name_edit or args.get("token")!=self.name_edit[0]:
            raise ValueError("이름을 바꿀 항목을 다시 선택하세요.")
        _,old,uid=self.name_edit
        new=entry_names.rename(old,args["title"],uid)
        self.name_edit=None
        self.plan=None
        result=dict(old=str(old),path=str(new),name=new.name,refresh=False)
        s=self._study
        if s:
            affected=[g for g in s.groups if g.destination==old]
            if affected and not any(root.is_relative_to(old) for root in s.roots):
                for g in affected:
                    g.destination=new
                    g.title_note=g.title_note.replace(str(old),str(new))
                    if g.title_kind in {"folder","extension"}:g.title=new.name
                result.update(layout=self.review({}),groups=[dict(id=g.gid,title=g.title,note=g.title_note,reason=group_reason(g)) for g in affected])
            elif any(root.is_relative_to(old) or old.parent==root for root in s.roots):
                result.update(refresh=True,roots=[entry_names.redirected(str(p),old,new) for p in s.roots])
                self._study=None
        return result

    def file(self,index):
        if type(index) is not int or not 0<=index<len(self.study.files):raise ValueError("파일을 다시 선택하세요.")
        return self.study.files[index]

    def selected(self,args):
        return [self.file(i) for i in dict.fromkeys(args.get("files",[]))]

    def detail(self,args):
        f=self.file(args["id"])
        clock=lambda t:datetime.fromtimestamp(t).strftime("%Y.%m.%d %H:%M")
        evidence=f.evidence
        if f.group and f.group.title_note and f.group.title_note!=f.note:
            evidence=f.group.title_note+"\n"+(evidence or "")
        return dict(note=f.note,evidence=evidence,normalized=f.normalized,sequence=f.sequence,
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
        assert s.rules is not None
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
        if kind=="folderTitle":
            if not g or g.destination:
                raise ValueError("이 화면에서는 제안된 새 폴더의 이름을 바꿀 수 있습니다.")
            if not title or storage.folder_name(title)!=title:
                raise ValueError("Windows 폴더 이름에 사용할 수 있는 문자로 100자 이내로 입력하세요.")
            if (os.path.lexists(self.study.root/title) or
                    any(other is not g and not other.destination and storage.folder_name(other.title).casefold()==title.casefold()
                        for other in self.study.groups)):
                raise ValueError("다른 폴더가 이 이름을 사용합니다.")
            # Only the title changes. Keep the current file evidence and checkbox selection.
            feedback.save_edit(self.study,[(g.gid,title,[])])
            self.study.revision+=1
            self.study.rules.rules.names[g.gid]=title
            self.study.rules.rules.revision=self.study.revision
            g.title=title
            if g.title_kind!="extension":
                g.title_kind,g.title_note="manual","사용자가 지정한 폴더 이름"
            self.plan=None
            return dict(title=title,note=g.title_note,reason=group_reason(g),layout=self.review({}))
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

    def organize_plan(self,args):
        ids = {f.index for f in self.selected(args)} if "files" in args else None
        return storage.plan_group_folders(self.study,self.group(args.get("group")),args.get("destination"),
                                          args.get("destinationMode",self.study.folder_mode),file_ids=ids)

    def review(self,args):
        return layout_rows(self.organize_plan(args))

    def preview(self,args) -> MovePreview:
        kind=args.get("kind","organize");token=uuid4().hex
        self.plan=None
        if kind=="undo":
            log,records=storage.history_batch(args["batch"]) if "batch" in args else storage.latest()
            if not log:raise ValueError("되돌릴 이동 기록이 없습니다.")
            rows=[]
            indices=set()
            blocked=[]
            for i,r in enumerate(records):
                if storage.pending(r):
                    reason=storage.restore_reason(r)
                    rows.append(MoveRow(name=Path(r["dst"]).name,source=r["dst"],target=r["src"],skip=reason))
                    if reason:
                        blocked.append(storage.result_line(dict(r,reason=reason),undoing=True))
                    else:
                        indices.add(i)
            plan=(log,indices,blocked)
        else:
            s=self.study
            if kind=="organize":
                plan=self.organize_plan(args)
            elif kind=="manual":
                destination=storage.check_directory(Path(args["destination"]))
                plan=[storage.FolderMove(f,destination/f.name,"같은 이름의 파일이 있습니다" if (destination/f.name).exists() else "",
                                        tuple(s.roots or [s.root]),destination,"existing",tuple(storage.file_identity(destination)))
                      for f in self.selected(args)]
            else:raise ValueError("지원하지 않는 작업입니다.")
            plan=storage.confirm_plan(plan)
            rows=[MoveRow(name=p.file.name,source=str(p.file.path),target=str(p.target),skip=p.skip) for p in plan]
        self.plan=(token,kind,plan)
        return MovePreview(token=token,rows=rows)

    def execute(self,args):
        if not self.plan or self.plan[0]!=args.get("token"):raise ValueError("미리보기를 다시 여세요.")
        _,kind,plan=self.plan;self.plan=None
        if kind=="undo":
            log,indices,blocked=plan
            return storage.undo(log,indices)+blocked
        if feedback.load([]).revision!=self.study.revision:raise ValueError("그룹이 변경됐습니다. 다시 분석하세요.")
        return storage.move_files(plan)

    @overload
    def run(self,action:Literal["scan"],args) -> ScanResult: ...
    @overload
    def run(self,action:Literal["options","sources"],args) -> ScanOptions: ...
    @overload
    def run(self,action:Literal["preview"],args) -> MovePreview: ...
    @overload
    def run(self,action:Literal["execute"],args) -> list[str]: ...
    @overload
    def run(self,action:Literal["search"],args) -> SearchResult: ...
    @overload
    def run(self,action:Literal["related"],args) -> list[RelatedFile]: ...
    @overload
    def run(self,action:Literal["history"],args) -> list[HistoryEvent]: ...
    @overload
    def run(self,action:Literal["openDownloads"],args) -> bool: ...
    @overload
    def run(self,action:Literal["edit"],args) -> bool|dict: ...
    @overload
    def run(self,action:Literal["bridge"],args) -> str: ...
    @overload
    def run(self,action:Literal["detail","matrix","pair","cover"],args): ...
    def run(self,action,args):
        if action=="beginRename":return self.begin_name_edit(args)
        if action=="renameEntry":return self.rename_entry(args)
        if action=="doubleClickTime":
            import ctypes
            return ctypes.windll.user32.GetDoubleClickTime() if os.name=="nt" else 500
        if action=="scan":return self.scan(args)
        if action=="options":return self.options()
        if action=="history":return storage.recent_history()
        if action=="historyDetail":
            _,rows=storage.history_batch(args.get("batch"))
            return [dict(source=r["src"],target=r["dst"],status=r["status"],reason=r.get("reason",""),
                         operation=r.get("operation","move"),recordedSource=r.get("recorded_src"),recordedTarget=r.get("recorded_dst"),
                         pending=storage.pending(r)) for r in rows]
        if action=="sources":
            roots=storage.validate_roots(args.get("roots"))
            options=self.options()
            storage.remember_options(options["recursive"],options["deep"],options["covers"],roots)
            self.plan=None
            return self.options()
        if action=="search":
            return file_search.search(args.get("query",""))
        if action=="preview" and args.get("kind")=="undo":return self.preview(args)
        if action=="execute" and self.plan and self.plan[1]=="undo":return self.execute(args)
        if action=="openDownloads":
            os.startfile(storage.downloads_folder())
            return True
        if action=="bridge":
            from organizer.browser.browser_bridge import register
            return str(register())
        if self._study is None or args.get("generation")!=self.generation:raise ValueError("목록을 다시 분석하세요.")
        if self.study.group_by=="extension" and (action in {"related","matrix","pair","cover"} or
                (action=="edit" and args.get("kind")!="folderTitle")):
            raise ValueError("파일 관계를 검토하려면 관련 작업별로 분석하세요.")
        if action=="related":
            from organizer.analysis.matrix import related
            return related(self.study,self.file(args["id"]).index)
        if action=="cover":
            g=self.group(args["group"])
            if g is None:raise ValueError("그룹을 선택하세요.")
            if g.title_kind in {"lms","cover","manual","confirmed"}:return [g.title,g.title_note]
            title,source=course_cover(g.members)
            return [title or g.title,source]
        if action not in ("detail","matrix","pair","edit","review","preview","execute"):raise ValueError("알 수 없는 작업입니다.")
        return getattr(self,action)(args)


output_lock=Lock()

def emit(payload):
    with output_lock:
        print(json.dumps(payload,ensure_ascii=False,separators=(",",":")),flush=True)

def main():
    storage.recover_interrupted()
    desk=Desktop(lambda msg:emit({"status":msg}))
    pending=Queue()
    searches=Queue()
    def search_worker():
        worker=file_search.SearchWorker()
        try:
            try:
                worker.request(None)
            except OSError:
                pass  # The current query retries when Everything starts later.
            while (item:=searches.get()) is not None:
                request,cancelled=item
                def check():
                    if cancelled.is_set():raise InterruptedError("검색을 취소했습니다.")
                try:
                    check()
                    query=file_search.validate_query(request.get("args",{}).get("query"))
                    try:
                        result=worker.request(query,check)
                    except file_search.EverythingUnavailable:
                        if worker.engine is None:
                            raise
                        result=file_search.quick_search(query,check)
                    check()
                    emit(dict(id=request["id"],ok=True,value=result))
                except Exception as exc:
                    code="everythingUnavailable" if isinstance(exc,file_search.EverythingUnavailable) else "error"
                    emit(dict(id=request["id"],ok=False,error=str(exc),code=code))
        finally:
            worker.close()
    search_thread=Thread(target=search_worker,daemon=True)
    search_thread.start()
    def receive():
        last_search=Event()
        for line in sys.stdin:
            request=json.loads(line)
            if request["action"]=="cancel":desk.cancel.set()
            elif request["action"] in ("search","cancelSearch"):
                last_search.set()
                if request["action"]=="search":
                    last_search=Event()
                    searches.put((request,last_search))
            else:pending.put(request)
        last_search.set();searches.put(None);desk.cancel.set();pending.put(None)
    Thread(target=receive,daemon=True).start()
    while (req:=pending.get()) is not None:
        try:
            if req["action"] in ("scan","search"):desk.cancel.clear()
            value=desk.run(req["action"],req.get("args",{}))
            emit(dict(id=req["id"],ok=True,value=value))
        except Exception as exc:
            emit(dict(id=req["id"],ok=False,error=str(exc) or type(exc).__name__,
                      code="courseConflict" if isinstance(exc,feedback.CourseConflict) else "error"))
    search_thread.join()

if __name__=="__main__":main()
