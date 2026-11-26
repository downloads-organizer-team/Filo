"""Opt-in Windows UI check. Run with Python Playwright and an Electron executable."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from contextlib import ExitStack

from test_search import isolated_instance


def verify(executable,everything):
    from playwright.sync_api import sync_playwright, expect

    with TemporaryDirectory(prefix="organizer-ui-") as temporary, ExitStack() as resources:
        base=Path(temporary)
        downloads,extra,state,profile=(base/k for k in ("Downloads","Projects","State","Profile"))
        for path in (downloads,extra,state):
            path.mkdir()
        for name in ("여름 프로젝트 1주차 보고서.txt","여름 프로젝트 2주차 보고서.txt","여름 프로젝트 3주차 보고서.txt","달빛정원_견적.xlsx","달빛정원_시안.png","달빛정원_일정.pdf","무제.txt"):
            (extra/name).write_text(name,encoding="utf-8")
        (downloads/"제외한 위치.txt").touch()
        (extra/"보관").mkdir()
        (extra/"보관"/"옛 문서.txt").touch()
        (state/"download-settings.json").write_text(json.dumps({"roots":[str(downloads),str(extra)]}),encoding="utf-8")
        inbox=base/"Search"
        inbox.mkdir()
        prefix="ui-check-"+base.name
        folder=inbox/(prefix+".folder")
        folder.mkdir()
        marker=inbox/"opened.marker"
        script=inbox/(prefix+".cmd")
        script.write_text('@echo off\necho opened>"%~dp0opened.marker"\n',encoding="ascii")
        for i in range(50):(inbox/f"{prefix}-{i:02}.txt").touch()
        env=dict(os.environ,MOA_HOME=str(state),MOA_DOWNLOADS=str(downloads),MOA_EVERYTHING_INSTANCE=base.name)
        env.pop("MOA_EVERYTHING_DLL",None)
        env.pop("ELECTRON_RUN_AS_NODE",None)
        def launch():
            return subprocess.Popen([executable,"--remote-debugging-port=0","--remote-debugging-address=127.0.0.1",
                                     "--user-data-dir="+str(profile),str(Path(__file__).resolve().parent/"desktop")],
                                    env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

        def connect(playwright,process):
            deadline=monotonic()+20
            port_file=profile/"DevToolsActivePort"
            while not port_file.exists() and process.poll() is None and monotonic()<deadline:
                sleep(.1)
            port=port_file.read_text().splitlines()[0]
            browser=playwright.chromium.connect_over_cdp("http://127.0.0.1:"+port)
            context=browser.contexts[0]
            return context.pages[0] if context.pages else context.wait_for_event("page")

        process=launch()
        try:
            with sync_playwright() as playwright:
                page=connect(playwright,process)
                page.wait_for_selector("#external-query")
                errors=[]
                page.on("pageerror",lambda error:errors.append(str(error)))
                expect(page.locator("#external-query")).to_be_focused()
                assert not (state/"feedback.sqlite3").exists()
                search=page.locator("#external-query")
                search.fill("discarded-query")
                search.fill(prefix)
                expect(page.locator("#search-meta")).to_contain_text("자동 재시도")
                expect(page.locator("#search-rows tr")).to_have_count(0)
                resources.enter_context(isolated_instance(everything,base,inbox,base.name))
                rows=page.locator("#search-rows tr")
                expect(rows).to_have_count(52,timeout=25000)
                expect(page.locator("#search-meta")).to_contain_text("Everything 1.5 SDK")
                expect(page.locator("#search-rows img").first).to_be_visible()
                directory=page.get_by_role("button",name=folder.name+" 폴더 열기",exact=True)
                expect(directory.locator(".result-folder")).to_be_visible()
                height=rows.first.bounding_box()["height"]
                viewport=page.locator(".search-list .table-scroll").bounding_box()["height"]
                assert height<=24 and viewport/height>=20,(height,viewport)
                print(f"Search row {height:g}px; {int((viewport-24)//height)} complete rows fit")
                # Observe the completed real Windows shell dispatch for a temporary directory.
                page.evaluate("""() => {
                    const invoke=call;
                    call=async (action,args)=>{
                        const result=await invoke(action,args);
                        if(action==="openSearchResult")window.openedResult=args.id;
                        return result;
                    };
                }""")
                await_id=directory.get_attribute("data-open-result")
                directory.locator(".entry-text").click()
                assert not page.evaluate("Boolean(window.openedResult)")
                directory.locator(".entry-text").dblclick()
                page.wait_for_function("id=>window.openedResult===id",arg=await_id)
                launch_file=page.get_by_role("button",name=script.name+" 파일 열기",exact=True)
                name_text=launch_file.locator(".entry-text")
                glyph=launch_file.locator("img,i").first
                glyph.dblclick()
                bounds=launch_file.bounding_box()
                launch_file.dblclick(position={"x":bounds["width"]-3,"y":8})
                assert not marker.exists()
                expect(launch_file).to_have_attribute("aria-pressed","false")
                name_text.click()
                expect(launch_file).to_have_attribute("aria-pressed","true")
                assert not marker.exists()
                name_text.dblclick()
                deadline=monotonic()+5
                while not marker.exists() and monotonic()<deadline:sleep(.05)
                assert marker.exists(),"The selected test file did not run"
                target=page.get_by_role("button",name=prefix+"-00.txt 파일 열기",exact=True)
                target.locator(".entry-text").click()
                page.wait_for_timeout(1100)
                target.locator(".entry-text").click()
                editor=page.get_by_role("textbox",name="새 이름")
                expect(editor).to_be_visible()
                renamed=prefix+"-00-updated.txt"
                editor.fill(renamed)
                editor.press("Enter")
                expect(page.get_by_role("button",name=renamed+" 파일 열기",exact=True)).to_be_visible()
                assert (inbox/renamed).is_file() and not (inbox/(prefix+"-00.txt")).exists()
                stale=await_id
                # Keep the Windows user's clipboard intact while checking which path is copied.
                copy=page.locator("[data-copy-path]").first
                path=copy.get_attribute("data-copy-path")
                assert page.evaluate("typeof navigator.clipboard.writeText")== "function"
                page.evaluate("navigator.clipboard.writeText=async text=>{window.copiedPath=text}")
                copy.press("Enter")
                expect(page.locator("#toast")).to_contain_text("경로를 복사")
                assert page.evaluate("window.copiedPath")==path
                resources.close()
                search.fill(prefix+"-00")
                expect(page.locator("#search-meta")).to_contain_text("자동 재시도",timeout=15000)
                resources.enter_context(isolated_instance(everything,base,inbox,base.name))
                expect(rows).to_have_count(1,timeout=20000)
                expect(rows.first).to_contain_text(renamed)
                search.fill("")
                expect(page.locator("#search-rows tr")).to_have_count(0)
                assert not page.evaluate("id=>window.desktop.call('openSearchResult',{id})",stale)["ok"]
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
                page.get_by_role("button",name="정리할 폴더 변경").click()
                dialog.locator("[data-remove-root]").first.click()
                expect(dialog.locator("#source-roots")).not_to_contain_text(str(downloads))
                dialog.get_by_role("button",name="분석 시작").click()
                expect(page.locator("#root-path summary")).to_contain_text(str(extra))
                groups=page.locator("#folder-tree details")
                expect(groups).to_have_count(3)
                expect(page.locator("#folder-tree details[open]")).to_have_count(0)
                summary=page.locator("#folder-tree summary").filter(has_text="달빛정원")
                folder_check=summary.get_by_role("checkbox")
                expect(folder_check).to_be_checked()
                folder_check.uncheck()
                expect(page.locator("#review-count")).to_have_text("폴더 1개 · 파일 3개 선택")
                expect(page.locator("#folder-tree details[open]")).to_have_count(0)
                folder_check.check()
                summary.locator("small").click()
                page.locator("#folder-tree summary").filter(has_text="여름 프로젝트").press("Enter")
                expect(page.locator("#folder-tree details[open]")).to_have_count(2)
                expect(page.get_by_role("heading",name="파일 정리",exact=True)).to_be_visible()
                expect(page.locator("#folder-tree .branch-file img.shell-icon").first).to_be_visible()
                row_height=page.locator("#folder-tree .branch-file").first.bounding_box()["height"]
                assert height<row_height<=height+7,(height,row_height)
                tree_file=page.get_by_role("button",name="여름 프로젝트 1주차 보고서.txt 파일 열기",exact=True)
                page.evaluate("""() => {
                    const invoke=call;
                    window.reviewOpens=[];
                    call=(action,args)=>{
                        if(action==="openReviewEntry"){window.reviewOpens.push(args);return Promise.resolve(true);}
                        return invoke(action,args);
                    };
                }""")
                tree_file.locator(".shell-icon").dblclick()
                width=tree_file.bounding_box()["width"]
                tree_file.dblclick(position={"x":width-2,"y":10})
                expect(tree_file).to_have_attribute("aria-pressed","false")
                assert not page.evaluate("window.reviewOpens.length")
                tree_file.locator(".entry-text").dblclick()
                assert page.evaluate("window.reviewOpens.length")==1
                tree_file.press("F2")
                editor=page.get_by_role("textbox",name="새 이름")
                tree_name="여름 프로젝트 1주차 수정 보고서.txt"
                editor.fill(tree_name)
                editor.press("Enter")
                expect(page.get_by_role("button",name=tree_name+" 파일 열기",exact=True)).to_be_visible()
                assert (extra/tree_name).is_file() and not (extra/"여름 프로젝트 1주차 보고서.txt").exists()
                summary=page.locator("#folder-tree summary").filter(has_text="달빛정원")
                summary.locator(".result-folder").dblclick()
                summary.locator("small").dblclick()
                expect(summary.locator("[data-entry]")).to_have_attribute("aria-pressed","false")
                expect(summary.locator("..")).to_have_attribute("open","")
                assert page.evaluate("window.reviewOpens.length")==1
                summary.press("F2")
                editor=page.get_by_role("textbox",name="새 이름")
                editor.fill("취소할 변경")
                editor.press("Escape")
                expect(summary).to_be_visible()
                label=page.locator('[data-entry="proposal"] .entry-text').filter(has_text="달빛정원")
                label.click()
                label.locator("..").press("F2")
                editor.fill("달빛정원 납품")
                editor.press("Enter")
                expect(page.locator("#folder-tree summary").filter(has_text="달빛정원 납품")).to_be_visible()
                expect(page.locator("#review-count")).to_have_text("폴더 2개 · 파일 6개 선택")
                page.locator("#organize").click()
                expect(dialog.locator(".move-row")).to_have_count(6)
                dialog.get_by_role("button",name="취소",exact=True).click()
                filter_box=page.get_by_role("searchbox",name="현재 목록에서 파일명 필터")
                filter_box.fill("무제")
                expect(page.locator("#organize")).to_be_disabled()
                filter_box.fill("2주차")
                expect(page.locator("#review-count")).to_have_text("폴더 1개 · 파일 1개 선택")
                page.locator("#organize").click()
                expect(dialog.locator(".move-row")).to_contain_text("고유 파일 3개")
                expect(dialog.get_by_role("button",name="1개 파일 이동")).to_have_count(0)
                dialog.get_by_role("button",name="취소",exact=True).click()
                filter_box.fill("여름 프로젝트")
                box=page.get_by_role("checkbox",name=tree_name+" 선택")
                box.uncheck()
                assert page.locator("[data-folder-check]").evaluate("(el)=>el.indeterminate")
                expect(page.locator("#move-selected")).to_be_disabled()
                expect(page.locator("#review-hint")).to_contain_text("2개 보류")
                box.check()
                expect(page.locator("#review-count")).to_have_text("폴더 1개 · 파일 3개 선택")
                for title in ("여름 프로젝트","달빛정원"):
                    filter_box.fill(title)
                    if title=="달빛정원":
                        page.get_by_role("button",name="파일 이동",exact=True).click()
                    else:
                        page.locator("#organize").click()
                        expect(dialog.locator(".move-row")).to_have_count(3)
                        dialog.get_by_role("button",name="3개 파일 이동",exact=True).click()
                    expect(dialog.get_by_role("heading",name="파일 처리 결과")).to_be_visible()
                    destination=extra/("달빛정원 납품" if title=="달빛정원" else title)
                    assert len(list(destination.iterdir()))==3
                    dialog.get_by_role("button",name="닫기",exact=True).last.click()
                assert not errors,errors
                page.close()
                process.wait(timeout=8)
                (profile/"DevToolsActivePort").unlink(missing_ok=True)
                process=launch()
                page=connect(playwright,process)
                dialog=page.get_by_role("dialog")
                page.get_by_role("button",name="최근 정리",exact=True).click()
                records=dialog.locator("[data-history]")
                expect(records).to_have_count(4)
                records.nth(1).click()
                expect(dialog.locator(".move-row")).to_have_count(3)
                dialog.get_by_role("button",name="이 작업 복원 미리보기").click()
                dialog.get_by_role("button",name="3개 파일 복원",exact=True).click()
                expect(dialog.get_by_role("heading",name="파일 처리 결과")).to_be_visible()
                assert not (extra/"여름 프로젝트").exists()
                assert len(list(extra.glob("여름 프로젝트*.txt")))==3
                assert len(list((extra/"달빛정원 납품").iterdir()))==3
                assert (extra/"보관"/"옛 문서.txt").exists()
                dialog.get_by_role("button",name="닫기",exact=True).last.click()
                existing=extra/"여름 프로젝트"
                existing.mkdir()
                page.get_by_role("button",name="파일 정리하기").click()
                dialog.locator('[value="reuse"]').check()
                dialog.get_by_role("button",name="분석 시작").click()
                single=page.get_by_role("searchbox",name="현재 목록에서 파일명 필터")
                single.fill("2주차")
                expect(page.locator("#folder-tree summary")).to_contain_text("기존 폴더")
                expect(page.locator("#review-count")).to_have_text("폴더 1개 · 파일 1개 선택")
                folder_button=page.locator('[data-entry="folder"]')
                folder_button.locator(".entry-text").click()
                folder_button.press("F2")
                editor=page.get_by_role("textbox",name="새 이름")
                editor.fill("여름 보관함")
                editor.press("Enter")
                expect(folder_button).to_have_text("여름 보관함")
                assert not existing.exists()
                existing=extra/"여름 보관함"
                assert existing.is_dir()
                page.locator("#organize").click()
                dialog.get_by_role("button",name="1개 파일 이동",exact=True).click()
                expect(dialog.get_by_role("heading",name="파일 처리 결과")).to_be_visible()
                assert len(list(existing.iterdir()))==1
                dialog.get_by_role("button",name="닫기",exact=True).last.click()
                page.get_by_role("button",name="이동 되돌리기",exact=True).click()
                dialog.get_by_role("button",name="1개 파일 복원",exact=True).click()
                expect(dialog.get_by_role("heading",name="파일 처리 결과")).to_be_visible()
                assert existing.is_dir() and not list(existing.iterdir())
                dialog.get_by_role("button",name="닫기",exact=True).last.click()
                page.get_by_role("button",name="정리할 폴더 변경").click()
                dialog.get_by_label("묶는 기준").select_option("extension")
                expect(dialog.locator("#min-confidence")).to_be_hidden()
                dialog.get_by_role("button",name="분석 시작").click()
                expect(page.locator("#folder-tree summary").filter(has_text="TXT")).to_have_count(1)
                page.locator("#folder-tree summary").filter(has_text="TXT").locator("small").click()
                expect(page.get_by_text("확장자 · TXT",exact=True)).to_be_visible()
                print("PASS: search, folder tree, minimum, two moves, restart, older-batch restore and single-file reuse")
                page.close()
        finally:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=8)


if __name__=="__main__":
    verify(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else str(Path(os.environ["ProgramFiles"])/"Everything"/"Everything.exe"))
