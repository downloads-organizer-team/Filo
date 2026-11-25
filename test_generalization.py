"""Synthetic inboxes with fixed labels, independent of any user's Downloads folder.

Run python -B -X utf8 test_generalization.py --measure to print pair and title counts.
"""
from itertools import combinations
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sys
import unittest

from desktop_service import Desktop
import storage


# None means that even two files sharing this label should stay unclassified.
DESIGN = {
    "북쪽 광장 프로젝트": ("북쪽 광장 프로젝트_예산.xlsx", "북쪽 광장 프로젝트_안내도.pdf","북쪽 광장 프로젝트_일정.txt"),
    "남쪽 광장 프로젝트": ("남쪽 광장 프로젝트_예산.xlsx", "남쪽 광장 프로젝트_안내도.pdf","남쪽 광장 프로젝트_일정.txt"),
    "RQ-53108": ("RQ-53108_견적.pdf", "발주서_RQ-53108.xlsx","RQ-53108_내역.csv"),
    "RQ-72914": ("RQ-72914_견적.pdf", "발주서_RQ-72914.xlsx","RQ-72914_내역.csv"),
    "필름산책": ("필름산책_콘티.pdf", "필름산책_촬영표.xlsx","필름산책_대본.txt"),
    "소리의 물리": ("소리의 물리 1주차 강의.pdf", "소리의 물리 2주차 실습.pptx","소리의 물리 3주차 강의.docx"),
    None: ("[INTERNAL] 통근 버스 노선.pdf", "[INTERNAL] 의자 구매 요청.xlsx",
           "Untitled (2).png", "90213.zip", "고양이 사진.jpg"),
}

# Different names, languages, word positions, departments, and unrelated tags.
VALIDATION = {
    "Project Copper Orchard": ("Project Copper Orchard - Budget.xlsx", "Drawings (Project Copper Orchard).pdf","Project Copper Orchard - Site.dwg"),
    "Project Glass Orchard": ("Project Glass Orchard - Budget.xlsx", "Drawings (Project Glass Orchard).pdf","Project Glass Orchard - Site.dwg"),
    "MX-80461": ("검수증 [MX-80461].pdf", "mx80461_수령 확인.xlsx","MX-80461_송장.csv"),
    "MX-19625": ("검수증 [MX-19625].pdf", "mx19625_수령 확인.xlsx","MX-19625_송장.csv"),
    "모래시계": ("모래시계 - 자막.srt", "모래시계 - 원화.psd","모래시계 - 배경.png"),
    "도시와 빛": ("도시와 빛 1주차.pdf", "도시와 빛 2주차.pptx","도시와 빛 3주차 실습.docx"),
    None: ("[SHARED] 오븐 설명서.pdf", "[SHARED] 조카 운동회.png",
           "무제 (3).png", "72104.zip", "당근케이크 재료.txt"),
}


DOCUMENTS = {
    "별의 정원": ("별의 정원_원화.psd","별의 정원_타이포.ai","별의 정원_콘티.pdf"),
    "Laurel Bay": ("Laurel Bay - permit.pdf","Laurel Bay - route.gpx","Laurel Bay - schedule.csv"),
    "오솔숲": ("영수증_오솔숲.pdf","오솔숲_invoice.xlsx","오솔숲_시안.png"),
    None: ("invoice_도자기.pdf","invoice_치과.xlsx","영수증_연극.pdf","영수증_택시.jpg",
           "Receipt (1).pdf","Receipt (2).png","[NOTICE] 오븐 사용법.pdf","[NOTICE] 세탁 일정.xlsx",
           "memo.txt","notes.docx"),
}


def pairs(groups):
    return {frozenset(pair) for members in groups for pair in combinations(members, 2)}


def generated_inbox(seed):
    """Vary identifiers, title spelling, cohort sizes, separators and insertion order."""
    rng=Random(seed)
    places=rng.sample(["Delta","Raven","Quill","Larch","Coral","Pine","Drift","Birch"],4)
    locations=rng.choice(["Park","Hill","Field","Point"])
    jobs={}
    for place in places:
        name=f"{place} {locations}"
        jobs["Project "+name]=[f"Project {name} - Budget.xlsx",f"Drawings ({name} Project).pdf",
                               f"Brief [Project {name.upper()}].docx"]
    for serial in rng.sample(range(30000,99000),4):
        prefix=rng.choice(["ZT","VL","HK","GP"])
        code=f"{prefix}-{serial}"
        jobs[code]=[f"청구서_{code}.pdf",f"{prefix.lower()}{serial}_인수증.xlsx"]
        if rng.randrange(2):jobs[code].append(f"서명 ({code}).png")
    jobs[None]=["[DRAFTING] 병원 주소.txt","[DRAFTING] 캠핑 사진.jpg","Untitled (4).txt",
                "11351.pdf","94120.pdf"]
    shuffled=list(jobs.items())
    rng.shuffle(shuffled)
    return dict(shuffled)


def evaluate(labels, split=False):
    with TemporaryDirectory(prefix="organizer-eval-") as tmp:
        base=Path(tmp)
        roots=[base/"Inbox"]
        if split:roots.append(base/"Import")
        for root in roots:root.mkdir()
        names=[name for members in labels.values() for name in members]
        for i,name in enumerate(reversed(names) if split else names):
            (roots[i%len(roots)]/name).write_bytes(name.encode())
        if split:
            (roots[0]/"공용 자료").mkdir()
            (roots[0]/"공용 자료"/"이전 파일.pdf").touch()
            (roots[1]/"빈 스캔.png").touch()
        with patch.object(storage,"HOME",base/"State"), patch.object(storage,"downloads_folder",return_value=roots[0]):
            app=Desktop()
            app.scan(dict(roots=list(map(str,roots)),folderMode="new",minConfidence=.7,deep=split,covers=False))
        actual={frozenset(f.name for f in g.members):g.title for g in app.study.groups}
    expected={frozenset(members):title for title,members in labels.items() if title is not None and len(members)>=3}
    found,wanted=pairs(actual),pairs(expected)
    titles=sum(actual.get(members,"").casefold()==title.casefold() for members,title in expected.items())
    return dict(correct=len(found&wanted),false=len(found-wanted),missed=len(wanted-found),
                titles=titles,expected_titles=len(expected)),actual


class GeneralizationTests(unittest.TestCase):
    def test_inbox_membership_titles_and_layout(self):
        for labels in (DESIGN,VALIDATION,DOCUMENTS):
            for split in (False,True):
                with self.subTest(first=next(iter(labels)),split=split):
                    scores,actual=evaluate(labels,split)
                    self.assertEqual((scores["false"],scores["missed"],scores["titles"]),
                                     (0,0,scores["expected_titles"]),actual)

    def test_unseen_names_and_reordered_project_markers(self):
        for seed in (29,101,811):
            labels=generated_inbox(seed)
            for split in (False,True):
                with self.subTest(seed=seed,split=split):
                    scores,actual=evaluate(labels,split)
                    self.assertEqual((scores["false"],scores["missed"],scores["titles"]),
                                     (0,0,scores["expected_titles"]),actual)


if __name__=="__main__":
    if "--measure" in sys.argv:
        for name,labels in (("design",DESIGN),("validation",VALIDATION),("documents",DOCUMENTS)):
            for split in (False,True):
                print(name,"split" if split else "single",evaluate(labels,split)[0])
    else:
        unittest.main()
