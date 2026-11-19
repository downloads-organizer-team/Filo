# 다운로드 파일 정리

강의 자료와 과제가 뒤섞인 Windows 다운로드 폴더에서 **같은 수업이나 작업에 속한 파일**을 찾아주는 데스크톱 앱입니다. PDF 강의안, PPTX 실습 자료, ZIP 제출물도 한 그룹으로 추천합니다. 추천 이유를 살펴보고 이동을 확정하면 다운로드 폴더 안에 그룹별 폴더가 생깁니다.

**[Windows x64 배포본 받기](https://github.com/seungan123/downloads-organizer/releases/tag/v1.0.0)** · [소스에서 실행](#소스에서-실행) · [팀 기여 가이드](CONTRIBUTING.md) · [이슈](https://github.com/seungan123/downloads-organizer/issues)

## 빠른 시작

1. 배포 페이지의 **Assets**에서 `downloads-organizer-windows-x64.zip`을 받아 폴더에 압축을 풉니다. 실행에 필요한 Electron과 Python이 들어 있습니다.
2. 압축을 푼 폴더에서 **`start.cmd`**를 두 번 클릭합니다. 앱이 Windows에 등록된 내 다운로드 폴더를 분석합니다. 화면 상단에서 실제 경로를 확인할 수 있습니다.
3. **파일 검토**에서 그룹을 고르고 파일 이름을 눌러 추천 이유를 확인합니다. 한 그룹만 옮기려면 **이 그룹 정리**, 전체를 옮기려면 전체 목록에서 **폴더로 정리**를 누릅니다.
4. **폴더 정리 미리보기**에서 목적지와 건너뛸 파일을 확인하고 **○개 파일 이동**을 누릅니다. 미분류 파일은 원래 위치에 두고, 목적지에 같은 이름의 파일이 있으면 건너뜁니다. 방금 옮긴 파일을 복원하려면 왼쪽 아래 **최근 이동 되돌리기**를 선택합니다.

### 어떤 파일이 함께 묶이나요?

저장소의 예제 파일 13개를 **애매한 파일만 본문 분석**을 켜고 분석한 결과입니다. 이름만으로 구분하기 어려운 `첨부.pdf`도 첫 페이지의 ‘Wireshark’를 단서로 네트워크 자료와 묶입니다. [예제 파일](demo.zip)

| 분석 결과 | 파일 수 | 파일 예시 |
| --- | ---: | --- |
| 네트워크 | 7 | `DNS_실습.pptx`, `wireshark_lab.zip`, `첨부.pdf` |
| 영양학 | 4 | `02_탄수화물.pdf`, `단백질_실습.pptx`, `과제.docx` |
| 미분류 | 2 | `IMG_2031.jpg`, `01.txt` |

## 검토와 편집

| 하고 싶은 일 | 앱에서 할 일 |
| --- | --- |
| 새로 받은 파일이나 하위 폴더 분석 | **다시 분석**을 누릅니다. 하위 폴더도 보려면 **분석 설정 → 하위 폴더 포함 → 적용하고 다시 분석**을 선택합니다. 기본 범위는 다운로드 폴더 바로 아래이며 한 번에 최대 3,000개를 분석합니다. |
| 두 파일이 함께 묶인 이유 확인 | **유사도 행렬**에서 두 파일이 만나는 셀을 누릅니다. 파일명·출처 등의 단서와 본문 분석 전후 점수를 비교할 수 있습니다. |
| 추천이 빗나간 파일 편집 | 파일을 체크하고 **선택 편집 → 다른 그룹으로 이동**에서 원하는 그룹이나 미분류를 선택합니다. 두 파일의 관계는 행렬에서 **같은 그룹** 또는 **다른 그룹**으로 저장할 수 있습니다. |
| 그룹 이름이나 구성 변경 | 그룹을 열고 **그룹 편집**에서 이름 변경·병합·분리를 선택합니다. **강의 표지로 과목명 찾기**를 켜면 강의소개 PDF나 PPTX 표지도 이름 후보를 찾는 데 사용합니다. |

### 브라우저에서 다운로드 출처 기록하기

기본 분석은 브라우저 확장 없이 실행할 수 있습니다. Edge나 Chrome을 연결하면 **연결 후 다운로드한 파일**의 상세 화면에서 웹페이지 제목과 주소, 확인된 강좌명을 볼 수 있습니다.

1. 앱의 **분석 설정 → 브라우저 출처 연결**을 누르면 확장 폴더 경로가 클립보드에 복사됩니다.
2. 브라우저의 확장 관리 페이지에서 **개발자 모드 → 압축 풀린 파일 로드**를 선택하고 복사한 경로를 지정합니다.
3. 조선대학교 e-Class는 기본 연결됩니다. 다른 HTTPS 사이트에서는 확장 아이콘의 **이 사이트 연결**을 누르고 권한을 허용한 뒤 새로고침합니다.
4. 해당 페이지에서 Windows 다운로드 폴더로 파일을 받은 뒤 앱에서 **다시 분석**을 누르고 파일 행을 엽니다.

## 소스에서 실행

Windows x64에서 Git, Python 3.13, Node.js 22.12 이상과 npm을 준비합니다. PowerShell에서 `python.exe --version`으로 Python이 PATH에 등록되어 있는지 확인하세요. 처음 실행할 때 `npx`가 Electron을 내려받습니다.

```powershell
git clone https://github.com/seungan123/downloads-organizer.git
cd downloads-organizer
npx.cmd --yes electron@45.3.3 ./desktop
```

## 저장소 둘러보기

| 위치 | 역할 |
| --- | --- |
| [desktop/](desktop/) · [desktop_service.py](desktop_service.py) | Electron 화면과 Python 서비스. 파일 상세, 유사도 행렬, 이동 미리보기를 연결합니다. |
| [engine.py](engine.py) · [terms.json](terms.json) · [readers.py](readers.py) | 파일명과 한·영 용어를 비교하고, 필요한 문서만 일부 읽어 그룹을 추천합니다. |
| [feedback.py](feedback.py) · [constraints.py](constraints.py) · [storage.py](storage.py) | 수동으로 정한 소속과 파일 관계를 저장하고, 실제 파일 이동과 복원을 처리합니다. |
| [browser_extension/](browser_extension/) · [capture_host.py](capture_host.py) | Edge·Chrome에서 다운로드한 파일과 페이지 출처를 연결합니다. |
| [test_pipeline.py](test_pipeline.py) · [test_desktop.py](test_desktop.py) | 예제 파일로 분류 결과, 그룹 편집, 파일 이동과 복원을 검증합니다. |

**팀 개발**에 필요한 작업 브랜치 예시, 테스트 명령, PR 작성 요령은 [기여 가이드](CONTRIBUTING.md)에 있습니다. 추천 점수의 기준, 지원 문서 형식, 로컬 저장 경로는 [분석 설계](docs/analysis.md)에서 확인하세요.

README 구성은 [Best-README-Template](https://github.com/othneildrew/Best-README-Template)을 참고했습니다.
