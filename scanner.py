import os
from pathlib import Path
import stat
from models import File

def file_uid(path,st):
    birth=getattr(st,"st_birthtime_ns",0)
    return f"{st.st_dev:x}:{st.st_ino:x}:{birth:x}" if st.st_ino else os.path.normcase(str(path))

def check_directory(path):
    path=Path(path)
    if not path.is_absolute() or path.resolve()!=path:raise OSError("절대 폴더 경로를 확인하세요.")
    for part in (path,*path.parents):
        info=part.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or getattr(info,"st_file_attributes",0)&stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise OSError("폴더 또는 연결 경로를 확인하세요.")
    return path


def scan(study, recursive, stop):
    roots = study.roots or [study.root]
    for root in roots:check_directory(root)
    pending = list(reversed(roots))
    visited = set()
    seen = set()
    while pending:
        folder = pending.pop()
        stop()
        key = os.path.normcase(str(folder))
        if key in visited:continue
        visited.add(key)
        try:
            check_directory(folder)
            with os.scandir(folder) as it:
                for entry in it:
                    stop()
                    try:
                        st = entry.stat(follow_symlinks=False)
                        attrs = getattr(st, "st_file_attributes", 0)
                        if entry.is_symlink() or attrs & (stat.FILE_ATTRIBUTE_REPARSE_POINT | stat.FILE_ATTRIBUTE_SYSTEM):
                            study.skipped += 1
                        elif entry.is_dir(follow_symlinks=False):
                            if recursive: pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False) and not entry.name.startswith("~$") and entry.name.lower() != "desktop.ini":
                            path = Path(entry.path)
                            if os.name=="nt" and not st.st_ino:st=path.stat()
                            uid = file_uid(path,st)
                            if uid in seen:continue
                            if len(study.files) >= 3000:
                                raise ValueError("한 번에 분석할 수 있는 파일은 3,000개입니다."
                                                 + (" ‘하위 폴더 포함’을 끄고 다시 분석할 수 있습니다." if recursive else ""))
                            seen.add(uid)
                            rel = str(path.parent.relative_to(roots[0])) if len(roots)==1 else str(path.parent)
                            study.files.append(File(path, uid, rel, st.st_size,
                                getattr(st, "st_birthtime", st.st_ctime), st.st_mtime, st.st_mtime_ns,
                                bool(attrs & stat.FILE_ATTRIBUTE_OFFLINE)))
                    except OSError:
                        study.skipped += 1
        except InterruptedError:
            raise
        except OSError:
            if folder in roots: raise
            study.skipped += 1
    study.files.sort(key=lambda f: str(f.path).casefold())
    for i, f in enumerate(study.files): f.index = i
