"""Rename a selected Windows entry and keep pending restore paths usable."""
from datetime import datetime
import json
import ntpath
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from scanner import check_directory, file_uid
import storage


def identity(path):
    check_directory(path.parent)
    info=path.lstat()
    if (not path.name or stat.S_ISLNK(info.st_mode)
            or getattr(info,"st_file_attributes",0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))):
        raise ValueError("일반 파일이나 폴더를 선택하세요.")
    return file_uid(path,info),stat.S_ISDIR(info.st_mode)


def checked_name(value):
    if (not isinstance(value,str) or not value.strip() or value.endswith(("."," "))
            or re.search(r'[<>:"/\\|?*\x00-\x1f]',value)
            or len(value.encode("utf-16-le"))>510 or ntpath.isreserved(value)):
        raise ValueError("Windows에서 사용할 수 있는 파일 또는 폴더 이름을 입력하세요.")
    return value


def redirected(value,old,new):
    path=Path(value)
    return str(new/path.relative_to(old)) if path.is_relative_to(old) else value


def update_references(log,record,old,new):
    directory=record["is_folder"]
    for path in log.parent.glob("*.json"):
        if path==log:continue
        try:
            rows=storage.read_history(path)
        except (OSError,ValueError):
            continue
        changed=False
        for row in rows:
            if row["status"] not in ("moved","planned"):continue
            # Keep the historical names for the detail view. Only pending paths follow the entry.
            if directory:
                fields=("src","dst","group_root")
            elif row.get("operation")!="rename" and Path(row["dst"])==old:
                if row.get("dst_uid") and row["dst_uid"]!=record["uid"]:continue
                fields=("dst",)
            else:
                continue
            for key in fields:
                if key not in row or row.get("operation")=="rename" and Path(row[key])==old:continue
                updated=redirected(row[key],old,new)
                if updated!=row[key]:
                    row.setdefault("recorded_"+key,row[key])
                    row[key]=updated
                    changed=True
            if directory and "source_roots" in row:
                roots=[redirected(p,old,new) for p in row["source_roots"]]
                if roots!=row["source_roots"]:
                    row["source_roots"]=roots
                    changed=True
        if changed:storage.save(path,rows)
    settings=storage.HOME/"download-settings.json"
    if directory and settings.is_file():
        try:
            options=json.loads(settings.read_text(encoding="utf-8"))
        except ValueError:
            return
        roots=options.get("roots") if isinstance(options,dict) else None
        if not isinstance(roots,list) or not all(isinstance(p,str) for p in roots):return
        updated=[redirected(p,old,new) for p in roots]
        if updated!=roots:
            options["roots"]=updated
            storage.save(settings,options)


def ensure_available(old,new,uid):
    if identity(old)[0]!=uid:
        raise OSError("선택한 항목이 바뀌었습니다. 다시 선택하세요.")
    if old!=new and os.path.lexists(new):
        raise FileExistsError("같은 이름의 항목이 있습니다.")


def recover(log,row):
    undoing=row["status"]=="rename_returning"
    old,new=Path(row["src"]),Path(row["dst"])
    if undoing:old,new=new,old
    try:
        arrived=identity(new)[0]==row["uid"] and (old!=new or new.name in os.listdir(new.parent))
    except (OSError,ValueError):
        arrived=False
    if arrived:
        update_references(log,row,old,new)
        row.update(status="undone" if undoing else "moved",reason="")
    else:
        row.update(status="moved" if undoing else "skipped",reason="이름 변경을 완료하지 못했습니다.")
    storage.save(log,[row])


def apply(log,row,undoing):
    old,new=Path(row["src"]),Path(row["dst"])
    if undoing:old,new=new,old
    ensure_available(old,new,row["uid"])
    row["status"]="rename_returning" if undoing else "renaming"
    storage.save(log,[row])
    try:
        # On Windows rename fails if another entry takes the target name.
        os.rename(old,new)
    except OSError as error:
        row.update(status="moved" if undoing else "skipped",reason=str(error))
        storage.save(log,[row])
        raise
    recover(log,row)


def rename(path,title,uid):
    new=path.with_name(checked_name(title))
    if storage.HOME.is_relative_to(path) or path.is_relative_to(storage.HOME/"History"):
        raise ValueError("현재 앱에서 사용하는 이력 경로입니다.")
    with storage.history_lock() as directory:
        storage.recover_locked(directory)
        current,is_folder=identity(path)
        if current!=uid:raise ValueError("항목이 바뀌었습니다. 다시 선택하세요.")
        if str(new)!=str(path):
            log=directory/(datetime.now().strftime("%Y%m%d-%H%M%S-%f")+"-"+uuid4().hex[:6]+".json")
            row=dict(operation="rename",src=str(path),dst=str(new),uid=uid,is_folder=is_folder,sha="")
            apply(log,row,False)
    return new
