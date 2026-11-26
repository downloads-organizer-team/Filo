# 기여 가이드

처음 참여한다면 [README의 소스 실행 안내](README.md#소스에서-실행)로 앱을 열어 보세요. 팀원과 작업 범위를 정할 때는 아래 표에서 변경할 기능과 관련 테스트를 먼저 찾으면 됩니다.

## 어디에서 작업하나요?

| 변경할 내용 | 먼저 볼 파일 | 확인할 동작 |
| --- | --- | --- |
| 파일명·용어·그룹 추천 | [features.py](organizer/analysis/features.py), [terms.json](organizer/analysis/terms.json), [similarity.py](organizer/analysis/similarity.py), [clustering.py](organizer/analysis/clustering.py) | 같은 과목 자료가 묶이고, 이름이 비슷한 다른 과목은 따로 남는지 |
| 문서 본문·과목명 추출 | [readers.py](organizer/analysis/readers.py), [refinement.py](organizer/analysis/refinement.py), [course_titles.py](organizer/analysis/course_titles.py) | 본문 분석 설정을 바꾸면 애매한 파일의 추천이 어떻게 달라지는지 |
| 화면·데스크톱 서비스 | [desktop/renderer.js](desktop/renderer.js), [desktop/main.cjs](desktop/main.cjs), [desktop_service.py](organizer/desktop_service.py) | 화면에서 누른 동작이 Python 서비스까지 전달되고 결과가 표시되는지 |
| 사용자 편집·파일 이동 | [feedback.py](organizer/files/feedback.py), [constraints.py](organizer/analysis/constraints.py), [storage.py](organizer/files/storage.py) | 수정한 소속이 재분석 후 유지되는지, 이동·복원 때 동명 파일을 보호하는지 |
| 브라우저 출처 | [browser_extension/](browser_extension/), [browser_bridge.py](organizer/browser/browser_bridge.py), [capture_host.py](organizer/browser/capture_host.py), [course_source.py](organizer/analysis/course_source.py) | 다운로드한 파일에 해당 페이지의 제목·경로가 붙는지 |

전체 처리 순서와 신뢰도 기준은 [분석 설계](docs/analysis.md)에서 볼 수 있습니다.

README의 소스 실행 명령으로 여는 화면은 `desktop/`에 있습니다. 루트의 `app.pyw`는 `start.cmd`와 같은 Electron 화면을 엽니다. 이전 Tkinter 검토 화면은 `python app.pyw --legacy`로 실행할 수 있습니다. Electron 화면의 버튼 문구는 [desktop/renderer.js](desktop/renderer.js), 기본 배치와 스타일은 [desktop/index.html](desktop/index.html)과 [desktop/style.css](desktop/style.css)에서 찾을 수 있습니다.

## 이슈에서 작업 나누기

1. [열린 이슈](https://github.com/downloads-organizer-team/downloads-organizer/issues)에서 같은 작업을 찾고, 맡을 항목에 담당자나 댓글을 남겨 중복 작업을 줄입니다.
2. 버그라면 **재현 순서, 기대 결과, 실제 결과**를 적습니다. 분류 오류는 예제 파일명과 분석 설정을 함께 적으면 따라 해 보기 쉽습니다. 예를 들어 “본문 분석을 켰을 때 `첨부.pdf`가 어느 그룹에 들어가는가?”처럼 결과를 비교할 수 있게 씁니다.
3. 기능 제안이라면 **어느 화면에서 누가 무엇을 할 수 있어야 하는지** 적습니다. 화면과 분석 엔진을 나눠 맡는다면 두 작업이 주고받을 값과 함께 확인할 예제를 이슈에 남깁니다.

## 브랜치에서 변경하기

원본 저장소에 쓰기 권한이 있는 팀원은 저장소 루트에서 다음과 같이 시작할 수 있습니다. 아래는 첫 실행 안내를 고치는 작업의 예입니다.

```powershell
git switch main
git pull --ff-only origin main
git switch -c docs/first-run-guide
```

변경한 파일을 살펴보고 작업 브랜치에 커밋합니다.

```powershell
git diff
git add README.md
git commit -m "첫 실행 안내에 배포 ZIP 파일명 추가"
git push -u origin docs/first-run-guide
```

포크에서 작업한다면 원본 `main`과 포크를 동기화한 뒤 작업 브랜치를 자신의 포크에 푸시합니다. 두 방식 모두 PR의 대상은 **`downloads-organizer-team/downloads-organizer`의 `main`**입니다.

## 변경 확인하기

저장소 루트에서 아래 명령으로 전체 테스트를 실행합니다. 두 테스트 모듈은 [demo.zip](demo.zip)을 임시 폴더에 풀고 임시 데이터베이스를 사용합니다. 배포 ZIP에 포함된 Python을 쓸 때는 `python` 자리에 `.\python\python.exe`를 입력합니다.

```powershell
python -B -m unittest -v
```

| 변경 범위 | 집중해서 확인하는 방법 |
| --- | --- |
| 분류 규칙·문서 판독 | `python -B -m unittest -v tests.test_pipeline`을 실행합니다. 예제에서 함께 묶여야 할 파일과 미분류에 남아야 할 파일을 하나씩 비교합니다. |
| 특정 폴더에 치우치는 분류 | `python -B -X utf8 -m tests.test_generalization --measure`로 합성 파일의 잘못 묶인 쌍, 놓친 쌍, 예상 이름과 일치한 묶음 수를 확인합니다. `python -B -m unittest tests.test_generalization`은 파일명·단어 순서·배치가 다른 경우도 검사합니다. |
| 편집·미리보기·이동 | `python -B -m unittest -v tests.test_desktop`을 실행합니다. 이동을 건너뛴 파일과 되돌린 파일의 경로를 확인하는 사례는 `test_pipeline`에도 있습니다. |
| 복수 폴더·목적지·검토 데이터 | `python -B -m unittest -v tests.test_sources`로 경로 중복, 충돌, 새 폴더·기존 폴더 이동과 복원, 제한된 관계 보기와 실제 정리 이력을 확인합니다. |
| 범용 관계·검색 | `python -B -m unittest -v tests.test_relationships tests.test_search`를 실행합니다. Windows에서 `python -B -X utf8 -m tests.test_search --sdk`를 실행하면 임시 폴더를 대상으로 내장 검색 엔진을 확인합니다. |
| Electron 화면·브라우저 확장 | Windows에서 바꾼 화면이나 연결 과정을 직접 따라갑니다. 파일 이동을 확인할 때는 예제 파일의 복사본으로 한 그룹만 옮기고 **최근 이동 되돌리기**까지 확인합니다. |
| 문서 | GitHub 미리보기에서 표와 코드 블록을 읽고, 바꾼 링크와 실행 절차를 따라갑니다. |

## Windows 설치 파일 빌드

Windows x64에서 Python 3.13, Inno Setup 6, [Electron rcedit](https://github.com/electron/rcedit/releases/tag/v2.0.0)을 준비합니다. [Electron 45.3.3](https://github.com/electron/electron/releases/tag/v45.3.3)과 [Python 3.13.14](https://www.python.org/downloads/release/python-31314/)의 Windows x64 ZIP을 내려받고 저장소 루트에서 실행합니다.

```powershell
python packaging/build_windows.py --electron electron-v45.3.3-win32-x64.zip --python-embed python-3.13.14-embed-amd64.zip --iscc "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" --rcedit .\rcedit-x64.exe --output dist
```

빌드 스크립트는 두 ZIP의 SHA-256을 확인합니다. 배포할 새 모듈과 리소스는 먼저 Git에 추가하세요. 설치 파일의 버전은 `desktop/package.json`에서 읽습니다.

## 풀 리퀘스트와 리뷰

[풀 리퀘스트](https://github.com/downloads-organizer-team/downloads-organizer/pulls)를 열 때는 제목에 사용자가 보게 될 변화를 쓰고, 본문에 아래 내용을 담아 주세요.

| 항목 | 적을 내용 |
| --- | --- |
| 목적 | 해결할 문제와 관련 이슈 번호. 병합과 함께 이슈를 닫으려면 `Closes #번호`를 사용합니다. |
| 변경 전후 | 같은 입력에서 무엇이 달라졌는지 파일명이나 화면으로 보여 줍니다. |
| 검증 | 실행한 명령과 결과, 직접 확인한 화면이나 브라우저를 적습니다. 화면 캡처에는 예제 파일명을 사용합니다. |
| 리뷰 요청 | 팀원이 집중해서 볼 부분을 짚어 줍니다. 예를 들어 “동명 파일을 건너뛴 뒤 복원할 때도 원본이 유지되는지 봐 주세요.”처럼 적습니다. |

리뷰어는 PR에 적힌 예제를 따라 해 보고, 결과가 다르면 사용한 설정과 관찰한 동작을 댓글에 남깁니다. 작성자는 수정한 커밋과 다시 확인한 결과를 같은 대화에 남기면 다음 리뷰어가 이어서 확인할 수 있습니다.
