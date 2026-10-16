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


def test_is_weekday_token_with_yoil_suffix():
    """'요일' 접미사 토큰도 메뉴로 유입되면 안 된다 (목요일에 '금요일' 유입 사례)."""
    assert _is_weekday_token("금요일")
    assert _is_weekday_token("(금요일)")
    assert _is_weekday_token("월요일")
    assert not _is_weekday_token("감자탕")
    assert not _is_weekday_token("매운미트볼조림")


def test_date_with_yoil_suffix_consumed_as_date_not_menu():
    """'10월16일 (금요일)' 형태는 날짜로 소비되고 메뉴로 유입되지 않는다."""
    items = [
        {
            "text": "10월16일 (금요일)",
            "x": 450, "y": 0, "x1": 430, "x2": 470, "text_len": 12,
        },
        {"text": "A코스", "x": 30, "y": 50, "x1": 30, "x2": 60, "text_len": 3},
        {"text": "부추무침", "x": 450, "y": 100, "x1": 450, "x2": 490, "text_len": 4},
    ]
    result = parse_daily_menus(items, period_str="26.10.12~10.16")

    assert "2026-10-16 (금)" in result
    a_course = result["2026-10-16 (금)"]["courses"]["A코스"]
    assert a_course == ["부추무침"]
    assert not any("10월16일" in it or "금요일" in it for it in a_course)


# ------------------------------------------------------------
# (T3) OCR 디버그 페이로드 빌더
# ------------------------------------------------------------

def test_build_ocr_debug_structure():
    from croll import build_ocr_debug

    post = {
        "title": "구내식 메뉴(26.10.12~16)",
        "date": "2026-10-12",
    }
    images = [
        {
            "url": "https://example.com/menu.jpg",
            "items": [
                {"text": "흑미밥", "x": 1.0, "y": 2.0,
                 "x1": 0.0, "x2": 2.0, "text_len": 3},
            ],
        },
    ]

    payload = build_ocr_debug(post, images, period_str="26.10.12~10.16")

    assert payload["post_title"] == "구내식 메뉴(26.10.12~16)"
    assert payload["post_date"] == "2026-10-12"
    assert payload["period"] == "26.10.12~10.16"
    assert payload["images"][0]["url"] == "https://example.com/menu.jpg"
    assert payload["images"][0]["items"][0]["text"] == "흑미밥"
    assert "captured_at" in payload


def test_build_ocr_debug_defaults():
    from croll import build_ocr_debug

    payload = build_ocr_debug({}, [])

    assert payload["post_title"] == ""
    assert payload["period"] == ""
    assert payload["images"] == []


# ------------------------------------------------------------
# (T6) 실측 픽스처 통합 회귀 테스트: 5일 복원 + 오염 토큰 0건
# 픽스처는 T5 실측 크롤링(meal_output/ocr_debug.json)에서 복사된다.
# ------------------------------------------------------------

import json
import os
import re

import pytest

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "ocr_items.json"
)


def _load_fixture_items():
    if not os.path.exists(FIXTURE_PATH):
        pytest.skip("tests/fixtures/ocr_items.json 없음 - T5 실측 크롤링 선행 필요")

    with open(FIXTURE_PATH, encoding="utf-8") as f:
        fixture = json.load(f)

    period = fixture.get("period", "")
    post_date = fixture.get("post_date", "")
    year = int(post_date[:4]) if post_date[:4].isdigit() else None

    items = []
    for img in fixture.get("images", []):
        items.extend(img.get("items", []))

    return items, period, year


_DATE_TOKEN_RE = re.compile(r"\d{1,2}월\d{1,2}일")
_WEEKDAY_TOKEN_RE = re.compile(r"^\(?[월화수목금토일]\)?$")


def test_live_fixture_restores_full_week():
    """과거 결함 회귀 감지: 주간 5일이 모두 날짜별로 생성되어야 한다."""
    items, period, year = _load_fixture_items()

    daily_menus = parse_daily_menus(items, period, year=year)

    assert len(daily_menus) == 5, f"일자 수 이상: {sorted(daily_menus.keys())}"


def test_live_fixture_no_contamination_tokens():
    """과거 결함 회귀 감지: 날짜/요일 토큰이 메뉴로 유입되지 않아야 한다."""
    items, period, year = _load_fixture_items()

    daily_menus = parse_daily_menus(items, period, year=year)

    for date_key, menu in daily_menus.items():
        for course, names in menu["courses"].items():
            for name in names:
                assert not _DATE_TOKEN_RE.search(
                    name
                ), f"{date_key} 날짜 토큰 오염: {name!r}"
                assert not _WEEKDAY_TOKEN_RE.match(
                    name
                ), f"{date_key} 요일 토큰 오염: {name!r}"


def test_live_fixture_reasonable_course_sizes():
    """비현실적인 흡수 감지: A코스 아이템 수 1~15 범위."""
    items, period, year = _load_fixture_items()

    daily_menus = parse_daily_menus(items, period, year=year)

    for date_key, menu in daily_menus.items():
        a_course = menu["courses"].get("A코스", [])
        assert 1 <= len(
            a_course
        ) <= 15, f"{date_key} A코스 아이템 수 이상: {len(a_course)} ({a_course})"


def test_live_fixture_no_empty_days():
    """빈 날짜 없음: 각 날짜의 코스 아이템 총합 5 이상."""
    items, period, year = _load_fixture_items()

    daily_menus = parse_daily_menus(items, period, year=year)

    for date_key, menu in daily_menus.items():
        total = sum(len(v) for v in menu["courses"].values())
        assert total >= 5, f"{date_key} 아이템 과소: {total}"


# ------------------------------------------------------------
# (T2) fallback: 요일 헤더 5개 + 날짜 앵커 2개 → 5열 복원
# ------------------------------------------------------------

def test_fallback_restores_missing_columns_from_headers_and_period():
    items = [
        # 요일 헤더 병합 박스 (x1=0, x2=500, MON~FRI)
        {
            "text": "MON TUE WED THU FRI",
            "x": 250, "y": -10, "x1": 0, "x2": 500, "text_len": 19,
        },
        # 감지된 날짜 앵커: 화(10-13), 금(10-16)
        {"text": "10월13일 (화)", "x": 150, "y": 0, "x1": 130, "x2": 170, "text_len": 10},
        {"text": "10월16일 (금)", "x": 450, "y": 0, "x1": 430, "x2": 470, "text_len": 10},
        {"text": "A코스", "x": 30, "y": 50, "x1": 30, "x2": 60, "text_len": 3},
        {"text": "흑미밥", "x": 150, "y": 100, "x1": 150, "x2": 190, "text_len": 3},
    ]
    result = parse_daily_menus(items, period_str="26.10.12~10.16")

    # 주간 5일이 모두 복원되어야 한다
    expected_keys = {
        "2026-10-12 (월)",
        "2026-10-13 (화)",
        "2026-10-14 (수)",
        "2026-10-15 (목)",
        "2026-10-16 (금)",
    }
    assert set(result.keys()) == expected_keys

    # 기존 앵커의 메뉴 배정은 불변
    assert result["2026-10-13 (화)"]["courses"]["A코스"] == ["흑미밥"]


# ------------------------------------------------------------
# (T2) fallback: 앵커 2개 + period → 누락 3열 선형 보간 복원
# ------------------------------------------------------------

def test_fallback_interpolates_missing_columns_from_period():
    items = [
        # 헤더 없이 날짜 앵커 2개만 존재 (13일, 16일)
        {"text": "10월13일 (화)", "x": 150, "y": 0, "x1": 130, "x2": 170, "text_len": 10},
        {"text": "10월16일 (금)", "x": 450, "y": 0, "x1": 430, "x2": 470, "text_len": 10},
        {"text": "A코스", "x": 30, "y": 50, "x1": 30, "x2": 60, "text_len": 3},
    ]
    result = parse_daily_menus(items, period_str="26.10.12~10.16")

    expected_keys = {
        "2026-10-12 (월)",
        "2026-10-13 (화)",
        "2026-10-14 (수)",
        "2026-10-15 (목)",
        "2026-10-16 (금)",
    }
    assert set(result.keys()) == expected_keys
    # 기존 앵커는 불변
    assert result["2026-10-13 (화)"]["date"] == "2026-10-13"
    assert result["2026-10-16 (금)"]["date"] == "2026-10-16"


# ------------------------------------------------------------
# (T2) 중간점 열 경계 배정
# ------------------------------------------------------------

def test_midpoint_column_boundary_assignment():
    items = [
        {"text": "10월13일 (화)", "x": 100, "y": 0, "x1": 80, "x2": 120, "text_len": 10},
        {"text": "10월16일 (금)", "x": 300, "y": 0, "x1": 280, "x2": 320, "text_len": 10},
        {"text": "A코스", "x": 30, "y": 50, "x1": 30, "x2": 60, "text_len": 3},
        # 경계(중간점 200) 좌우에 위치한 메뉴
        {"text": "흑미밥", "x": 190, "y": 100, "x1": 190, "x2": 230, "text_len": 3},
        {"text": "제육볶음", "x": 210, "y": 100, "x1": 210, "x2": 250, "text_len": 4},
    ]
    # period를 주지 않아 fallback 없이 2열만 사용
    result = parse_daily_menus(items)

    assert set(result.keys()) == {"2026-10-13 (화)", "2026-10-16 (금)"}
    assert result["2026-10-13 (화)"]["courses"]["A코스"] == ["흑미밥"]
    assert result["2026-10-16 (금)"]["courses"]["A코스"] == ["제육볶음"]


# ------------------------------------------------------------
# (T2) period 파서
# ------------------------------------------------------------

def test_parse_period_dates():
    from croll import _parse_period_dates
    import datetime as dt

    start, end = _parse_period_dates("26.10.12~10.16")
    assert start == dt.date(2026, 10, 12)
    assert end == dt.date(2026, 10, 16)

    start, end = _parse_period_dates("2026.10.12~2026.10.16")
    assert start == dt.date(2026, 10, 12)
    assert end == dt.date(2026, 10, 16)

    start, end = _parse_period_dates("")
    assert start is None and end is None
