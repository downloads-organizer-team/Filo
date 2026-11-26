from datetime import datetime
from dataclasses import dataclass, replace
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path
from zipfile import ZipFile
from uuid import UUID, uuid4
from urllib.parse import quote
import ctypes
import json
import os
import re
import stat
from models import File, HistoryEvent
from scanner import check_directory, file_uid
from eligibility import MIN_UNIQUE, check_source, checksum, minimum_reason

HOME=Path(os.environ["MOA_HOME"]) if os.environ.get("MOA_HOME") else Path(os.environ.get("LOCALAPPDATA",str(Path.home())))/"MoaFileReview"

def downloads_folder():
    """Use the current user's Windows Downloads location, including redirections."""
    if os.environ.get("MOA_DOWNLOADS"):return Path(os.environ["MOA_DOWNLOADS"]).absolute()
    folder_id = (ctypes.c_ubyte * 16).from_buffer_copy(
        UUID("374DE290-123F-4565-9164-39C4925E467B").bytes_le)
    get_path = ctypes.windll.shell32.SHGetKnownFolderPath
    get_path.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                         ctypes.POINTER(ctypes.c_wchar_p)]
    get_path.restype = ctypes.c_long
    release = ctypes.windll.ole32.CoTaskMemFree
    release.argtypes = [ctypes.c_void_p]
    release.restype = None
    result = ctypes.c_wchar_p()
    try:
        # KF_FLAG_DONT_VERIFY lets the scanner report unavailable drives in its worker.
        hr = get_path(ctypes.byref(folder_id), 0x4000, None, ctypes.byref(result))
        if hr or not result.value:
            raise OSError(f"Windows 다운로드 폴더 위치를 확인할 수 없습니다 (0x{hr & 0xffffffff:08X}).")
        return Path(result.value)
    finally:
        release(result)

def scan_options():
    for name in ("download-settings.json", "campus-session.json"):
        try:
            value=json.loads((HOME/name).read_text(encoding="utf-8"))
            if isinstance(value, dict):
                recursive=name=="download-settings.json" and value.get("recursive") is True
                return recursive,value.get("deep") is not False,value.get("course_covers") is not False
        except (OSError,ValueError):
            continue
    return False,True,True

def source_roots():
    try:
        value=json.loads((HOME/"download-settings.json").read_text(encoding="utf-8"))
        roots=value.get("roots") if isinstance(value,dict) else None
        if isinstance(roots,list):
            return list(dict.fromkeys(str(Path(p)) for p in roots if isinstance(p,str) and Path(p).is_absolute()))
    except (OSError,ValueError):pass
    return [str(downloads_folder().absolute())]


def organization_options():
    try:
        value=json.loads((HOME/"download-settings.json").read_text(encoding="utf-8"))
        return validate_criteria(value.get("minConfidence",.7),value.get("folderMode","reuse"))
    except (OSError,ValueError,AttributeError):
        return .7,"reuse"


def validate_criteria(minimum,mode):
    if type(minimum) not in (int,float) or minimum not in [i/10 for i in range(11)]:
        raise ValueError("최소 신뢰도는 0부터 1까지 0.1 단위로 선택하세요.")
    if mode not in ("new","reuse"):
        raise ValueError("기존 폴더 활용 방식을 선택하세요.")
    return minimum,mode


def validate_roots(roots):
    if not isinstance(roots,list) or any(not isinstance(p,str) for p in roots):
        raise ValueError("원본 폴더 목록을 확인하세요.")
    result=[]
    keys=set()
    for value in roots:
        path=check_directory(Path(value))
        key=os.path.normcase(str(path))
        if key not in keys:result.append(str(path));keys.add(key)
    return result


def grouping_option():
    try:
        value=json.loads((HOME/"download-settings.json").read_text(encoding="utf-8"))
        return "extension" if value.get("groupBy")=="extension" else "related"
    except (OSError,ValueError,AttributeError):
        return "related"


def remember_options(recursive,deep,course_covers=True,roots=None,minimum=None,mode=None,group_by=None):
    old_min,old_mode=organization_options()
    try:
        HOME.mkdir(parents=True,exist_ok=True)
        save(HOME/"download-settings.json",dict(recursive=recursive,deep=deep,course_covers=course_covers,
                                               roots=source_roots() if roots is None else list(map(str,roots)),
                                               minConfidence=old_min if minimum is None else minimum,
                                               folderMode=old_mode if mode is None else mode,
                                               groupBy=group_by or grouping_option()))
    except OSError:pass

def sample():
    root=HOME/"Samples"/(datetime.now().strftime("%Y%m%d-%H%M%S")+"-"+uuid4().hex[:6])
    root.mkdir(parents=True)
    with ZipFile(Path(__file__).with_name("demo.zip")) as z:
        for i in z.infolist():
            p=root/i.filename
            p.resolve().relative_to(root.resolve())
            p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(i))
            day=12
            if os.name=="nt" and p.suffix.lower() in (".pdf",".pptx"):
                try:
                    with open(str(p)+":Zone.Identifier","w",encoding="utf-8") as ads:
                        ads.write("[ZoneTransfer]\nZoneId=3\nHostUrl=https://campus.example/downloads/"+quote(p.name)+"\n")
                except OSError:pass
            stamp=datetime(2026,3,day,10).timestamp();os.utime(p,(stamp,stamp))
    return root

def save(p,batch):
    temp=p.with_name(p.name+"."+uuid4().hex+".tmp")
    try:
        with temp.open("x",encoding="utf-8") as f:
            json.dump(batch,f,ensure_ascii=False,indent=1);f.flush();os.fsync(f.fileno())
        os.replace(temp,p)
    finally:temp.unlink(missing_ok=True)

def relocate(src,dst):
    # On Windows MoveFileEx without REPLACE_EXISTING refuses a competing destination.
    if os.name=="nt":
        native=ctypes.WinDLL("kernel32",use_last_error=True).MoveFileExW
        native.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_uint];native.restype=ctypes.c_int
        if not native(str(src),str(dst),2):raise ctypes.WinError(ctypes.get_last_error())
        if src.exists():raise OSError("원본을 제거할 수 없어 두 위치를 확인해야 합니다.")
    else:
        os.link(src,dst);src.unlink()

@dataclass(frozen=True)
class FolderMove:
    file: File
    target: Path
    skip: str = ""
    roots: tuple[Path,...] = ()
    destination: Path | None = None
    mode: str = "new"
    destination_id: tuple[int,int] | None = None
    digest: str = ""


def folder_name(title):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")[:100].rstrip(" .") or "그룹"
    device = name.split(".", 1)[0].rstrip().upper()
    if re.fullmatch(r"CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[0-9¹²³]", device):
        name = "_" + name
    return name


def check_group_paths(root, source, target, roots=None, mode="new"):
    root=check_directory(root)
    roots=tuple(map(Path,roots)) if roots else (root,)
    if (not source.is_absolute() or not target.is_absolute()
            or not any(source.is_relative_to(p) and source!=p for p in roots)
            or source.resolve()!=source or target.parent.resolve()!=target.parent
            or (target.parent.parent!=root if mode=="new" else target.parent!=root)):
        raise OSError("다운로드 안의 원래 경로를 확인할 수 없습니다.")
    for source_root in roots:check_directory(source_root)
    check_directory(source.parent)
    if os.path.lexists(target.parent):
        info = target.parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError("그룹 폴더 위치에 파일 또는 연결 경로가 있습니다.")


def plan_group_folders(study, selected=None, destination=None, mode="new", *, file_ids=None, progress=None):
    if mode not in ("new","existing","reuse"):raise ValueError("대상 폴더 방식을 확인하세요.")
    if mode=="existing" and destination is None:raise ValueError("대상 폴더를 선택하세요.")
    destination=check_directory(Path(destination) if destination is not None else study.root)
    roots=tuple(study.roots or [study.root])
    plan = []
    names = set()
    reserved = set()
    if progress:
        total = sum(1 for g in study.groups if selected is None or g is selected
                    for f in g.members if file_ids is None or f.index in file_ids)
        progress(0, total)
    for group in sorted(study.groups, key=lambda g: (g.title.casefold(), g.gid)):
        base = folder_name(group.title)
        name = base
        suffix = 2
        while name.casefold() in names or (mode!="existing" and os.path.lexists(destination/name)):
            name = f"{base} ({suffix})"
            suffix += 1
        names.add(name.casefold())
        if selected is not None and group is not selected:
            continue
        members=[f for f in group.members if file_ids is None or f.index in file_ids]
        if not members:
            continue
        reuse=group.destination if mode=="reuse" else None
        parent=reuse or destination
        move_mode="existing" if reuse or mode=="existing" else "new"
        folder_id=None
        parent_error=""
        if move_mode=="existing":
            try:
                info=check_directory(parent).stat()
                folder_id=(info.st_dev,info.st_ino)
            except OSError as error:
                parent_error=str(error)
        for file in sorted(members, key=lambda f: str(f.path).casefold()):
            target = parent / name / file.name if move_mode=="new" else parent / file.name
            skip = ""
            try:
                if parent_error or file.hold_reason:raise OSError(parent_error or file.hold_reason)
                check_source(file)
                check_group_paths(parent, file.path, target, roots, move_mode)
                if target == file.path:
                    skip = "이미 정리됨"
                elif os.path.lexists(target) or target in reserved:
                    skip = "같은 이름의 파일이 있습니다"
                else:
                    reserved.add(target)
            except (OSError, RuntimeError) as error:
                skip = str(error)
            plan.append(FolderMove(file, target, skip, roots, parent, move_mode, folder_id))
            if progress:
                progress(len(plan), total)
    return apply_minimum(plan)


def apply_minimum(plan):
    counts = Counter(p.target.parent for p in plan if p.mode == "new" and not p.skip)
    return [replace(p,skip=minimum_reason(counts[p.target.parent]))
            if p.mode=="new" and not p.skip and counts[p.target.parent]<MIN_UNIQUE else p for p in plan]


def confirm_plan(plan):
    """Bind the confirmation to the bytes on disk and recheck the folder threshold."""
    result = []
    seen = set()
    reserved = set()
    for item in plan:
        if not item.skip:
            try:
                if item.destination:
                    check_group_paths(item.destination,item.file.path,item.target,item.roots,item.mode)
                if os.path.lexists(item.target) or item.target in reserved:
                    raise OSError("목적지에 같은 이름이 있습니다.")
                check_source(item.file)
                digest = checksum(item.file.path)
                check_source(item.file)
                if item.file.digest and digest != item.file.digest:
                    raise OSError("분석 후 파일 내용이 바뀌었습니다.")
                if digest in seen:
                    raise OSError("동일 내용의 사본")
                seen.add(digest)
                reserved.add(item.target)
                item = replace(item,digest=digest)
            except OSError as error:
                item = replace(item,skip=str(error))
        result.append(item)
    return apply_minimum(result)


def move(items,dest):
    return move_files(FolderMove(f,Path(dest)/f.name,mode="existing") for f in items)


@contextmanager
def history_lock():
    # The OS releases the lock on process exit, including a crash during a rename.
    directory = HOME / "History"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a+b") as stream:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield directory
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def file_identity(directory):
    info = check_directory(directory).stat()
    return [info.st_dev,info.st_ino]


def validate_destination(row, created=None):
    if not row.get("group_root"):
        return
    root = Path(row["group_root"])
    src, dst = Path(row["src"]), Path(row["dst"])
    check_group_paths(root,src,dst,row.get("source_roots"),row.get("destination_mode","new"))
    expected = created or row.get("destination_id")
    if expected and file_identity(dst.parent) != expected:
        raise OSError("대상 폴더가 바뀌었습니다.")


def move_files(plan, group_root=None):
    with history_lock() as directory:
        recover_locked(directory)
        return execute_moves(list(plan), group_root, directory)


def execute_moves(plan, group_root, directory):
    rows = []
    reserved = set()
    seen = set()
    for item in plan:
        f, target = item.file, item.target
        root = item.destination or group_root
        row = dict(src=str(f.path),dst=str(target),uid=f.uid,size=f.size,mtime_ns=f.mtime_ns,
                   destination_mode=item.mode,status="planned",sha="")
        rows.append(row)
        if root:
            row.update(group_root=str(root),source_roots=list(map(str,item.roots or [root])))
        if item.destination_id:
            row["destination_id"] = list(item.destination_id)
        try:
            if item.skip:
                raise OSError(item.skip)
            validate_destination(row)
            if item.mode == "new" and os.path.lexists(target.parent):
                raise OSError("미리보기 후 새 폴더 위치가 사용 중입니다.")
            check_source(f)
            if os.path.lexists(target) or target in reserved:
                raise OSError("목적지에 같은 이름이 있습니다.")
            row["sha"] = checksum(f.path)
            if (item.digest or f.digest) and row["sha"] != (item.digest or f.digest):
                raise OSError("미리보기 후 파일 내용이 바뀌었습니다.")
            if row["sha"] in seen:
                raise OSError("동일 내용의 사본")
            seen.add(row["sha"])
            reserved.add(target)
        except (OSError, RuntimeError) as error:
            row.update(status="skipped",reason=str(error))

    grouped = new_folder_rows(rows)
    for members in grouped.values():
        ready = [r for r in members if r["status"]=="planned"]
        if len(ready) < MIN_UNIQUE:
            for r in ready:
                r.update(status="skipped",reason=minimum_reason(len(ready)))

    if not rows:
        return []
    log = directory / (datetime.now().strftime("%Y%m%d-%H%M%S-%f")+"-"+uuid4().hex[:6]+".json")
    rows[0]["transaction"] = "moving"
    save(log,rows)
    created = {}
    for row,item in zip(rows,plan):
        if row["status"]!="planned":
            continue
        src, dst = item.file.path, item.target
        try:
            validate_destination(row,created.get(dst.parent))
            check_source(item.file)
            if checksum(src)!=row["sha"]:
                raise OSError("미리보기 후 파일 내용이 바뀌었습니다.")
            if item.mode=="new" and dst.parent not in created:
                dst.parent.mkdir()
                row["created_dir"] = created[dst.parent] = file_identity(dst.parent)
            if dst.parent in created:
                row["destination_id"] = created[dst.parent]
            validate_destination(row)
            row["status"] = "moving"
            save(log,rows)
            relocate(src,dst)
            row["status"] = "moved"
            row["dst_uid"] = file_uid(dst,dst.lstat())
        except (OSError,RuntimeError) as error:
            if row["status"]=="moving":
                reconcile(row)
            if row["status"]!="moved":
                row.update(status="skipped",reason=str(error))
        save(log,rows)
    finish_move(log,rows)
    return [result_line(r) for r in rows]


def new_folder_rows(rows):
    groups = defaultdict(list)
    for row in rows:
        if row.get("destination_mode")=="new":
            groups[Path(row["dst"]).parent].append(row)
    return groups


def remove_empty_group_dirs(rows):
    for row in rows:
        if not row.get("created_dir"):continue
        directory=Path(row["dst"]).parent
        try:
            if (directory.parent==Path(row["group_root"]) and row["created_dir"][1]
                    and file_identity(directory)==row["created_dir"]):
                directory.rmdir()
        except (OSError,RuntimeError):
            pass  # Retain populated, replaced, or unavailable folders.


def matching(path, row, uid=None):
    info=path.lstat()
    return (stat.S_ISREG(info.st_mode)
            and not getattr(info,"st_file_attributes",0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            and (not uid or file_uid(path,info)==uid)
            and checksum(path)==row["sha"])


def reconcile(row):
    """Inspect only operations with a persisted intent and an unknown outcome."""
    src, dst = Path(row["src"]), Path(row["dst"])
    if row["status"]=="moving":
        try:
            arrived = os.path.lexists(dst) and (not os.path.lexists(src)
                      or file_uid(dst,dst.lstat())==row["uid"])
        except OSError:
            arrived = False
        if arrived:
            row.update(status="moved",reason="중단된 이동 · 현재 파일 확인 필요")
        else:
            row.update(status="skipped",reason="이동 중단 · 두 경로를 확인하세요.")
    elif row["status"]=="restoring":
        try:
            if not os.path.lexists(dst) and matching(src,row):
                row.update(status="undone",reason="")
                return
        except OSError:
            pass
        row.update(status="moved",reason="복원 중단 · 재시도 가능")


def pending(row):
    if row["status"] in ("moved","restoring"):
        return True
    # Older versions persisted 'planned' just before moving a file.
    return (row["status"]=="planned" and not os.path.lexists(row["src"])
            and os.path.lexists(row["dst"]))


def restore_reason(row):
    try:
        src, dst = Path(row["src"]), Path(row["dst"])
        if row.get("operation")=="rename":
            from entry_names import ensure_available
            ensure_available(dst,src,row["uid"])
            return ""
        validate_destination(row)
        check_directory(dst.parent)
        if os.path.lexists(src):
            raise OSError("원래 위치가 사용 중입니다.")
        if not os.path.lexists(dst):
            raise OSError("이동한 파일이 사라졌습니다.")
        if not matching(dst,row,row.get("dst_uid")):
            raise OSError("이동한 파일이 변경되었습니다.")
        return ""
    except (OSError,RuntimeError,ValueError) as error:
        return str(error)


def restore_row(log,rows,row):
    if row.get("operation")=="rename":
        from entry_names import apply
        try:
            apply(log,row,True)
        except (OSError,ValueError) as error:
            if row["status"]!="rename_returning":
                row["reason"]=str(error)
                save(log,rows)
            else:
                raise
        return
    reason = restore_reason(row)
    if reason:
        row.update(status="moved",reason=reason)
    else:
        src, dst = Path(row["src"]), Path(row["dst"])
        row.update(status="restoring",reason="")
        save(log,rows)
        try:
            src.parent.mkdir(parents=True,exist_ok=True)
            check_directory(src.parent)
            reason = restore_reason(row)
            if reason:
                raise OSError(reason)
            relocate(dst,src)
            row.update(status="undone",reason="")
        except (OSError,RuntimeError) as error:
            reconcile(row)
            row["reason"]=str(error)
    save(log,rows)


def finish_move(log,rows):
    for row in rows:
        reconcile(row)
        if row["status"]=="planned":
            row.update(status="skipped",reason="처리 전에 이동이 중단되었습니다.")
    for members in new_folder_rows(rows).values():
        moved = [r for r in members if r["status"]=="moved"]
        if 0 < len(moved) < MIN_UNIQUE:
            for row in reversed(moved):
                restore_row(log,rows,row)
                if row["status"]=="undone":
                    row["reason"]=minimum_reason(len(moved))+" · 원위치로 복원"
    remove_empty_group_dirs(rows)
    rows[0]["transaction"]="finished"
    save(log,rows)


def result_line(row, undoing=False):
    state = row["status"]
    if undoing or state=="undone":
        label = "복원 완료" if state=="undone" else "복원 보류"
        source,target = row["dst"],row["src"]
    else:
        label = "건너뜀"
        if state=="moved":
            label = "복원 확인 필요" if row.get("reason") else "이동 완료"
        source,target = row["src"],row["dst"]
    reason = " · "+row["reason"] if row.get("reason") else ""
    return f"{label}   {source} → {target}{reason}"


def read_history(path):
    rows=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows,list) or any(
            not isinstance(r,dict) or not all(isinstance(r.get(k),str) for k in ("status","src","dst","sha"))
            for r in rows):
        raise ValueError("이력 파일의 형식을 확인할 수 없습니다.")
    return rows


def recover_locked(directory):
    for path in directory.glob("*.json"):
        try:
            rows=read_history(path)
        except (OSError,ValueError):
            continue
        if rows and rows[0]["status"] in ("renaming","rename_returning"):
            from entry_names import recover
            recover(path,rows[0])
        elif rows and rows[0].get("transaction")=="moving":
            finish_move(path,rows)
        elif any(r["status"]=="restoring" for r in rows):
            for r in rows:
                reconcile(r)
            remove_empty_group_dirs(rows)
            save(path,rows)


def recover_interrupted():
    if (HOME/"History").is_dir():
        with history_lock() as directory:
            recover_locked(directory)


def batches():
    recover_interrupted()
    for path in sorted((HOME/"History").glob("*.json"),reverse=True):
        try:
            rows=read_history(path)
        except (OSError,ValueError):
            rows=None
        yield path,rows


def history_batch(batch_id):
    for path,rows in batches():
        if path.stem==batch_id:
            if rows is None:
                raise ValueError("선택한 이력 파일을 읽을 수 없습니다.")
            return path,rows
    raise ValueError("선택한 정리 기록을 찾을 수 없습니다.")


def latest():
    return next(((p,rows) for p,rows in batches() if rows and any(map(pending,rows))), (None,[]))


def recent_history() -> list[HistoryEvent]:
    result=[]
    for path,rows in batches():
        readable=rows is not None
        rows=rows or []
        try:
            stamp=datetime.strptime(path.stem[:15],"%Y%m%d-%H%M%S")
        except ValueError:
            stamp=datetime.fromtimestamp(path.stat().st_mtime)
        result.append(HistoryEvent(id=path.stem,time=stamp.strftime("%Y.%m.%d %H:%M:%S"),readable=readable,
                                   operation=rows[0].get("operation","move") if rows else "move",
                                   moved=sum(pending(r) or r["status"]=="undone" for r in rows),
                                   undone=sum(r["status"]=="undone" for r in rows),
                                   pending=sum(pending(r) for r in rows),
                                   files=[Path(r["src"]).name for r in rows[:8]]))
    return result


def undo(path, indices=None):
    with history_lock() as directory:
        recover_locked(directory)
        rows=read_history(path)
        report=[]
        for i in reversed(range(len(rows))):
            row=rows[i]
            if not pending(row) or indices is not None and i not in indices:
                continue
            restore_row(path,rows,row)
            report.append(result_line(row,undoing=True))
        remove_empty_group_dirs(rows)
        return report
