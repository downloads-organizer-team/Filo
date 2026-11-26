"""Report work within the current analysis stage without flooding the desktop IPC."""
from time import monotonic


class ScanProgress:
    def __init__(self, send):
        self.send = send

    def stage(self, label):
        self.label = label
        self.last_value = None
        self.last_sent = None
        self.send({"label": label, "percent": None})

    def update(self, done, total):
        if total == 0:
            return
        percent = None if total is None else min(100, done * 100 // total)
        value = done if percent is None else percent
        if value == self.last_value:
            return
        now = monotonic()
        if self.last_sent is not None and now - self.last_sent < 0.15 and percent != 100:
            return
        self.last_value, self.last_sent = value, now
        event = {"label": self.label, "percent": percent}
        if total is None:
            event["files"] = done
        self.send(event)


def tracked(items, progress):
    """Count an item only after the caller has finished processing it."""
    if progress is None:
        yield from items
        return
    total = len(items)
    progress(0, total)
    for done, item in enumerate(items, 1):
        yield item
        progress(done, total)
