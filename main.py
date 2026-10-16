# pyrefly: ignore [missing-import]
from fastapi import FastAPI
from datetime import date
import json
import os

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "meal_output")

# menu.json의 게시물 '작성일' 기준 신선도 임계값(일).
# 게시물이 메뉴 주간 시작 전에 올라오는 경우 조기 stale 처리되지만
# 과잉 크롤링 방향이라 안전하다.
REFRESH_DAYS = 7


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
    croll.main()


@app.get("/meal")
def meal():
    # 1) 전체 주간 메뉴 데이터 확인
    result = _load_weekly_menu()

    # 2) 데이터가 존재하고 신선하면 그대로 반환
    if result and _is_fresh(result.get("post", {}).get("date")):
        return result

    # 3) 없거나 오래되었으면 크롤링 실행
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
