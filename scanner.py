import os
from pathlib import Path
import stat
from models import File

def file_uid(path,st):
    birth=getattr(st,"st_birthtime_ns",0)
    return f"{st.st_dev:x}:{st.st_ino:x}:{birth:x}" if st.st_ino else os.path.normcase(str(path))


def scan(study, recursive, stop):
    pending = [study.root]
    while pending:
        folder = pending.pop()
        stop()
        try:
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
                            if len(study.files) >= 3000:
                                raise ValueError("한 번에 분석할 수 있는 파일은 3,000개입니다."
                                                 + (" ‘하위 폴더 포함’을 끄고 다시 분석할 수 있습니다." if recursive else ""))
                            path = Path(entry.path)
                            if os.name=="nt" and not st.st_ino:st=path.stat()
                            uid = file_uid(path,st)
                            study.files.append(File(path, uid, str(path.parent.relative_to(study.root)), st.st_size,
                                getattr(st, "st_birthtime", st.st_ctime), st.st_mtime, st.st_mtime_ns,
                                bool(attrs & stat.FILE_ATTRIBUTE_OFFLINE)))
                    except OSError:
                        study.skipped += 1
        except OSError:
            if folder == study.root: raise
            study.skipped += 1
    study.files.sort(key=lambda f: str(f.path).casefold())
    for i, f in enumerate(study.files): f.index = i
