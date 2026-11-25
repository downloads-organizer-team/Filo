"""Content identity and the minimum size of a proposed new folder."""
from collections import Counter
import hashlib
import re
import stat

from scanner import file_uid


MIN_UNIQUE = 3


def minimum_reason(count):
    return f"새 폴더에는 고유 파일 {MIN_UNIQUE}개가 필요합니다. 현재 이동 가능 {count}개"


def check_source(file):
    info = file.path.lstat()
    if (not stat.S_ISREG(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or file_uid(file.path, info) != file.uid
            or (info.st_size, info.st_mtime_ns) != (file.size, file.mtime_ns)):
        raise OSError("분석 후 파일이 바뀌었습니다.")


def checksum(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def identify_files(files, stop):
    sizes = Counter(f.size for f in files)
    representatives = {}
    # Prefer the unnumbered original, then the path, independently of scan order.
    def order(f):
        return (bool(re.search(r"\s*\(\d+\)$", f.path.stem)), str(f.path).casefold(), str(f.path))

    for f in sorted(files, key=order):
        stop()
        try:
            check_source(f)
            if f.offline:
                raise OSError("오프라인 파일")
            if sizes[f.size] == 1:
                with f.path.open("rb") as stream:
                    stream.read(1)
                continue
            f.digest = checksum(f.path)
            check_source(f)
            rep = representatives.setdefault((f.size, f.digest), f)
            if rep is not f:
                f.hold_reason = "동일 내용의 사본 · 대표 파일 " + str(rep.path)
        except OSError as error:
            f.hold_reason = "내용 확인 보류 · " + str(error)


def eligible_groups(study, plan):
    reasons = {item.file: item.skip for item in plan}
    kept = []
    for group in study.groups:
        if group.destination or any(not reasons[f] for f in group.members):
            kept.append(group)
            continue
        for f in group.members:
            f.group = None
            f.state = "미분류"
            f.note = reasons[f]
    study.groups = kept
