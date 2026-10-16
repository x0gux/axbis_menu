"""parse_daily_menus 및 날짜/토큰 헬퍼 단위 테스트.

paddleocr 미설치 환경에서도 실행 가능해야 한다.
croll.py의 PaddleOCR import는 guarded 되어 있으므로
순수 파싱 함수만 import해서 테스트한다.
"""

from croll import (
    _find_date_line,
    _is_weekday_token,
    _normalize_ocr_text,
    parse_daily_menus,
)


# ------------------------------------------------------------
# (a) OCR 공백 오차가 있는 날짜 정규화 + 파싱
# ------------------------------------------------------------

def test_find_date_line_with_ocr_spacing_errors():
    # '10 월1 2 일 (월)' → 정규화 후 '10월12일 (월)' → (10, 12, '월')
    assert _find_date_line("10 월1 2 일 (월)") == (10, 12, "월")


# ------------------------------------------------------------
# (b) 요일 없는 날짜 → 날짜에서 요일 도출
# ------------------------------------------------------------

def test_date_without_weekday_derives_weekday_from_date():
    items = [
        # 요일 없는 날짜 (2026-10-12 = 월요일)
        {"text": "10월12일", "x": 100, "y": 0, "x1": 100, "x2": 150, "text_len": 6},
        {"text": "A코스", "x": 30, "y": 50, "x1": 30, "x2": 60, "text_len": 3},
        {"text": "흑미밥", "x": 100, "y": 100, "x1": 100, "x2": 140, "text_len": 3},
    ]
    result = parse_daily_menus(items)

    assert "2026-10-12 (월)" in result
    assert result["2026-10-12 (월)"]["weekday"] == "월"
    assert result["2026-10-12 (월)"]["courses"]["A코스"] == ["흑미밥"]


# ------------------------------------------------------------
# (c) 괄호 요일 토큰 '(화)'가 메뉴로 유입되지 않음
# ------------------------------------------------------------

def test_weekday_token_excluded_from_menu_items():
    items = [
        {"text": "10월13일 (화)", "x": 100, "y": 0, "x1": 100, "x2": 170, "text_len": 10},
        {"text": "A코스", "x": 30, "y": 50, "x1": 30, "x2": 60, "text_len": 3},
        # 날짜/요일 토큰이 분리되어 떨어져 나온 경우 (과거 오염 사례)
        {"text": "(화)", "x": 110, "y": 100, "x1": 110, "x2": 130, "text_len": 3},
        {"text": "콩나물국", "x": 100, "y": 120, "x1": 100, "x2": 150, "text_len": 4},
    ]
    result = parse_daily_menus(items)

    assert "2026-10-13 (화)" in result
    a_course = result["2026-10-13 (화)"]["courses"]["A코스"]
    assert a_course == ["콩나물국"]
    assert "(화)" not in a_course


# ------------------------------------------------------------
# (d) 병합 박스 다중 날짜 → 서로 다른 x로 보간, 열 분리
# ------------------------------------------------------------

def test_merged_box_multiple_dates_get_distinct_ordered_x():
    items = [
        # 하나의 OCR 박스에 두 날짜가 병합된 경우 (x1=100, x2=300)
        {
            "text": "10월12일 (월) 10월13일(화)",
            "x": 200, "y": 0, "x1": 100, "x2": 300, "text_len": 19,
        },
        {"text": "A코스", "x": 30, "y": 50, "x1": 30, "x2": 60, "text_len": 3},
        # 앞쪽 날짜 열에 가까운 메뉴
        {"text": "흑미밥", "x": 150, "y": 100, "x1": 150, "x2": 190, "text_len": 3},
        # 뒤쪽 날짜 열에 가까운 메뉴
        {"text": "제육볶음", "x": 250, "y": 100, "x1": 250, "x2": 290, "text_len": 4},
    ]
    result = parse_daily_menus(items)

    # 두 날짜가 모두 열로 생성되어야 한다
    assert "2026-10-12 (월)" in result
    assert "2026-10-13 (화)" in result

    # x 보간이 서로 다른 위치를 가리켜 메뉴가 올바른 열로 배정된다
    courses_12 = result["2026-10-12 (월)"]["courses"]["A코스"]
    courses_13 = result["2026-10-13 (화)"]["courses"]["A코스"]
    assert "흑미밥" in courses_12
    assert "흑미밥" not in courses_13
    assert "제육볶음" in courses_13
    assert "제육볶음" not in courses_12


# ------------------------------------------------------------
# 헬퍼 보조 검증
# ------------------------------------------------------------

def test_normalize_ocr_text_collapses_spacing():
    assert _normalize_ocr_text("1 0 월 1 2 일") == "10월12일"
    assert _normalize_ocr_text("（월）") == "(월)"


def test_is_weekday_token():
    assert _is_weekday_token("(월)")
    assert _is_weekday_token("화")
    assert not _is_weekday_token("10월12일")
    assert not _is_weekday_token("콩나물국")
