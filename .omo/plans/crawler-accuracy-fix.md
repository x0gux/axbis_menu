# crawler-accuracy-fix - Work Plan

## TL;DR (For humans)
<!-- Fill this LAST, after the detailed plan below is written, so it summarizes the REAL plan. -->
<!-- Plain English for a non-engineer: NO file paths, NO todo numbers, NO wave/agent/tool names. -->

**What you'll get:** 주간 구내식 메뉴가 5일 전부 날짜별로 정확하게 저장되고, 인접 요일 메뉴가 섞여 들어가던 오염이 사라집니다. 또한 매 크롤링 실행 시 OCR 원본 좌표가 디버그 파일로 남아, 앞으로 같은 버그가 재발하면 자동 테스트가 잡아냅니다. 메뉴 조회 API는 7일 이상 오래된 데이터를 자동으로 다시 크롤링해 갱신합니다.

**Why this approach:** 근본 원인이 "OCR이 날짜 줄을 한 덩어리로 묶어 읽는데 파서가 날짜 하나만 꺼내고, 박스 왼쪽 끝 좌표만 쓰기 때문"으로 확정됐습니다(실측 데이터로 확인). 따라서 엔진을 바꾸지 않고 파서 쪽에서 정규화·박스 중심 좌표·날짜 행 단위 앵커링·중간점 열 경계로 재설계하는 것이 가장 확실하고 검증 가능합니다. 실제 사이트 1회 크롤링으로 얻은 좌표 데이터를 회귀 테스트 픽스처로 고정해, 미래의 재발을 기계적으로 잡아냅니다.

**What it will NOT do:** OCR 엔진 교체나 메뉴 이름 오타 교정은 하지 않습니다. 배포 설정(vercel.json)과 게시물 선정 로직은 건드리지 않습니다. 기존 날짜별 메뉴 아카이브 파일은 삭제·이관하지 않습니다.

**Effort:** Short-Medium (크롤링 실측 + paddlepaddle 설치에 수 분 소요)
**Risk:** Medium - paddlepaddle wheel이 로컬 Python 3.14를 지원하지 않을 수 있음(계획에 3.12 venv 폴백 포함). 실측은 네트워크/사이트 상태 의존.
**Decisions to sanity-check:** (1) 실측 검증 포함(Q1 승인) — paddleocr 설치 + 실사이트 1회 크롤링. (2) /meal 신선도 수정 포함(Q2 승인) — 단, Vercel 서버리스에서는 paddle 미번들+60초 제한으로 재크롤링이 실패하고 stale 데이터로 폴백하는 것이 설계된 동작이며, 실제 운영 신선도는 기존 CI 크론(평일 09:43 KST 자동 크롤링 커밋)이 담당함. (3) 테스트 프레임워크 pytest(Q3 승인).

Your next move: 계획 승인 후 `$start-work crawler-accuracy-fix`로 실행하거나, 고정밀 리뷰를 먼저 요청하세요. Full execution detail follows below.

---

> TL;DR (machine): Short-Medium effort, Medium risk. croll.py 파싱 재설계(정규화/중심좌표/날짜행 앵커/중간점 경계/fallback) + ocr_debug 저장 + main.py 7일 신선도 재크롤링(서버리스 폴백 명시) + 실측 픽스처 pytest 회귀. 6 todos + 4 final verifiers.

## Scope
### Must have
- `croll.py` 파싱 정확도 수정: 주간 메뉴 5일 전부 날짜별 생성, 인접 열 오염 제거
- PaddleOCR import 격리(guarded import) — paddleocr 미설치 환경에서도 파서 순수함수 테스트 가능
- OCR 원본 좌표 디버그 아티팩트(`meal_output/ocr_debug.json`) 저장 — 회귀 픽스처 원본
- `main.py` /meal 의 stale menu.json 신선도 체크(7일) + 재크롤링 시도 + 실패 시 stale 폴백 (로컬/개발 환경용 가용성 기능. 서버리스에서는 paddle 미번들로 fail-fast → stale 폴백이 설계 동작)
- pytest 기반 회귀 테스트(실측 픽스처 사용, paddleocr import 없이 실행)

### Must NOT have (guardrails, anti-slop, scope boundaries)
- OCR 엔진 교체/추가(PaddleOCR 유지), 메뉴명 사전 기반 텍스트 교정(오인식 "수정") 금지
- 게시판 게시물 선정 로직(get_latest_meal_post) 변경 금지
- vercel.json / `.github/workflows/crawl_meal.yml`(CI 크롤러) 변경 금지
- 기존 meal_output/menu_*.json 아카이브 삭제·이관 금지
- 응답 JSON 스키마(post/period/images/daily_menus/menu_text) 파괴 금지 - 필드 추가만 허용하되, menu.json에 대량 ocr_items 원본을 넣는 것 금지(API 페이로드 비대화)
- pytest를 requirements.txt에 추가 금지(그 파일은 Vercel 번들용)

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: tests-after + pytest (신규 헬퍼는 함수 단위 테스트, 파서는 실측 픽스처 회귀 테스트)
- pytest는 `requirements-dev.txt`로 선언하고 로컬에 `python3 -m pip install pytest`로 설치(T1에서 수행)
- 격리 원칙: 단위 테스트는 `from croll import ...` 시 PaddleOCR import가 guarded 되어 있어야 실행 가능(T1에서 구현, T5 설치 이전에 검증)
- Evidence: .omo/evidence/task-<N>-crawler-accuracy-fix.<ext> (outside ulw-loop use .omo/evidence/)
- 실측 근거: `python3 croll.py` 1회 실행 → meal_output/ocr_debug.json 확보 → `pytest -q` 전부 PASS + `python3 -c "...assert len(d['daily_menus'])==5"` 통과
- 운영 확인(병행): 커밋 반영 후 다음 CI 크론(`.github/workflows/crawl_meal.yml`, 평일 09:43 KST)의 자동 커밋에서 menu.json daily_menus 5일 키를 사람이 확인(자동 단계 아님, 후속 확인 사항으로 기록)

## Execution strategy
### Parallel execution waves
> croll.py 핵심 파서가 단일 파일이므로 croll.py 내 작업(T1→T2→T3)은 직렬. 파일 단위 병렬은 T1(croll.py)×T4(main.py)에서만 발휘.

- Wave 1: T1 (croll.py 정규화/좌표/앵커/격리), T4 (main.py 신선도) — 서로 다른 파일, 병렬 가능
- Wave 2: T2 (croll.py 열 경계/fallback) → 완료 후 T3 (croll.py 디버그 저장) — 같은 파일이라 직렬(병렬 금지)
- Wave 3: T5 (실측 크롤링 1회)
- Wave 4: T6 (픽스처 회귀 테스트)

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| T1 | - | T2, T3, T5 | T4 |
| T2 | T1 | T3, T5, T6 | 없음(같은 파일) |
| T3 | T1, T2 | T5 | 없음(같은 파일) |
| T4 | - | T6 | T1, T2, T3 |
| T5 | T1, T2, T3 | T6 | - |
| T6 | T2, T4, T5 | F1-F4 | - |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->

- [x] 1. croll.py - OCR 아이템 정규화·박스 중심 좌표·날짜 행 앵커링·괄호 요일 토큰 차단 + import 격리 + pytest 인프라
  What to do:
  - **import 격리(Metis A1)**: `croll.py:43`의 `from paddleocr import PaddleOCR`를 guarded import로 교체:
    ```python
    try:
        from paddleocr import PaddleOCR
    except Exception:
        PaddleOCR = None
    ```
    `main()` 최상단(croll.py:1069)에 `if PaddleOCR is None: raise RuntimeError("paddleocr 미설치")` 가드 추가. 이로써 `from croll import parse_daily_menus` 등 순수함수 import가 paddleocr 미설치에서도 성공함.
  - **pytest 인프라(Metis A2)**: `python3 -m pip install pytest` 실행 + `requirements-dev.txt` 생성(`pytest` 1줄). requirements.txt는 수정 금지(Vercel 번들용).
  - `croll.py`에 `_normalize_ocr_text(text)` 헬퍼 추가: 전각 괄호 `(→(` `）→)` 통일, `(\d)\s*월`, `월\s*(\d)`, `(\d)\s*일` 사이 공백 제거, 다중 공백 축약. `clean_text`는 그대로 두고 새 헬퍼로 분리.
  - `_find_date_line`(croll.py:660-676) 수정: `_normalize_ocr_text` 적용 후 정규식 `(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*[\(（]?\s*([월화수목금토일])\s*[\)）]?`로 매칭. 요일 없는 날짜도 수용(요일 None 반환).
  - **요일 None 해소(Metis A3)**: 요일이 None인 날짜는 `datetime.date(year, month, day).weekday()`로 요일을 즉시 도출해 채움(한글 요일 매핑: 0=월...6=일). "YYYY-MM-DD (요일)" 키 형식은 항상 유지.
  - `run_ocr`(croll.py:408-506) 좌표 보정: rec_boxes 요소가 길이 4 이상이면 x=(box[0]+box[2])/2, y=(box[1]+box[3])/2 (박스 중심). 아이템 dict에 `x1`, `x2`(=box[0], box[2])와 `text_len`(len(text))도 함께 저장.
  - **병합 박스 다중 날짜(Metis B1)**: `parse_daily_menus`에서 하나의 OCR 아이템 텍스트에 날짜가 2개 이상 매칭되면 `finditer`로 전부 추출하고, 각 날짜의 x를 문자 오프셋 비례 보간: `x ≈ x1 + (x2-x1) * (match.start() / len(normalized_text))`. 날짜 순서는 등장 순서. 같은 박스에서 나온 날짜들이 동일 x를 갖는 상황 금지.
  - **날짜 행 앵커링**: 날짜 감지 아이템들의 y를 y_threshold=25 클러스터링해 "날짜 행"을 식별하고, 행 내 날짜 앵커를 x 오름차순 정렬해 열 앵커 목록 생성.
  - `_is_weekday_token(text)` 헬퍼 추가: `_normalize_ocr_text` 후 `^[\(（]?[월화수목금토일][\)）]?$` 매칭 시 True. `parse_daily_menus`의 menu_items 필터에서 이 토큰을 배제(기존 skip_patterns 앞 단계).
  - 단위 테스트 `tests/test_parse_daily_menus.py` 작성: (a) "10 월1 2 일 (월)" → (10,12,월) 파싱, (b) "10월12일" 요일 없음 → 요일이 날짜에서 도출됨(예: 2026-10-12 → 월), (c) "(월)" 토큰이 menu_items에 유입되지 않음, (d) 병합 문자열 "10월12일 (월) 10월13일(화)"(x1=100, x2=300, text 길이에 비례) → 2개 날짜가 서로 다른 x를 갖고 x순 정렬됨.
  Must NOT do: PaddleOCR 초기화 파라미터(croll.py:1096-1104) 변경 금지. `get_latest_meal_post`/`get_menu_images`/`download_image` 수정 금지. HTML 셀렉터(`.tb_body` 등) 변경 금지. requirements.txt 수정 금지.
  Parallelization: Can parallel: YES | Wave 1 | Blocks: [2, 3, 5] | Blocked by: []
  References (executor has NO interview context - be exhaustive):
  - Pattern: `croll.py:43` - 교체 대상 최상단 import(untagged)
  - Pattern: `croll.py:660-676` - 기존 _find_date_line 정규식(교체 대상)
  - Pattern: `croll.py:712-792` - 기존 parse_daily_menus 아이템 순회/필터 구조(재사용 위치)
  - Pattern: `croll.py:408-506` - run_ocr rec_boxes 파싱 및 (x,y) 추출부
  - Pattern: `croll.py:513-584` - group_ocr_lines y_threshold 클러스터링 기법(날짜 행 클러스터링에 동일 기법 적용)
  - Pattern: `croll.py:1069-1076` - main() 진입부(RuntimeError 가드 삽입 위치)
  - Test: `tests/test_parse_daily_menus.py` - 신규 생성. pytest 스타일. `from croll import _normalize_ocr_text, _find_date_line, _is_weekday_token, parse_daily_menus`만 사용(가드 import 덕분에 paddleocr 불필요).
  - External: https://docs.pytest.org/en/stable/getting-started.html
  Acceptance criteria (agent-executable):
  - [ ] `python3 -m pip install pytest` 성공, `requirements-dev.txt`에 `pytest` 존재: `grep -x pytest requirements-dev.txt`
  - [ ] paddleocr 미설치 상태에서 `python3 -m pytest tests/test_parse_daily_menus.py -q` PASS (T5 설치 **이전에** 실행해 격리를 실증)
  - [ ] `python3 -c "import ast; ast.parse(open('croll.py').read())"` 성공
  - [ ] `python3 -c "from croll import PaddleOCR; print(PaddleOCR is None or 'installed')"` 오류 없음
  QA scenarios:
  ```
  Scenario: 정규화된 날짜 파싱
  Tool: `python3 -m pytest tests/test_parse_daily_menus.py -q`
  Steps: 테스트 실행
  Expected: 4개 테스트 모두 PASS (종료코드 0)
  Evidence: .omo/evidence/task-1-crawler-accuracy-fix.txt

  Scenario: paddleocr 미설치 환경에서 테스트 격리
  Tool: `python3 -m pytest tests/test_parse_daily_menus.py -q` (paddleocr 미설치 상태, T5 이전 실행)
  Steps: `python3 -c "import paddleocr"`가 ModuleNotFoundError임을 확인 후 테스트 실행
  Expected: 테스트 PASS — guarded import 덕분에 파서 함수들이 로드됨
  Evidence: .omo/evidence/task-1-crawler-accuracy-fix-isolation.txt
  ```
  Commit: YES | `fix(crawler): normalize OCR text, box-center coords, date-row anchoring, guarded import` | Files: [croll.py, tests/test_parse_daily_menus.py, requirements-dev.txt]

- [x] 2. croll.py - 중간점 열 경계 배정 + 요일 헤더/period fallback + 연도 도출
  What to do:
  - 열 배정 교체: 열 앵커 x 목록을 정렬해 인접 앵커 중간점으로 경계 배열 생성, 아이템 x가 속한 구간의 열에 배정(`nearest_col` 대체, croll.py:805-814). 앵커가 1개면 전체를 그 열에 배정.
  - fallback 1 - 요일 헤더 앵커: `_find_day_header`(croll.py:679-687)로 감지된 MON~FRI 헤더 아이템을 버리지 말고 x 좌표를 보조 앵커로 수집. 날짜 앵커 수 < 요일 헤더 수이고 두 x 그룹이 1:1 대응(각 날짜 앵커의 최근접 헤더가 서로 다를 때)이면 헤더 x를 빠진 열의 앵커로 채움.
  - fallback 2 - period 역산 + **우선순위 규칙(Metis B2)**: 위로도 열이 부족하면 `extract_period`(croll.py:619-653) 결과에서 시작일을 파싱해 월~금(또는 기간 일수) 날짜 리스트를 생성. 배정 규칙: (1) 기존 날짜 앵커가 있는 열은 절대 덮어쓰지 않음 — 날짜 앵커가 항상 우선. (2) period는 앵커 없는 열만 x순(좌→우)으로 period 시작일부터 순서대로 채움. (3) 채운 날짜가 기존 앵커와 충돌하면 앵커를 유지하고 불일치 내용을 evidence에 기록. weekday는 `datetime.date.weekday()`로 도출.
  - 연도 도출: `parse_daily_menus(ocr_items, period_str, year=None)` 시그니처로 변경. year가 None이면 period_str의 `(\d{4})` 또는 `(\d{2})\.\d{2}`에서 도출(기존 로직 croll.py:852-859 유지), 그래도 없으면 `datetime.date.today().year`. main(croll.py:1186-1189) 호출부에 post["date"]("2026-10-12" 형식)에서 연도를 추출해 전달. 하드코드 `year = 2026` 제거.
  - 단위 테스트 추가: (a) 날짜 앵커 2개 + 요일 헤더 5개 → 5열 복원, (b) 앵커 2개 + period "26.10.12~10.16" → 누락 3열이 역산으로 채워지고 기존 앵커는 불변, (c) 중간점 경계 - 앵커 x=100, x=300일 때 x=190 아이템은 첫 열.
  Must NOT do: 코스(course) 경계 로직(croll.py:819-847) 구조 변경 금지(버그 없음). 날짜 포맷 "YYYY-MM-DD (요일)" 키 변경 금지.
  Parallelization: Can parallel: NO (croll.py 동일 파일 — T3와 직렬) | Wave 2 | Blocks: [3, 5, 6] | Blocked by: [1]
  References (executor has NO interview context - be exhaustive):
  - Pattern: `croll.py:801-814` - 교체 대상 nearest_col
  - Pattern: `croll.py:619-653` - extract_period 반환 형식(예: "26.10.12~10.16")
  - Pattern: `croll.py:679-687` - _find_day_header(DAY_KEYWORDS 매핑)
  - Pattern: `croll.py:849-910` - daily_menus 생성 및 아이템 배정 루프(수정 대상)
  - Test: `tests/test_parse_daily_menus.py` - T1에서 생성한 파일에 테스트 추가
  Acceptance criteria (agent-executable):
  - [ ] `python3 -m pytest tests/test_parse_daily_menus.py -q` 전부 PASS
  - [ ] `grep -n "year = 2026" croll.py` 결과 없음(종료코드 1)
  QA scenarios:
  ```
  Scenario: fallback 열 복원
  Tool: `python3 -m pytest tests/test_parse_daily_menus.py -q`
  Steps: 테스트 실행
  Expected: 신규 3개 테스트 PASS
  Evidence: .omo/evidence/task-2-crawler-accuracy-fix.txt

  Scenario: 하드코드 제거 확인
  Tool: `grep -n "year = 2026" croll.py`
  Steps: grep 실행
  Expected: 매칭 없음 (종료코드 1)
  Evidence: .omo/evidence/task-2-crawler-accuracy-fix-grep.txt
  ```
  Commit: YES | `fix(crawler): midpoint column boundaries with weekday/period fallback` | Files: [croll.py, tests/test_parse_daily_menus.py]

- [x] 3. croll.py - OCR 원본 좌표 디버그 아티팩트 저장 (T2 이후 직렬 실행)
  What to do:
  - 디버그 페이로드를 만드는 순수 함수 `build_ocr_debug(post, images_with_items) -> dict`를 croll.py에 추가. 구조: `{"post_title": <title>, "post_date": <date>, "period": <period_str>, "captured_at": <ISO 8601 UTC>, "images": [{"url":..., "items":[{"text","x","y","x1","x2"}...]}]}` (Metis E5 - period 포함).
  - main 루프(croll.py:1113-1160)에서 이미지별 OCR 아이템을 모아 `meal_output/ocr_debug.json`에 저장(ensure_ascii=False, indent=2, 매 실행 덮어쓰기).
  - **menu.json에는 ocr_items를 넣지 않음(Metis C1)** — /meal API 페이로드 비대 방지. menu.json 스키마는 기존 그대로.
  - `build_ocr_debug` 단위 테스트: stub 아이템을 넣어 period/post_title 반영과 구조를 검증(파일 I/O 없이).
  Must NOT do: meal_output/menu_*.json 기존 파일 삭제/변경 금지. ocr_debug.json에 이미지 바이너리 포함 금지. menu.json에 원본 좌표 배열 포함 금지.
  Parallelization: Can parallel: NO (croll.py 동일 파일 — T2 다음 순서) | Wave 2 | Blocks: [5] | Blocked by: [1, 2]
  References (executor has NO interview context - be exhaustive):
  - Pattern: `croll.py:1106-1160` - main의 이미지별 OCR 루프(저장 지점)
  - Pattern: `croll.py:936-953` - json.dump 패턴(ensure_ascii=False, indent=2) 준수
  - Test: `tests/test_parse_daily_menus.py` - build_ocr_debug 단위 테스트 추가
  Acceptance criteria (agent-executable):
  - [ ] `python3 -m pytest tests/test_parse_daily_menus.py -q` PASS (build_ocr_debug 테스트 포함)
  - [ ] `python3 -c "from croll import build_ocr_debug; print('ok')"` 오류 없음
  - [ ] 실제 파일 생성은 T5에서 검증(이 단계에서는 크롤링 실행 금지)
  QA scenarios:
  ```
  Scenario: 디버그 페이로드 빌더
  Tool: `python3 -m pytest tests/test_parse_daily_menus.py -q -k debug`
  Steps: stub 아이템으로 build_ocr_debug 검증
  Expected: PASS - period/post_title/items 구조 확인
  Evidence: .omo/evidence/task-3-crawler-accuracy-fix.txt

  Scenario: menu.json 비대 방지 확인
  Tool: `grep -n "ocr_items" croll.py`
  Steps: grep으로 save_result/menu.json 경로에 ocr_items가 없음을 확인
  Expected: build_ocr_debug/ocr_debug.json 관련만 매칭 (menu.json 기록부에 없음)
  Evidence: .omo/evidence/task-3-crawler-accuracy-fix-grep.txt
  ```
  Commit: YES | `feat(crawler): persist raw OCR items for regression fixtures` | Files: [croll.py, tests/test_parse_daily_menus.py]

- [x] 4. main.py - menu.json 신선도 체크 + 자동 재크롤링(로컬 가용성 폴백 명시)
  What to do:
  - **범위 명시(Metis C2)**: 이 기능은 로컬/개발 환경의 가용성 폴백이다. Vercel 서버리스에서는 paddle 미번들 + 60초 제한으로 재크롤링이 fail-fast로 실패하고 stale 데이터를 반환하는 것이 설계 동작이다. 운영 신선도는 기존 CI 크론(`.github/workflows/crawl_meal.yml`, 평일 09:43 KST)이 담당한다. 이 사실을 main.py 해당 함수 docstring에 기록.
  - `main.py`에 `REFRESH_DAYS = 7` 상수 추가. 신선도 판정은 순수 함수 `_is_fresh(post_date_str, today=None) -> bool`로 분리:
    - 날짜 파싱: `data.get("post", {}).get("date")` 체이닝(Metis B3). 값이 None/빈 문자열/형식 오류 → False(=not fresh → 재크롤링 시도).
    - `today - post.date <= 7일`이면 True. 경계 7일 포함.
    - 신선도 기준은 게시물 작성일 기준임을 docstring에 명시(Metis C3): 게시물이 메뉴 주간 시작 전에 올라오면 조기 stale 처리되지만 안전한 방향.
  - `/meal`(main.py:32-53) 로직 교체:
    1. menu.json 로드 성공 + `_is_fresh` True → 그대로 반환.
    2. not fresh → `import croll; croll.main()` 실행 후 다시 로드해 반환.
    3. 재크롤링 예외 발생 시: 기존(stale) 데이터가 있으면 그것을 반환(가용성 우선, 500 없음), 없으면 기존 에러 메시지 흐름 유지(main.py:44-46).
  - 테스트 `tests/test_main_freshness.py`:
    (a) 오늘 날짜 → True, (b) 8일 전 → False, (c) 잘못된 형식 "abc" → False, (d) None/누락 → False, (e) 경계 7일 → True — 모두 `_is_fresh(..., today=date(2026,10,16))` 식으로 today 주입해 실제 값 단정(Metis E1 - vacuous assert 제거).
    (f) **재크롤링 성공 경로(Metis E1)**: monkeypatch로 `sys.modules["croll"]` 스텁(main이 호출하는 크롤 함수가 menu.json을 갱신한다고 가정) + stale menu.json → /meal 호출 시 크롤 스텁이 1회 호출되고 갱신된 데이터 반환.
    (g) **재크롤링 실패 폴백**: 크롤 스텁이 예외 발생 → /meal이 stale 데이터를 반환(500 아님).
  Must NOT do: 응답 스키마 변경(필드 삭제/이름 변경) 금지. 크롤링을 동기→비동기 전환 금지. FastAPI 앱 구조(app 객체) 변경 금지. requirements.txt에 의존성 추가 금지.
  Parallelization: Can parallel: YES (main.py - T1과 다른 파일) | Wave 1 | Blocks: [6] | Blocked by: []
  References (executor has NO interview context - be exhaustive):
  - Pattern: `main.py:18-53` - 기존 /meal 로직(교체 대상)
  - Pattern: `main.py:2-9` - 기존 import 스타일(표준 라이브러리 우선)
  - Data: `meal_output/menu.json` - `post.date`가 "2026-10-12" ISO 형식임이 실제 데이터로 확인됨
  - Data: `.github/workflows/crawl_meal.yml` - 운영 신선도를 담당하는 CI 크론(runs-on: self-hosted, cron 평일 UTC 01:00). 수정 금지, docstring 참조용.
  - Test: `tests/test_main_freshness.py` - 신규 생성. croll은 sys.modules 스텁으로 대체하므로 paddleocr 불필요.
  Acceptance criteria (agent-executable):
  - [ ] `python3 -m pytest tests/test_main_freshness.py -q` 전부 PASS (7개 테스트)
  - [ ] `python3 -c "from main import _is_fresh; from datetime import date; assert _is_fresh('2026-10-12', today=date(2026,10,16)) is True; assert _is_fresh('2026-10-08', today=date(2026,10,16)) is False"` 성공
  QA scenarios:
  ```
  Scenario: 신선도 경계값
  Tool: `python3 -m pytest tests/test_main_freshness.py -q`
  Steps: 테스트 실행
  Expected: 7개 테스트 PASS
  Evidence: .omo/evidence/task-4-crawler-accuracy-fix.txt

  Scenario: 실패 폴백 - 크롤링 예외 시 stale 반환
  Tool: `python3 -m pytest tests/test_main_freshness.py -q -k fallback`
  Steps: (g) 시나리오 실행
  Expected: stale 데이터 반환, 500 없음
  Evidence: .omo/evidence/task-4-crawler-accuracy-fix-fallback.txt
  ```
  Commit: YES | `fix(api): refresh stale weekly menu older than 7 days with availability fallback` | Files: [main.py, tests/test_main_freshness.py]

- [x] 5. 실측 - paddleocr 설치 + 실사이트 1회 크롤링으로 좌표 픽스처 확보
  What to do:
  - **Python 호환성 사전 점검(Metis D1)**: 로컬 Python은 3.14.7. 먼저 `python3 -m pip download --dry-run --no-deps paddlepaddle`로 wheel 가용성 확인. 실패 시 **Python 3.12 venv 폴백**(CI 러너와 동일 버전): `python3.12 -m venv .venv312 && .venv312/bin/pip install paddlepaddle paddleocr pytest` 후 이후 모든 실행(pytest 포함)을 해당 venv로 수행. 선택한 경로와 버전을 evidence에 기록.
  - `python3 croll.py` 1회 실행. 콘솔 출력 전체를 evidence로 저장. 네트워크 실패(게시판 접속) 시 1회 재시도 후 BLOCKED 보고.
  - 실행 결과물 확인: `meal_output/ocr_debug.json` 생성, `meal_output/menu.json` 갱신, `meal_output/menu_2026-10-*.json` 5일 생성 여부 목록화.
  - **아이템 수 기준 완화(Metis D2)**: 아이템 수 >= 100은 경고로 격하 — 100 미만이면 즉시 실패시키지 말고 evidence에 "저텍스트 이미지 의심" 노트와 실제 수를 기록하고, 아래 daily_menus==5 단정으로 실질 검증.
  - 확보된 `meal_output/ocr_debug.json`을 `tests/fixtures/ocr_items.json`으로 복사(픽스처).
  Must NOT do: croll.py/main.py 코드 수정 금지(버그 발견 시 계획 변경 보고). 게시물 수동 선택 금지(main 흐름 그대로). paddlepaddle GPU 변형 설치 금지. requirements.txt 수정 금지.
  Parallelization: Can parallel: NO | Wave 3 | Blocks: [6] | Blocked by: [1, 2, 3]
  References (executor has NO interview context - be exhaustive):
  - Pattern: `croll.py:1096-1104` - PaddleOCR 초기화 파라미터(한국어, doc orientation off)
  - Pattern: `croll.py:19-40` - oneDNN 패치(macOS에서는 무해, 제거 금지)
  - Data: `https://www.g5w.co.kr/home/m_board.php?ps_db=b7` - 크롤링 대상 게시판. 현재 최신 게시물 "구내식 메뉴(26.10.12~16)" (2026-10-12 작성, 주간 = 월~금 5일)
  - Data: `.github/workflows/crawl_meal.yml` - CI 러너가 Python 3.12/self-hosted Windows임 - venv 폴백 시 버전 근거
  - External: https://www.paddleocr.ai/latest/version3.x/pipeline_usage/OCR.html - PaddleOCR 3.x predict API
  Acceptance criteria (agent-executable):
  - [ ] `test -f meal_output/ocr_debug.json` 성공
  - [ ] `python3 -c "import json;d=json.load(open('meal_output/ocr_debug.json'));assert d['images'] and all(len(i['items'])>0 for i in d['images'])"` 성공
  - [ ] `python3 -c "import json;d=json.load(open('meal_output/menu.json'));assert len(d['daily_menus'])==5"` 성공 (Metis E2 - T1/T2 반영 후 실측이므로 성공해야 함)
  - [ ] `test -f tests/fixtures/ocr_items.json` 성공
  QA scenarios:
  ```
  Scenario: 실측 실행
  Tool: `python3 croll.py` (또는 .venv312/bin/python croll.py)
  Steps: wheel 점검 → 설치 → 실행 → 산출물 확인
  Expected: 종료코드 0, "[5] 결과 저장" 로그 존재, ocr_debug.json 생성, daily_menus 5일
  Evidence: .omo/evidence/task-5-crawler-accuracy-fix.txt

  Scenario: 실패 - 네트워크/사이트 구조 변경
  Tool: `python3 croll.py`
  Steps: 실행이 Exception으로 종료하는 경우 1회 재시도
  Expected: 재시도도 실패하면 BLOCKED: <reason> 보고 (계획 무시하고 진행 금지)
  Evidence: .omo/evidence/task-5-crawler-accuracy-fix-error.txt
  ```
  Commit: YES | `chore(data): add live OCR fixture for regression tests` | Files: [tests/fixtures/ocr_items.json]

- [x] 6. 픽스처 기반 통합 회귀 테스트 - 5일 복원 + 오염 토큰 0건
  What to do:
  - `tests/test_parse_daily_menus.py`에 통합 테스트 추가: `tests/fixtures/ocr_items.json`을 로드해 **period와 year를 픽스처에서 읽어 사용(Metis E5)** — period는 `d["period"]`, year는 `d["post_date"][:4]`에서 추출. 하드코딩 금지.
  - 모든 이미지의 items를 합친 뒤 `parse_daily_menus(items, period, year=year)` 실행.
  - 단정:
    (a) daily_menus 키가 정확히 5개 ("2026-10-12 (월)" ~ "2026-10-16 (금)")
    (b) 모든 날짜의 모든 코스 아이템에 정규식 `^\(?[월화수목금토일]\)?$` 및 `\d{1,2}월\d{1,2}일` 매칭 0건 (날짜/요일 토큰 오염 없음)
    (c) 각 날짜의 A코스 아이템 수 1~15 범위 (비현실적 흡수 감지)
    (d) 월~금 각 날짜의 코스 아이템 총합 >= 5 (빈 날짜 없음)
  - 실패 시: 실패 케이스의 아이템 좌표를 evidence에 기록하고 T1/T2로 돌아갈 원인 후보를 로그로 남길 것(자동 수정 시도 금지, 보고 후 계획 갱신).
  - **운영 후속 확인 사항(Metis D3)**: 커밋 반영 후 다음 CI 크론 실행의 `chore(auto)` 커밋에서 menu.json daily_menus 5일 키를 확인할 것 — 이 확인은 CI 워크플로우를 트리거/수정하지 않고 사람이 확인하는 후속 단계로 계획 완료 보고에 명시.
  Must NOT do: 픽스처 파일 수정으로 테스트를 통과시키는 행위 금지. 기대값을 실제 결과에 맞춰 느슨하게 완화 금지(단정 완화는 계획 갱신 사항).
  Parallelization: Can parallel: NO | Wave 4 | Blocks: [] | Blocked by: [2, 4, 5]
  References (executor has NO interview context - be exhaustive):
  - Data: `tests/fixtures/ocr_items.json` - T5에서 확보한 실측 좌표(단일 진실 원본). period/post_date 필드는 T3 스키마에서 옴.
  - Data: `meal_output/menu_2026-10-13.json:6-9` - 과거 오염 사례("10월12일", "(월)" 유입) - 회귀 감지 대상
  - Pattern: `croll.py:712` - parse_daily_menus 최종 시그니처(ocr_items, period_str, year)
  Acceptance criteria (agent-executable):
  - [ ] `python3 -m pytest tests/ -q` 전부 PASS
  - [ ] `python3 -m pytest tests/ -q --tb=short` 출력에 "7 passed" 이상 존재 (T1 4개 + T2 3개 + T3/T4/T6 테스트 합산)
  QA scenarios:
  ```
  Scenario: 회귀 감지 - 과거 버그 재현 차단
  Tool: `python3 -m pytest tests/test_parse_daily_menus.py -q -k fixture`
  Steps: 실측 픽스처로 통합 테스트 실행
  Expected: (a)~(d) 단정 모두 PASS. 특히 5일 키 존재 + 오염 토큰 0건
  Evidence: .omo/evidence/task-6-crawler-accuracy-fix.txt

  Scenario: 실패 - 오염 토큰 재유입
  Tool: `python3 -m pytest tests/test_parse_daily_menus.py -q -k fixture`
  Steps: 단정 (b) 실패 시 실패 아이템 dump 확인
  Expected: 실패 시 좌표 evidence가 남고, 테스트는 FAIL로 보고됨 (숨김 금지)
  Evidence: .omo/evidence/task-6-crawler-accuracy-fix-error.txt
  ```
  Commit: YES | `test(crawler): live-fixture regression for 5-day grid restore` | Files: [tests/test_parse_daily_menus.py]

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [x] F1. Plan compliance audit
  - 모든 `- [ ] N.` 행이 `## Todos` 섹션에 컬럼-0으로 존재하고, `- [ ] F<n>.` 행이 `## Final verification wave`에 존재하는지, 참조 경로가 실제 파일/라인과 일치하는지 감사. Tool: `grep -nE "^- \[ \] [0-9F]" .omo/plans/crawler-accuracy-fix.md` + 파일 대조. Evidence: .omo/evidence/f1-compliance.txt
- [x] F2. Code quality review
  - croll.py/main.py 변경부 리뷰: 함수 분리(순수함수 _normalize_ocr_text/_is_fresh/build_ocr_debug), 기존 코드 스타일(한글 주석, 4-space) 일관성, requirements.txt에 불필요한 의존성 추가 없음(pytest는 requirements-dev.txt에만). Tool: `python3 -m py_compile croll.py main.py` + diff 리뷰. Evidence: .omo/evidence/f2-quality.txt
- [x] F3. Real manual QA
  - 실제 서빙 검증: `python3 croll.py` 실행 → `meal_output/menu.json` 5일 키 확인 → `uvicorn main:app --port 8000` 기동 후 `curl -s localhost:8000/meal | python3 -m json.tool`로 daily_menus 5일 반환 확인 → 서버 종료. Evidence: .omo/evidence/f3-qa.txt
- [x] F4. Scope fidelity
  - Must-NOT-have 위반 검사: vercel.json/.github 워크플로우 diff 없음, OCR 엔진 교체 없음(`grep -n "PaddleOCR(" croll.py` 초기화 파라미터 동일), 게시물 선정 로직 diff 없음, 응답 스키마 필드 삭제 없음. **diff 검사는 meal_output/와 .omo/ 경로를 제외하고 수행(Metis E4)**. Tool: `git diff --stat -- . ':!meal_output' ':!.omo'` + grep. Evidence: .omo/evidence/f4-scope.txt

## Commit strategy
- One logical change per commit. Conventional Commits (`<type>(<scope>): <subject>`).
- 코드 커밋(fix/feat/test)과 데이터 커밋(chore(data): fixtures) 분리 - 기존 자동 커밋 히스토리(chore(auto): update meal menu data)와 충돌하지 않게 코드는 feat/fix 접두사 사용.
- **meal_output/ 노이즈 처리(Metis E4)**: T5 실측이 menu.json/menu.txt/menu_1.jpg/menu_2026-10-*.json을 변경·추가하지만, 이 산출물은 기존 CI 봇(chore(auto))의 관할이므로 이 계획의 커밋에 의도적으로 포함하지 않고 워킹트리에 남겨둠. F4 diff 검사에서도 제외. tests/fixtures/ocr_items.json만 test/data 커밋에 포함.
- 마지막 커밋 푸터에 계획 파일 참조: `Plan: .omo/plans/crawler-accuracy-fix.md`.

## Success criteria
- `python3 -m pytest tests/ -q` 전부 PASS (paddleocr 미설치 환경에서도 단위 테스트는 T1 이후 즉시 통과 — guarded import)
- 실측 크롤링 결과 daily_menus가 주간 5일 전부 포함하고, 날짜/요일/괄호 토큰 오염 0건
- `/meal`이 7일 초과 stale 데이터에 대해 자동 재크롤링을 시도하고, 실패 시 stale 데이터로 폴백(서버리스에서는 fail-fast 폴백이 설계 동작)
- `meal_output/ocr_debug.json`이 매 실행 생성되어 향후 회귀 분석 가능
- (후속 사람 확인) 다음 CI 크론 자동 커밋의 menu.json이 5일 키를 포함
