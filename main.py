# pyrefly: ignore [missing-import]
from fastapi import FastAPI
from datetime import datetime
import json
import os

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "meal_output")


@app.get("/")
def root():
    return {"message": "yeah"}


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


@app.get("/meal")
def meal():
    # 1) 전체 주간 메뉴 데이터 확인
    result = _load_weekly_menu()
    if result:
        return result

    # 2) 없으면 크롤링 실행
    try:
        import croll
        croll.main()
    except Exception as e:
        return {
            "message": f"메뉴가 없으며, 자동 크롤링을 실행할 수 없습니다: {e}"
        }

    # 3) 크롤링 후 다시 전체 데이터 읽기
    result = _load_weekly_menu()
    if result:
        return result

    return {"message": "메뉴를 찾을 수 없습니다."}
