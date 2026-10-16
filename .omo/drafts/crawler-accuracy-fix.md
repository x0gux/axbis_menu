---
slug: crawler-accuracy-fix
status: awaiting-approval
intent: clear
review_required: false
pending-action: write .omo/plans/crawler-accuracy-fix.md
approach: 날짜 행/열 앵커 재설계 + 좌표 디버그 아티팩트 저장 + 오프라인 회귀 테스트 + (기본값) main.py 신선도 체크
---

# Draft: crawler-accuracy-fix

## Components (topology ledger)
<!-- id | outcome (one line) | status: active|deferred | evidence path -->

- C1 수집(게시물/이미지 다운로드) | 최신 구내식 게시물에서 메뉴 이미지를 안정적으로 확보 | active | croll.py:104-332
- C2 OCR 좌표 추출 | 이미지에서 (text, x, y) 아이템을 추출 | active | croll.py:408-506
- C3 격자 파싱(날짜×코스) | OCR 아이템을 날짜별/코스별 구조로 재구성 | active | croll.py:660-910
- C4 저장/API 제공 | menu.json / menu_YYYY-MM-DD.json 저장 및 /meal 서빙 | active | croll.py:917-1062, main.py:18-53

## Open assumptions (announced defaults)
<!-- assumption | adopted default | rationale | reversible? -->

- A1: main.py /meal 의 stale menu.json 무기한 서빙 문제도 이번 범위에 포함 | 포함 (게시물 작성일 기준 신선도 체크 + 재크롤링) | "크롤링의 단점"은 저장→서빙 파이프라인 전반이라고 판단 | YES
- A2: OCR 오인식(숭능/승능) 사전 기반 교정 | 범위 제외 (구조적 유입 차단만 수행) | 메뉴명 사전은 유지보수 불가능, 오탐 위험 | YES
- A3: QA는 실사이트 1회 실측 + 저장된 좌표 데이터 기반 오프라인 회귀 테스트 | 실측 포함 (권장) | 좌표 원본이 현재 저장되지 않아 회귀 픽스처가 존재하지 않음 → 실측이 픽스처를 만들어냄 | YES (사용자가 거부하면 오프라인만)

## Findings (cited - path:lines)

- F1 [치명] 주간 메뉴 5일 중 3일 누락: menu.json daily_menus = 2026-10-13(화), 2026-10-16(금)만 존재. 10-12/10-14/10-15 전부 미생성. 근거: meal_output/menu.json (dates 키 확인)
- F2 [치명] 인접 열 데이터 오염: 2026-10-13.json A코스에 "10월12일", "(월)", "10월14일", "(수)" 유입 → 미인식 열의 메뉴가 nearest_col으로 인접 열에 흡수됨. 근거: meal_output/menu_2026-10-13.json:6-9, croll.py:805-814 (nearest_col)
- F3 [원인] 날짜 행은 OCR상 온전히 존재: menu.json menu_text = '10월12일 (월) 10월13일(화) 10월14일 (수) 10월15일 (목) 10월16일(금)' — 5개 모두 인식됨. 그러나 개별 아이템 단계에서 _find_date_line(croll.py:660-676) 정규식이 3개를 놓침(아이템 분할/좌표 문제). "(월)" 괄호 요일 토큰은 어디서도 처리되지 않아 menu_items로 유입 (croll.py:743-792)
- F4 [원인] 열 배정이 center가 아닌 좌변 x 기준: rec_boxes에서 box[0], box[1]만 사용 (croll.py:477-489) → 박스 폭이 다른 날짜/메뉴 간 체계적 편향
- F5 [원인] 열 경계가 '가장 가까운 중심' 방식: 중간점 경계가 아니라 인접 날짜 중심 x에 가까운 쪽으로 전부 배정 (croll.py:805-814) → 중간 지대 텍스트가 잘못된 열로
- F6 [원인] 날짜 인식 실패 시 복구 경로 없음: 요일 헤더(MON~FRI)는 버려지고(croll.py:751-753), period 문자열로 열을 재구성하는 fallback 없음
- F7 [검증불가] OCR 원본 좌표 아이템을 저장하지 않음: menu.json에는 병합 라인만 저장 → 근본 원인을 아티팩트만으로 확정 불가, 회귀 테스트 픽스처 없음 (croll.py:928-934)
- F8 [부차] 연도 하드코드 기본값 2026 (croll.py:852) → 게시물 작성일 기반 도출 필요
- F9 [부차] main.py /meal 이 menu.json이 존재하기만 하면 영구 서빙 — 주차가 바뀌어도 갱신 안 됨 (main.py:18-37)
- F10 [환경] paddleocr/paddle 미설치 (로컬) → 실측 QA는 설치 필요. 테스트 인프라/CI 없음 (pyproject.toml:7-13, requirements.txt)
- F11 [환경] git clean, 자동 커밋 히스토리(chore(auto): update meal menu data) → 데이터 커밋과 코드 커밋 분리 필요

## Decisions (with rationale)

- D1: 날짜 행을 'y-클러스터 행' 단위로 먼저 식별하고, 행 내 아이템을 정규화 후 x순으로 열 앵커로 사용 — 아이템 분할/병합 모두 흡수
- D2: OCR 텍스트 정규화(숫자-월-일 사이 공백 제거, 괄호 통일) 후 날짜 매칭 — '10 월12일', '10월1 2일' 등 오차 흡수
- D3: 열 배정을 인접 열 중간점 경계 방식으로 교체, 박스 center 좌표 사용
- D4: 요일 헤더(MON~FRI) x좌표를 보조 앵커로 사용 + period에서 날짜 역산하는 fallback 추가 (우선순위: 날짜 앵커 > period 역산, 충돌 시 앵커 유지)
- D5: "(월)" 등 괄호 요일 토큰을 메뉴 후보에서 배제
- D6: run_ocr 원본 아이템을 meal_output/ocr_debug.json 으로 저장 (period 필드 포함). menu.json에는 넣지 않음(API 비대 방지 — Metis C1)
- D7: 오프라인 회귀 테스트(pytest)로 parse_daily_menus 검증 — paddleocr import 격리(guarded import)로 미설치에서도 실행
- D8 (Metis A1/A2 반영): PaddleOCR guarded import + main() 가드, pytest는 requirements-dev.txt로 분리
- D9 (Metis B1 반영): 병합 박스 다중 날짜는 문자 오프셋 비례 x 보간 (동일 x 금지)
- D10 (Metis C2 반영): main.py 재크롤링은 로컬 가용성 폴백이며 서버리스에서는 fail-fast→stale 폴백이 설계 동작. 운영 신선도는 CI 크론(crawl_meal.yml) 담당
- D11 (Metis D1 반영): 로컬 Python 3.14 wheel 미지원 시 Python 3.12 venv 폴백(CI 러너와 동일 버전)

## Metis review (folded in)

- 실행: 2026-10-16, general 서브에이전트(ses_ebc7a9393ffeASF0TQTCtHdcTq), verdict: CHANGES_REQUESTED
- BLOCKER 2건 반영: A1(paddleocr guarded import 부재 — 테스트 import 크래시) → T1 import 격리 추가. A2(pytest 미설치·미선언) → T1에 설치+requirements-dev.txt 추가
- MAJOR 반영: A3(요일 None → 날짜에서 도출), A4(T2/T3 동일 파일 병렬 금지 — 직렬화), B1(병합 박스 x 보간), C1(menu.json ocr_items 제외), C2(서버리스 한계 명시 + 폴백 테스트), E1(재크롤링 경로 monkeypatch 테스트), D1(3.12 venv 폴백)
- MINOR 반영: A5(T6 의존 행렬 정합), B2(fallback 우선순위), B3(.get 체이닝), C3(작성일 기준 신선도 명시), D2(아이템 수 게이트 완화), D3(CI 후속 확인 사항 기록), E2(5일 키 단정 T5 이동), E3(빌더 단위 테스트로 대체), E4(F4 diff 제외 경로), E5(픽스처에서 period/year 읽기)

## Scope IN

- croll.py: 날짜/열/코스 파싱 재설계, 좌표 center 보정, fallback 열 복구, OCR 디버그 저장, 연도 도출
- main.py: menu.json 신선도 체크(게시물 작성일 기준) 후 재크롤링
- 테스트: parse_daily_menus 등 순수함수 회귀 테스트 추가

## Scope OUT (Must NOT have)

- OCR 엔진 교체/추가, 메뉴명 사전 교정(오인식 텍스트 '수정')
- 크롤링 대상 사이트/게시물 선정 로직 변경(단, 최신성 체크는 IN)
- vercel.json / 배포 설정 변경
- 기존 menu_YYYY-MM-DD.json 아카이브 삭제/이관

## Open questions

- Q1 [소유자 결정] 실측 검증: paddleocr 설치 + 실사이트 1회 크롤링 실행을 계획에 포함할지 (권장: 포함). 미포함 시 기존 menu.json 라인 데이터로 제한적 검증만 가능
- Q2 [소유자 결정] 범위: croll.py 파싱만 vs 파싱+main.py 신선도 (권장: 후자, 가정 A1)
- Q3 [테스트 전략] 테스트 프레임워크: pytest 추가 vs 표준 unittest (권장: pytest — 의존성 1개, 관례적)

## Approval gate
status: awaiting-approval
<!-- 브리프 제시 후 사용자의 명시적 okay 대기 중 -->
