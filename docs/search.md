# 검색과 관계 추천

## 공식 SDK 선택

파일을 빨리 찾는 일과 같은 작업의 파일을 묶는 일은 별개입니다. 검색은 Everything의 색인을 활용하고, 그룹 추천은 앱의 파일명·문맥·시간·위치·출처 비교로 수행합니다. 검색 속도를 이유로 관계 판정 기준을 낮추지 않습니다.

Windows x64 앱에 공식 Everything SDK 3.0.1.12의 `Everything3_x64.dll`을 포함했습니다. Everything 1.5가 실행 중이면 기본 인스턴스, 이어서 `1.5a`에 연결합니다. 다른 이름으로 실행한 인스턴스는 `MOA_EVERYTHING_INSTANCE` 환경 변수로 지정할 수 있습니다. `MOA_EVERYTHING_DLL`은 명시적인 SDK 경로를 지정할 때 사용합니다.

앱은 창을 열 때 검색 서비스를 시작합니다. SDK 전용 Python 프로세스가 독립된 입출력 파이프로 요청을 받고, 처음 연결한 클라이언트를 후속 검색에 재사용합니다. 네이티브 호출의 제한 시간은 5초입니다.

기본 인스턴스에 연결할 수 없으면 Windows에 등록된 Everything 1.5 설치 경로를 확인하고 `-startup`으로 한 차례 실행합니다. 별도 이름을 지정한 인스턴스는 사용자가 실행합니다. 검색창은 연결 대기를 표시하고 최신 입력을 자동으로 재시도합니다. 각 검색 전에 `Everything3_IsDBLoaded`로 색인이 준비됐는지 확인합니다.

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

## 확장 없는 기본 동작

파일명·실제 폴더·시각·번호·버전과 Windows `Zone.Identifier`에 남은 URL을 우선 사용합니다. 동일 시각, 동일 다운로드 도메인, ‘예약’ 같은 일반 단어는 보조 단서입니다. 카카오톡·클라우드 복사본의 시각과 출처가 원본과 같다고 가정하지 않습니다.

기존 브라우저 확장은 웹페이지 제목과 주소를 추가하는 선택 기능입니다. 확장 설치 대비 정확도 개선을 일반화할 실사용 데이터는 아직 없으므로 필수로 만들지 않습니다. Chrome·Edge는 기존 연결 경로를 사용하며 웨일의 Native Messaging은 검증되지 않았습니다.

## 검색 결과 표시와 열기

입력이 바뀌면 이전 질의를 취소합니다. `Everything3_IsFolderResult`가 참인 항목은 확장자에 관계없이 노란 폴더 아이콘으로 표시합니다. 파일의 Windows 아이콘은 이름과 경로를 표시한 뒤 불러옵니다.

이름 버튼을 누르면 Electron이 현재 SDK 결과의 경로를 Windows 셸에 전달합니다. 검색어를 바꾸거나 지우면 이전 목록의 열기 요청도 만료됩니다.

## 재현 가능한 검증

```powershell
python -B -X utf8 -m unittest discover -v
python -B -X utf8 file_search.py Everything.exe
python -B -X utf8 test_search.py --sdk
python -B -X utf8 test_search.py --sdk "C:\Program Files\Everything\Everything.exe"
python -B test_relationships.py --benchmark
```

첫 명령은 기존 분류·이동 회귀와 복수 폴더·검색 회귀를 실행합니다. 두 번째는 실행 중인 Everything 1.5에 직접 질의합니다. `--sdk`는 Electron처럼 서비스 입력 파이프를 열어 둔 상태에서 실제 SDK 백엔드와 설치된 `Everything.exe` 검색 결과를 확인합니다. Everything이 실행되지 않은 환경에서는 명시적으로 실패하는 선택 검증이며, 단위 테스트에서 조용히 건너뛰는 검사가 아닙니다.

실행 파일 경로를 함께 주면 테스트가 임시 폴더만 색인하는 별도 Everything 1.5 인스턴스를 열고, 합성 파일을 찾은 뒤 종료합니다.

측정은 파일 수, 파일명 구성, 본문 분석 여부, 실행 환경과 결과 묶음을 함께 기록합니다. 합성 자료의 실행 시간을 모든 실제 폴더의 성능으로 일반화하지 않습니다.

Windows에서는 `python desktop_smoke.py "Electron 실행 파일 경로" "Everything 실행 파일 경로"`로 실제 화면을 검증합니다. 검색어를 먼저 입력하고 테스트용 Everything을 시작해 자동 재시도, 폴더 아이콘, 행 높이, 이름으로 열기, 선택 이동과 복원을 확인합니다.

### 이전 브랜치의 측정 결과

Windows 11 x64, Core Ultra 7 258V에서 얻은 단일 실행 값입니다. 합성 입력은 서로 구별되는 두 파일짜리 프로젝트들이며, 모든 쌍을 비교합니다. 후보를 생략해 속도를 얻는 방식은 사용하지 않았습니다.

| 파일 수 | 비교 쌍 | 전체 분석 | 행렬 계산 | 기대한 묶음 |
| ---: | ---: | ---: | ---: | ---: |
| 100 | 4,950 | 0.227초 | 0.013초 | 50개 일치 |
| 500 | 124,750 | 0.726초 | 0.370초 | 250개 일치 |
| 1,000 | 499,500 | 3.636초 | 1.870초 | 500개 일치 |

설치 전부터 존재하던 실제 파일 2,144개를 두 폴더에서 합쳐 분석한 별도 실행은 본문 분석을 끈 상태에서 18.733초였습니다. 출처 URL이 없는 파일 830개, 브라우저 다운로드 시각이 없는 파일 2,144개를 포함했고 945개를 미분류로 남겼습니다. 이 자료의 정답 묶음을 사용자가 라벨링한 것은 아니므로 **분류 정확도 수치로 해석하면 안 됩니다**. 분석 전후 파일 목록·크기·수정 시각·식별자 해시는 동일했고 실제 파일 이동은 하지 않았습니다.

현재 분석은 O(n²)이며 3,000개 한도를 유지합니다. Everything 검색이 빠르다는 사실이 대량 파일의 관계 분석까지 같은 속도라는 뜻은 아닙니다.
