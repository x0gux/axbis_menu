# pyrefly: ignore [missing-import]
from fastapi import FastAPI
from datetime import datetime
import json
import os

import croll

app = FastAPI()


@app.get("/")
def root():
    return {"message": "yeah"}


def _load_today_menu():
    """menu.json에서 오늘 날짜 메뉴를 찾아 반환.
    없으면 None."""
    json_path = os.path.join(croll.OUTPUT_DIR, "menu.json")

    if not os.path.exists(json_path):
        return None

    with open(json_path, "r", encoding="utf-8") as f:
        menu_data = json.load(f)

    today = datetime.today().strftime("%Y-%m-%d")
    daily_menus = menu_data.get("daily_menus", {})

    for date_key, menu in daily_menus.items():
        if menu["date"] == today:
            return {"date_key": date_key, **menu}

    return None


@app.get("/meal")
def meal():
    # 1) 기존 데이터에서 오늘 메뉴 찾기
    result = _load_today_menu()
    if result:
        return result

    # 2) 없으면 크롤링 실행
    try:
        croll.main()
    except Exception as e:
        return {"message": f"크롤링 실패: {e}"}

    # 3) 크롤링 후 다시 찾기
    result = _load_today_menu()
    if result:
        return result

    return {"message": f"{datetime.today().strftime('%Y-%m-%d')} 메뉴를 찾을 수 없습니다."}
