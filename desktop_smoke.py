"""Opt-in Windows UI check. Run with Python Playwright and an Electron executable."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep


def verify(executable):
    from playwright.sync_api import sync_playwright, expect

    with TemporaryDirectory(prefix="organizer-ui-") as temporary:
        base=Path(temporary)
        downloads,extra,state,profile=(base/k for k in ("Downloads","Projects","State","Profile"))
        for path in (downloads,extra,state):
            path.mkdir()
        for name in ("여름 프로젝트 1주차 보고서.txt","여름 프로젝트 2주차 보고서.txt","여름 프로젝트 3주차 보고서.txt","무제.txt"):
            (extra/name).write_text("sample",encoding="utf-8")
        (downloads/"제외한 위치.txt").touch()
        (extra/"보관").mkdir()
        (extra/"보관"/"옛 문서.txt").touch()
        (state/"download-settings.json").write_text(json.dumps({"roots":[str(downloads),str(extra)]}),encoding="utf-8")
        env=dict(os.environ,MOA_HOME=str(state),MOA_DOWNLOADS=str(downloads),
                 MOA_EVERYTHING_DLL=str(base/"missing.dll"))
        env.pop("ELECTRON_RUN_AS_NODE",None)
        process=subprocess.Popen([executable,"--remote-debugging-port=0","--remote-debugging-address=127.0.0.1",
                                  "--user-data-dir="+str(profile),str(Path(__file__).resolve().parent/"desktop")],
                                 env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            deadline=monotonic()+20
            port_file=profile/"DevToolsActivePort"
            while not port_file.exists() and process.poll() is None and monotonic()<deadline:
                sleep(.1)
            port=port_file.read_text().splitlines()[0]
            with sync_playwright() as playwright:
                browser=playwright.chromium.connect_over_cdp("http://127.0.0.1:"+port)
                context=browser.contexts[0]
                page=context.pages[0] if context.pages else context.wait_for_event("page")
                page.wait_for_selector("#external-query")
                errors=[]
                page.on("pageerror",lambda error:errors.append(str(error)))
                expect(page.locator("#external-query")).to_be_focused()
                assert not (state/"feedback.sqlite3").exists()
                search=page.locator("#external-query")
                search.fill("explorer")
                search.fill("explorer.exe")
                expect(page.locator("#search-rows")).to_contain_text("explorer.exe",timeout=15000,ignore_case=True)
                expect(page.locator("#search-rows img").first).to_be_visible()
                # Keep the Windows user's clipboard intact while checking which path is copied.
                copy=page.locator("[data-copy-path]").first
                path=copy.get_attribute("data-copy-path")
                assert page.evaluate("typeof navigator.clipboard.writeText")== "function"
                page.evaluate("navigator.clipboard.writeText=async text=>{window.copiedPath=text}")
                copy.press("Enter")
                expect(page.locator("#toast")).to_contain_text("경로를 복사")
                assert page.evaluate("window.copiedPath")==path
                search.fill("")
                expect(page.locator("#search-rows tr")).to_have_count(0)
                page.get_by_role("button",name="파일 정리하기").click()
                dialog=page.get_by_role("dialog")
                slider=dialog.get_by_role("slider")
                descriptions=set()
                for i in range(11):
                    slider.press("Home" if i==0 else "ArrowRight")
                    descriptions.add(dialog.locator("#min-description").inner_text())
                assert len(descriptions)==11
                for _ in range(3):slider.press("ArrowLeft")
                dialog.locator('[value="new"]').check()
                dialog.get_by_role("button",name="분석 시작").click()
                expect(page.locator("#root-path summary")).to_contain_text("외 1개")
                page.locator("#root-path summary").click()
                expect(page.locator("#root-path li")).to_have_text([str(downloads),str(extra)])
                page.get_by_role("button",name="위치 · 기준 변경").click()
                dialog.locator("[data-remove-root]").first.click()
                expect(dialog.locator("#source-roots")).not_to_contain_text(str(downloads))
                dialog.get_by_role("button",name="분석 시작").click()
                expect(page.locator("#root-path summary")).to_contain_text(str(extra))
                expect(page.locator("#file-rows tr")).to_have_count(4)
                page.locator("#organize").click()
                expect(dialog.locator(".move-row")).to_have_count(3)
                dialog.get_by_role("button",name="취소",exact=True).click()
                filter_box=page.get_by_role("searchbox",name="현재 목록에서 파일명 필터")
                filter_box.fill("무제")
                expect(page.locator("#organize")).to_be_disabled()
                filter_box.fill("2주차")
                expect(page.locator("#review-count")).to_have_text("필터 결과 · 이동 대상 1개")
                page.locator("#organize").click()
                expect(dialog.locator(".move-row")).to_have_count(1)
                expect(dialog.locator(".move-row")).to_contain_text("2주차")
                dialog.get_by_role("button",name="취소",exact=True).click()
                filter_box.fill("")
                page.get_by_role("checkbox",name="여름 프로젝트 1주차 보고서.txt 선택").check()
                expect(page.locator("#review-count")).to_have_text("체크한 파일 · 이동 대상 1개")
                page.locator("#organize").click()
                expect(dialog.locator(".move-row")).to_have_count(1)
                expect(dialog.locator(".move-row")).to_contain_text("1주차")
                dialog.get_by_role("button",name="1개 파일 이동",exact=True).click()
                expect(dialog.get_by_role("heading",name="파일 처리 결과")).to_be_visible()
                assert (extra/"여름 프로젝트"/"여름 프로젝트 1주차 보고서.txt").exists()
                assert len(list(extra.glob("*.txt")))==3
                dialog.get_by_role("button",name="닫기",exact=True).last.click()
                page.get_by_role("button",name="파일 검색",exact=True).last.click()
                page.get_by_role("button",name="이동 되돌리기",exact=True).click()
                dialog.get_by_role("button",name="1개 파일 복원",exact=True).click()
                expect(dialog.get_by_role("heading",name="파일 처리 결과")).to_be_visible()
                assert len(list(extra.glob("*.txt")))==4
                assert (extra/"보관"/"옛 문서.txt").exists()
                assert not errors,errors
                print("PASS: live search, path copy action, 11 thresholds, roots, filtered and checked previews, move and undo")
                page.close()
        finally:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=8)


if __name__=="__main__":
    verify(sys.argv[1])
