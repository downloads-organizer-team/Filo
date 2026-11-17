from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile
from uuid import UUID, uuid4
from urllib.parse import quote
import ctypes
import hashlib
import json
import os
import re
import stat
from models import File

HOME=Path(os.environ.get("LOCALAPPDATA",str(Path.home())))/"MoaFileReview"

def downloads_folder():
    """Use the current user's Windows Downloads location, including redirections."""
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

def remember_options(recursive,deep,course_covers=True):
    try:
        HOME.mkdir(parents=True,exist_ok=True)
        save(HOME/"download-settings.json",dict(recursive=recursive,deep=deep,course_covers=course_covers))
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

def checksum(p):
    with open(p,"rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()

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


def folder_name(title):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")[:100].rstrip(" .") or "그룹"
    device = name.split(".", 1)[0].rstrip().upper()
    if re.fullmatch(r"CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[0-9¹²³]", device):
        name = "_" + name
    return name


def check_group_paths(root, source, target):
    if (target.parent.parent != root or not source.is_relative_to(root)
            or source.resolve() != source or target.parent.resolve() != target.parent):
        raise OSError("다운로드 안의 원래 경로를 확인할 수 없습니다.")
    if os.path.lexists(target.parent):
        info = target.parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError("그룹 폴더 위치에 파일 또는 연결 경로가 있습니다.")


def plan_group_folders(study, selected=None):
    plan = []
    names = set()
    reserved = set()
    for group in sorted(study.groups, key=lambda g: (g.title.casefold(), g.gid)):
        base = folder_name(group.title)
        name = base
        suffix = 2
        while name.casefold() in names:
            name = f"{base} ({suffix})"
            suffix += 1
        names.add(name.casefold())
        if selected is not None and group is not selected:
            continue
        for file in sorted(group.members, key=lambda f: str(f.path).casefold()):
            target = study.root / name / file.name
            skip = ""
            try:
                check_group_paths(study.root, file.path, target)
                if target == file.path:
                    skip = "이미 정리됨"
                elif os.path.lexists(target) or target in reserved:
                    skip = "같은 이름의 파일이 있습니다"
                else:
                    reserved.add(target)
            except (OSError, RuntimeError) as error:
                skip = str(error)
            plan.append(FolderMove(file, target, skip))
    return plan


def move(items,dest):
    return move_files((FolderMove(f,Path(dest)/f.name) for f in items))


def move_files(plan, group_root=None):
    history=HOME/"History";history.mkdir(parents=True,exist_ok=True)
    log=history/(datetime.now().strftime("%Y%m%d-%H%M%S-%f")+"-"+uuid4().hex[:6]+".json")
    rows=[];report=[];reserved=set()
    for item in plan:
        f,target=item.file,item.target
        if item.skip:
            report.append(f"건너뜀   {f.name}   ·   {item.skip}")
            continue
        try:
            if group_root is not None:check_group_paths(group_root,f.path,target)
            st=f.path.stat()
            if (st.st_size,st.st_mtime_ns)!=(f.size,f.mtime_ns):raise OSError("분석 후 파일 변경")
            if os.path.lexists(target) or target in reserved:raise OSError("같은 이름 또는 같은 위치")
            row=dict(src=str(f.path),dst=str(target),sha=checksum(f.path),status="planned")
            if group_root is not None:row["group_root"]=str(group_root)
            rows.append(row)
            reserved.add(target)
        except (OSError,RuntimeError) as ex:report.append("건너뜀   "+f.name+"   ·   "+str(ex))
    if not rows:return report
    save(log,rows)
    for r in rows:
        src=Path(r["src"]);dst=Path(r["dst"])
        try:
            if group_root is not None:
                check_group_paths(group_root,src,dst)
                try:
                    dst.parent.mkdir()
                except FileExistsError:
                    pass
                else:
                    info=dst.parent.stat()
                    r["created_dir"]=[info.st_dev,info.st_ino]
                    save(log,rows)
                check_group_paths(group_root,src,dst)
            relocate(src,dst);r["status"]="moved"
            report.append("이동 완료   "+str(dst.relative_to(group_root) if group_root else dst))
        except (OSError,RuntimeError) as ex:r["status"]="failed";report.append("건너뜀   "+src.name+"   ·   "+str(ex))
        save(log,rows)
    remove_empty_group_dirs(rows)
    return report


def remove_empty_group_dirs(rows):
    for row in rows:
        if not row.get("created_dir"):continue
        directory=Path(row["dst"]).parent
        try:
            info=directory.lstat()
            if (directory.parent==Path(row["group_root"]) and directory.resolve()==directory
                    and info.st_ino and row["created_dir"]==[info.st_dev,info.st_ino]):
                directory.rmdir()
        except (OSError,RuntimeError):
            pass  # A populated, replaced or unavailable folder must be retained.

def pending(row):
    return row["status"]=="moved" or (row["status"]=="planned" and not Path(row["src"]).exists() and Path(row["dst"]).is_file())

def latest():
    for p in sorted((HOME/"History").glob("*.json"),reverse=True):
        rows=json.loads(p.read_text(encoding="utf-8"))
        if any(map(pending,rows)):return p,rows
    return None,[]

def undo(path):
    rows=json.loads(path.read_text(encoding="utf-8"));report=[]
    for r in reversed(rows):
        if not pending(r):continue
        src,dst=Path(r["src"]),Path(r["dst"])
        try:
            if r.get("group_root"):check_group_paths(Path(r["group_root"]),src,dst)
            if src.exists():raise OSError("원래 위치가 사용 중입니다.")
            if not dst.is_file() or checksum(dst)!=r["sha"]:raise OSError("이동 후 파일이 바뀌었거나 사라졌습니다.")
            src.parent.mkdir(parents=True,exist_ok=True);relocate(dst,src);r["status"]="undone";report.append("복원 완료   "+src.name)
        except (OSError,RuntimeError) as ex:report.append("복원 보류   "+src.name+"   ·   "+str(ex))
        save(path,rows)
    remove_empty_group_dirs(rows)
    return report
