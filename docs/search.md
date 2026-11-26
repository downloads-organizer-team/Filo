# 검색과 관계 추천

## 앱에 포함된 검색 엔진

파일을 빨리 찾는 일과 같은 작업의 파일을 묶는 일은 별개입니다. 검색은 Everything의 색인을 활용하고, 그룹 추천은 앱의 파일명·문맥·시간·위치·출처 비교로 수행합니다. 검색 속도를 이유로 관계 판정 기준을 낮추지 않습니다.

Windows x64 설치 파일에는 검색 엔진 `vendor/everything/Everything.exe`와 IPC 클라이언트 `vendor/Everything3_x64.dll`이 들어 있습니다. Windows 서비스 설치나 관리자 권한 없이 앱 전용 인스턴스를 실행합니다. 검색 엔진은 현재 계정이 읽을 수 있는 로컬 고정 드라이브의 파일·폴더 이름을 색인합니다. 첫 실행은 저장된 색인을 여는 재실행보다 오래 걸릴 수 있습니다.

앱은 창을 열 때 검색 서비스를 시작합니다. SDK 전용 Python 프로세스가 독립된 입출력 파이프로 요청을 받고, 처음 연결한 클라이언트를 후속 검색에 재사용합니다. 네이티브 호출의 제한 시간은 5초입니다.

개발본은 실행 중인 Everything 1.5의 기본 인스턴스와 `1.5a`를 순서대로 확인합니다. 준비된 색인이 있으면 그 인스턴스의 검색 범위로 조회합니다. 연결할 수 없거나 색인이 준비 중이면 앱 전용 엔진을 시작합니다. `MOA_SEARCH_ROOTS`로 범위를 지정하면 그 범위에서 내장 엔진을 사용합니다.

내장 색인이 준비되는 동안에는 다운로드, 저장한 정리 위치, 사용자 홈의 Desktop·Documents 중 검색 범위 안에 있는 폴더를 먼저 확인합니다. 파일명 검색 한 건마다 폴더를 너비 우선으로 두 단계까지 훑고, 약 150ms 또는 12,000개 항목에서 멈춥니다. 이때의 결과는 **자주 쓰는 폴더**로 표시합니다. 검색창은 마지막 입력을 유지하고 전체 색인이 준비되면 결과를 갱신합니다.

설정과 색인은 기본적으로 `%LOCALAPPDATA%\MoaFileReview\Search`에 저장합니다. 검색창은 준비 상태를 표시하고 마지막 검색어를 자동으로 재시도합니다. 각 검색 전에 `Everything3_IsDBLoaded`로 색인 상태를 확인합니다. 개발 중 외부 테스트 인스턴스에 직접 연결하려면 `MOA_EVERYTHING_INSTANCE`에 해당 이름을 지정합니다.

파일명 일부는 정규식 리터럴로 이스케이프해 전달합니다. 검색 연산자를 실행하는 입력창이 아니며, 파일 이동이나 분석 범위를 몰래 늘리지 않습니다. 결과 폴더를 사용자가 추가한 후에만 해당 위치를 분석합니다.

### SDK에서 확인한 주의점

- `Everything3_GetResultFullPathNameW`에는 `FULL_PATH` 속성(240)을 요청해야 합니다. NAME과 PATH만 요청하면 충분하지 않습니다.
- 3.0.1.12의 `Everything3_SetSearchViewportCount`는 값을 변경한 뒤에도 FALSE를 반환합니다. 공식 C 소스와 실제 DLL 호출에서 확인했으며, `Everything3_GetSearchViewportCount`로 설정값을 확인합니다.
- 번들 DLL의 PE 내보내기 표와 실제 SDK 질의에서 전체 색인 건수(`Everything3_GetResultListCount`)와 반환된 항목 수(`Everything3_GetResultListViewportCount`)를 확인했습니다. 드라이브·폴더·파일 목록 색인이 겹치면 같은 경로가 여러 번 잡힐 수 있습니다. 화면에는 현재 받은 경로를 중복 제거해 최대 200개 표시하고, 색인 건수와 표시한 경로 수가 다르면 둘 다 알려 줍니다. 서로 다른 폴더의 동명 파일은 각각 표시합니다.

공식 자료:

- SDK 소스와 배포: https://github.com/voidtools/everything_sdk3
- 사용한 배포: https://github.com/voidtools/everything_sdk3/releases/tag/3.0.1.12
- API 선언: https://github.com/voidtools/everything_sdk3/blob/master/include/Everything3.h
- 구현: https://github.com/voidtools/everything_sdk3/blob/master/src/Everything3.c
- 재배포 라이선스·바이너리 해시: [Everything3-LICENSE.txt](../vendor/Everything3-LICENSE.txt)
- 검색 엔진은 [공식 1.5.0.1424b x64 영문 포터블 ZIP](https://www.voidtools.com/Everything-1.5.0.1424b.x64.en-US.zip)을 사용합니다. 배포 ZIP의 SHA-256은 `b6beff0f7808045d16585ffc785cc93ea27064cdffe5d674688abc26f3414e7b`입니다. [공식 체크섬](https://www.voidtools.com/Everything-1.5.0.1424b.sha256) · [엔진 라이선스](../vendor/everything/License.txt)

### 재배포 조건

공식 엔진과 SDK의 허가문은 저작권과 허가 고지를 포함하는 조건으로 복제·배포·판매를 허용합니다. 엔진에 들어 있는 PCRE는 바이너리와 함께 제공하는 자료에 저작권·조건·면책 문구를 실어야 하며, 사전 허가 없이 기여자 이름을 보증이나 홍보에 쓸 수 없습니다. [엔진·PCRE 공식 조건](https://www.voidtools.com/License.txt) · [SDK 3.0.1.12의 허가문](https://github.com/voidtools/everything_sdk3/blob/3.0.1.12/src/Everything3.c#L1-L22)

v1.2.0 설치 로그에서 `vendor/everything/License.txt`와 `vendor/Everything3-LICENSE.txt`를 확인했습니다. 전자는 공식 웹 고지(2018 David Carpenter)이며, 배포한 원본 EXE 자체에도 2026 voidtools 고지와 허가문이 들어 있습니다. 이 앱은 각 PC에서 전용 인스턴스를 사용합니다. 기업에서 중앙 색인을 공유하는 Everything Server 플러그인을 운영할 때는 별도 조건을 확인해야 합니다. [Everything Server 라이선스 안내](https://www.voidtools.com/support/everything/everything_server/)

## 확장 없는 기본 동작

파일명·실제 폴더·시각·번호·버전과 Windows `Zone.Identifier`에 남은 URL을 우선 사용합니다. 동일 시각, 동일 다운로드 도메인, ‘예약’ 같은 일반 단어는 보조 단서입니다. 카카오톡·클라우드 복사본의 시각과 출처가 원본과 같다고 가정하지 않습니다.

기존 브라우저 확장은 웹페이지 제목과 주소를 추가하는 선택 기능입니다. 확장 설치 대비 정확도 개선을 일반화할 실사용 데이터는 아직 없으므로 필수로 만들지 않습니다. Chrome·Edge는 기존 연결 경로를 사용하며 웨일의 Native Messaging은 검증되지 않았습니다.

## 검색 결과 표시와 열기

입력이 바뀌면 이전 질의를 취소합니다. `Everything3_IsFolderResult`가 참인 항목은 확장자에 관계없이 노란 폴더 아이콘으로 표시합니다. 파일의 Windows 아이콘은 이름과 경로를 표시한 뒤 불러옵니다.

이름 글자를 한 번 누르면 항목을 선택합니다. 이름을 빠르게 두 번 누르면 Electron이 현재 SDK 결과의 경로를 Windows 셸에 전달합니다. 선택한 이름을 잠시 뒤 다시 누르거나 F2를 누르면 이름을 편집합니다. Enter를 누르면 디스크와 화면에 새 이름을 적용합니다. 검색어를 바꾸거나 지우면 이전 목록의 열기 요청도 만료됩니다.

## 재현 가능한 검증

```powershell
python -B -X utf8 -m unittest discover -v
python -B -X utf8 test_search.py --sdk
python -B -X utf8 test_search.py --sdk ".\vendor\everything\Everything.exe"
python -B test_relationships.py --benchmark
```

첫 명령은 분류, 이동, 복원과 검색을 검증합니다. `--sdk`는 임시 폴더에서 내장 엔진을 실행해 한글 이름을 검색합니다. 실행 파일 경로를 함께 주면 별도 이름을 지정한 테스트 인스턴스에 SDK로 연결합니다. 개발 중 검색 범위를 좁히려면 `MOA_SEARCH_ROOTS`에 폴더의 절대 경로를 지정하세요. 여러 경로는 세미콜론으로 구분합니다.

측정은 파일 수, 파일명 구성, 본문 분석 여부, 실행 환경과 결과 묶음을 함께 기록합니다. 합성 자료의 실행 시간을 모든 실제 폴더의 성능으로 일반화하지 않습니다.

Windows에서는 `python desktop_smoke.py "Electron 실행 파일 경로"`로 실제 화면을 검증합니다. 이 테스트는 저장소에 포함된 엔진을 별도 인스턴스로 시작해 자동 재시도, 폴더 아이콘, 행 높이, 이름으로 열기, 선택 이동과 복원을 확인합니다.

### v1.2.0 기본 검색 범위 실측

2026-11-26에 Windows x64 PC 한 대에서 빈 앱 프로필로 Python 서비스를 실행했습니다. 기본 고정 드라이브를 대상으로 약 1초 간격으로 `Everything3_x64.dll`을 검색해 지정한 전체 경로가 처음 반환될 때까지 **192.6초**가 걸렸습니다. 그 응답에 기록된 검색 작업자의 요청·응답 시간은 **9ms**였습니다. 한 번의 관측값이며 UI 렌더링은 측정 범위에서 제외했습니다. [개발 가이드 실측표](file-organizing.html#timing)

### 이전 브랜치의 파일 정리 측정 결과

Windows 11 x64, Core Ultra 7 258V에서 얻은 단일 실행 값입니다. 합성 입력은 서로 구별되는 두 파일짜리 프로젝트들이며, 모든 쌍을 비교합니다. 후보를 생략해 속도를 얻는 방식은 사용하지 않았습니다.

| 파일 수 | 비교 쌍 | 전체 분석 | 행렬 계산 | 기대한 묶음 |
| ---: | ---: | ---: | ---: | ---: |
| 100 | 4,950 | 0.227초 | 0.013초 | 50개 일치 |
| 500 | 124,750 | 0.726초 | 0.370초 | 250개 일치 |
| 1,000 | 499,500 | 3.636초 | 1.870초 | 500개 일치 |

설치 전부터 존재하던 실제 파일 2,144개를 두 폴더에서 합쳐 분석한 별도 실행은 본문 분석을 끈 상태에서 18.733초였습니다. 출처 URL이 없는 파일 830개, 브라우저 다운로드 시각이 없는 파일 2,144개를 포함했고 945개를 미분류로 남겼습니다. 이 자료의 정답 묶음을 사용자가 라벨링한 것은 아니므로 **분류 정확도 수치로 해석하면 안 됩니다**. 분석 전후 파일 목록·크기·수정 시각·식별자 해시는 동일했고 실제 파일 이동은 하지 않았습니다.

관련 작업별 분석에서 전체 유사도 행렬의 크기는 O(n²)입니다. 파일 정리는 선택한 원본 폴더에서 총 3,000개까지 분석합니다.
