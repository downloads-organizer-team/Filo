"""Read a single native-messaging request from the LMS extension."""
from datetime import datetime
import json
import re
from pathlib import Path
import stat
import struct
import sys
from urllib.parse import urlsplit

from organizer.files import feedback
from organizer.models import DownloadContext
from organizer.analysis.readers import usable_title
from organizer.files.scanner import file_uid
from organizer.files import storage

ORIGIN="https://clc.chosun.ac.kr"

def capture(message):
    if message.get("type")=="ping":return {"ok":True}
    origin=message.get("pageOrigin","")
    parts=urlsplit(origin)
    if (not parts.hostname or parts.scheme!="https" or parts.username is not None
            or origin!="https://"+parts.netloc or not re.fullmatch(r"[A-Za-z0-9.\-:\[\]]+",parts.netloc)):
        return {"skip":True}
    if message.get("type")=="enable-site":
        with feedback.connection() as db:
            db.execute("INSERT OR IGNORE INTO lms_sites VALUES(?)",(origin,))
        return {"ok":True}
    if message.get("type")!="download":
        return {"skip":True}
    if origin!=ORIGIN:
        with feedback.connection() as db:
            if not db.execute("SELECT 1 FROM lms_sites WHERE origin=?",(origin,)).fetchone():return {"skip":True}
    path=Path(message["path"])
    root=storage.downloads_folder().resolve()
    if not path.is_absolute() or not path.is_relative_to(root) or path==root:
        return {"skip":True}
    if path.resolve()!=path or ":" in str(path.relative_to(root)):
        return {"skip":True}
    try:
        st=path.stat()
    except FileNotFoundError:
        return {"skip":True}
    completed=datetime.fromisoformat(message["endTime"])
    if (completed.tzinfo is None or not stat.S_ISREG(st.st_mode)
            or (message["size"]>=0 and st.st_size!=message["size"])
            or getattr(st,"st_birthtime",0)>completed.timestamp()+2):
        return {"skip":True}
    page_title=" ".join(message.get("pageTitle","").split())[:300]
    course=" ".join(message.get("courseName","").split())
    if not usable_title(course):course=""
    source_page=""
    source_url=message.get("pageUrl","")
    if isinstance(source_url,str) and len(source_url)<=4096:
        try:
            source=urlsplit(source_url)
            if (source.scheme=="https" and source.hostname and source.username is None
                    and source.password is None and source.netloc.casefold()==parts.netloc.casefold()):
                # Keep the page location, but not query parameters or fragments that may contain tokens.
                source_page=f"https://{source.netloc}{source.path[:2048]}"
        except ValueError:
            pass
    course_id=message.get("courseId","")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}",course_id):course_id=""
    if not (course or page_title or course_id or source_page):return {"skip":True}
    # Preserve a recognized course identifier separately from the generic source page.
    page=origin+"/?course_id="+course_id if course_id else origin
    info=DownloadContext(page_title=page_title,downloaded_at=completed.isoformat(),course_name=course,
                         course_page=page,source_page=source_page)
    feedback.record_download(file_uid(path,st),info)
    return {"ok":True}

def main():
    header=sys.stdin.buffer.read(4)
    if len(header)!=4:return
    size=struct.unpack("<I",header)[0]
    if size>65536:return
    try:
        request=json.loads(sys.stdin.buffer.read(size))
        answer=capture(request)
    except (KeyError,TypeError,ValueError,AttributeError):
        answer={"skip":True}
    except (OSError,feedback.sqlite3.Error):
        answer={"retry":True}
    payload=json.dumps(answer).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I",len(payload))+payload)
    sys.stdout.buffer.flush()

if __name__=="__main__":main()
