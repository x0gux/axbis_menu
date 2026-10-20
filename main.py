# pyrefly: ignore [missing-import]
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import date, datetime, timezone
import json
import os
import tempfile

app = FastAPI()

# 프론트엔드(브라우저)에서 백엔드 API를 직접 호출할 수 있도록 CORS 허용.
# 읽기 전용 공개 API이므로 전체 오리진을 허용한다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "meal_output")

# menu.json의 게시물 '작성일' 기준 신선도 임계값(일).
# 게시물이 메뉴 주간 시작 전에 올라오는 경우 조기 stale 처리되지만
# 과잉 크롤링 방향이라 안전하다.
REFRESH_DAYS = 7

# 크롤링 쿨다운(초). 크롤링은 고비용 작업(OCR, 최대 60초)이라
# 짧은 시간 안에 반복 트리거되는 것을 막는다.
# - /meal 자동 재크롤링: 마지막 '시도' 기준 (실패 반복 시 요청마다
#   크롤링이 몰리는 것을 방지)
# - /meal/refresh 수동 갱신: 마지막 '성공' 기준 (사용자 의도를 존중해
#   실패했으면 재시도를 허용)
CRAWL_COOLDOWN_SECONDS = 300


@app.get("/")
def root():
    return {"message": "yeah"}


def _is_fresh(post_date_str, today=None):
    """menu.json의 게시물 작성일이 REFRESH_DAYS 이내인지 판정한다.

    - post_date_str: "2026-10-12" 형식 (menu.json의 post.date)
    - None/빈 문자열/형식 오류는 not fresh로 간주한다(재크롤링 시도).
    """
    if not post_date_str:
        return False

    try:
        post_date = date.fromisoformat(str(post_date_str).strip())
    except (TypeError, ValueError):
        return False

    if today is None:
        today = date.today()

    return (today - post_date).days <= REFRESH_DAYS


def _load_weekly_menu():
    """menu.json 파일 전체(주간 메뉴)를 읽어 반환합니다."""
    json_path = os.path.join(OUTPUT_DIR, "menu.json")

    if not os.path.exists(json_path):
        return None

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _crawl_menu():
    """크롤러를 실행해 menu.json을 갱신한다. (로컬/개발 환경용 가용성 폴백)

    주의: Vercel 서버리스에서는 paddle 의존성이 번들되지 않고 60초 제한이
    있어 이 호출이 fail-fast로 실패할 수 있다. 이 경우 아래 /meal이 stale
    데이터를 반환하는 것이 설계된 동작이다. 운영 환경의 실제 신선도는 CI
    크론(.github/workflows/crawl_meal.yml, 평일 09:43 KST 자동 크롤링
    커밋)이 담당한다.
    """
    import croll

    _touch_crawl_attempt()
    croll.main()


# ------------------------------------------------------------
# 크롤링 쿨다운 (고비용 작업 반복 트리거 방지)
# ------------------------------------------------------------

def _crawl_marker_paths():
    """크롤링 시도 시각 마커 후보 경로. 읽기 전용 파일시스템(Vercel)에서는
    /tmp로 폴백한다."""
    return [
        os.path.join(OUTPUT_DIR, ".last_crawl_attempt"),
        os.path.join(tempfile.gettempdir(), "axbis_menu_last_crawl_attempt"),
    ]


def _touch_crawl_attempt():
    """크롤링 '시도' 시각을 기록한다."""
    stamp = datetime.now(timezone.utc).isoformat()
    for path in _crawl_marker_paths():
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(stamp)
            return
        except OSError:
            continue


def _last_crawl_attempt_at():
    """마지막 크롤링 '시도' 시각을 반환한다. 없으면 None."""
    for path in _crawl_marker_paths():
        try:
            with open(path, encoding="utf-8") as f:
                return datetime.fromisoformat(f.read().strip())
        except (OSError, ValueError):
            continue
    return None


def _is_crawl_on_cooldown():
    """마지막 시도가 쿨다운 이내인지 판정한다."""
    last = _last_crawl_attempt_at()
    if last is None:
        return False
    elapsed = (datetime.now(timezone.utc) - last).total_seconds()
    return elapsed < CRAWL_COOLDOWN_SECONDS


def _captured_at(menu_payload):
    """menu.json의 captured_at(마지막 '성공' 크롤링 시각)을 반환한다.

    구버전 menu.json(필드 없음)은 None - 쿨다운 없이 동작(하위 호환).
    """
    if not menu_payload:
        return None
    raw = menu_payload.get("captured_at")
    try:
        return datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


@app.post("/meal/refresh")
def meal_refresh():
    """신선도 조건 없이 강제로 크롤링을 실행한다.

    프론트엔드(axbis_lunch)의 수동 갱신 버튼에서 호출된다.
    /meal과 동일하게 크롤링 실패 시 기존(stale) 데이터가 있으면
    그것을 반환한다(가용성 우선). refreshed 필드로 성공 여부를 알린다.

    남용 방지: 마지막 '성공' 크롤링이 쿨다운 이내면 크롤링을 건너뛰고
    현재 데이터를 즉시 반환한다. 실패한 시도는 쿨다운을 만들지 않아
    사용자가 곧바로 재시도할 수 있다.
    """
    result = _load_weekly_menu()

    captured = _captured_at(result)
    if captured is not None:
        elapsed = (datetime.now(timezone.utc) - captured).total_seconds()
        if elapsed < CRAWL_COOLDOWN_SECONDS and result:
            return {
                "refreshed": True,
                "message": (
                    "최근에 갱신된 데이터입니다. "
                    f"{int(CRAWL_COOLDOWN_SECONDS - elapsed)}초 후 재크롤링 가능합니다."
                ),
                "data": result,
            }

    try:
        _crawl_menu()
    except Exception as e:
        # 재크롤링 실패 시: 기존 데이터가 있으면 그것과 함께 실패를 알림
        if result:
            return {
                "refreshed": False,
                "error": str(e),
                "data": result,
            }
        return {
            "refreshed": False,
            "error": f"메뉴가 없으며, 강제 크롤링을 실행할 수 없습니다: {e}",
        }

    # 크롤링 후 다시 전체 데이터 읽기
    fresh_result = _load_weekly_menu()
    if fresh_result:
        return {
            "refreshed": True,
            "data": fresh_result,
        }

    return {
        "refreshed": False,
        "error": "크롤링 후 메뉴를 찾을 수 없습니다.",
    }


@app.get("/meal")
def meal():
    # 1) 전체 주간 메뉴 데이터 확인
    result = _load_weekly_menu()

    # 2) 데이터가 존재하고 신선하면 그대로 반환
    if result and _is_fresh(result.get("post", {}).get("date")):
        return result

    # 3) 없거나 오래되었으면 크롤링 실행 (쿨다운 중이면 건너뛰고 stale 반환)
    if _is_crawl_on_cooldown():
        if result:
            return result
    else:
        try:
            _crawl_menu()
        except Exception as e:
            # 재크롤링 실패 시: 기존(stale) 데이터가 있으면 그것을 반환(가용성 우선)
            if result:
                return result
            return {
                "message": f"메뉴가 없으며, 자동 크롤링을 실행할 수 없습니다: {e}"
            }

    # 4) 크롤링 후 다시 전체 데이터 읽기
    fresh_result = _load_weekly_menu()
    if fresh_result:
        return fresh_result

    return {"message": "메뉴를 찾을 수 없습니다."}
