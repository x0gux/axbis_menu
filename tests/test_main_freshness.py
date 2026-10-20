"""main.py 신선도 판정(_is_fresh) 및 /meal 재크롤링 경로 테스트.

croll은 sys.modules 스텁으로 대체하므로 paddleocr 미설치에서도 실행 가능하다.
"""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

import main


TODAY = date(2026, 10, 16)


# ------------------------------------------------------------
# _is_fresh 순수 함수 테스트 (today 주입으로 실제 값 단정)
# ------------------------------------------------------------

def test_is_fresh_today():
    assert main._is_fresh("2026-10-16", today=TODAY) is True


def test_is_fresh_eight_days_ago_is_stale():
    assert main._is_fresh("2026-10-08", today=TODAY) is False


def test_is_fresh_boundary_seven_days_is_fresh():
    assert main._is_fresh("2026-10-09", today=TODAY) is True


def test_is_fresh_invalid_format_is_not_fresh():
    assert main._is_fresh("abc", today=TODAY) is False


def test_is_fresh_none_or_missing_is_not_fresh():
    assert main._is_fresh(None, today=TODAY) is False
    assert main._is_fresh("", today=TODAY) is False


# ------------------------------------------------------------
# /meal 재크롤링 경로 (monkeypatch + sys.modules 스텁)
# ------------------------------------------------------------

class _FakeCroll:
    """croll.main()을 대체하는 스텁. 호출 횟수를 기록한다."""

    def __init__(self, payload, fail=False):
        self.payload = payload
        self.fail = fail
        self.calls = 0

    def main(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("crawl failed")
        with open(
            os.path.join(main.OUTPUT_DIR, "menu.json"),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(self.payload, f, ensure_ascii=False)


def _write_menu(payload):
    os.makedirs(main.OUTPUT_DIR, exist_ok=True)
    with open(
        os.path.join(main.OUTPUT_DIR, "menu.json"),
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(payload, f, ensure_ascii=False)


def test_meal_recrawls_stale_menu_and_returns_fresh(monkeypatch, tmp_path):
    # OUTPUT_DIR을 tmp로 격리하고 stale menu.json을 준비
    monkeypatch.setattr(main, "OUTPUT_DIR", str(tmp_path))
    stale_payload = {
        "post": {"date": "2026-10-01", "title": "old"},
        "daily_menus": {"old-key": {}},
    }
    _write_menu(stale_payload)

    fresh_payload = {
        "post": {"date": date.today().isoformat(), "title": "new"},
        "daily_menus": {"2026-10-16 (금)": {}},
    }
    fake = _FakeCroll(fresh_payload)
    monkeypatch.setitem(sys.modules, "croll", fake)

    result = main.meal()

    # 재크롤링이 1회 호출되고 갱신된 데이터가 반환된다
    assert fake.calls == 1
    assert "2026-10-16 (금)" in result["daily_menus"]
    assert "old-key" not in result["daily_menus"]


def test_meal_crawl_failure_falls_back_to_stale(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "OUTPUT_DIR", str(tmp_path))
    stale_payload = {
        "post": {"date": "2026-10-01", "title": "old"},
        "daily_menus": {"old-key": {}},
    }
    _write_menu(stale_payload)

    fake = _FakeCroll(None, fail=True)
    monkeypatch.setitem(sys.modules, "croll", fake)

    # 예외가 밖으로 새지 않고 stale 데이터를 반환한다 (500 없음)
    result = main.meal()

    assert fake.calls == 1
    assert "old-key" in result["daily_menus"]


# ------------------------------------------------------------
# /meal/refresh 강제 갱신 경로 (프론트 수동 갱신 버튼용)
# ------------------------------------------------------------

def test_meal_refresh_forces_crawl_even_when_fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "OUTPUT_DIR", str(tmp_path))
    # 데이터가 신선해도(force 조건 없음) 크롤링이 실행되어야 한다
    fresh_payload = {
        "post": {"date": date.today().isoformat(), "title": "new"},
        "daily_menus": {"2026-10-16 (금)": {}},
    }
    _write_menu(fresh_payload)

    updated_payload = {
        "post": {"date": date.today().isoformat(), "title": "updated"},
        "daily_menus": {"2026-10-20 (화)": {}},
    }
    fake = _FakeCroll(updated_payload)
    monkeypatch.setitem(sys.modules, "croll", fake)

    result = main.meal_refresh()

    assert fake.calls == 1
    assert result["refreshed"] is True
    assert "2026-10-20 (화)" in result["data"]["daily_menus"]


def test_meal_refresh_failure_falls_back_to_stale(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "OUTPUT_DIR", str(tmp_path))
    stale_payload = {
        "post": {"date": "2026-10-01", "title": "old"},
        "daily_menus": {"old-key": {}},
    }
    _write_menu(stale_payload)

    fake = _FakeCroll(None, fail=True)
    monkeypatch.setitem(sys.modules, "croll", fake)

    # 예외가 밖으로 새지 않고 stale 데이터와 실패 표시를 반환한다
    result = main.meal_refresh()

    assert fake.calls == 1
    assert result["refreshed"] is False
    assert "error" in result
    assert "old-key" in result["data"]["daily_menus"]


def test_meal_refresh_failure_without_existing_data(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "OUTPUT_DIR", str(tmp_path))

    fake = _FakeCroll(None, fail=True)
    monkeypatch.setitem(sys.modules, "croll", fake)

    result = main.meal_refresh()

    assert fake.calls == 1
    assert result["refreshed"] is False
    assert "error" in result
    assert "data" not in result


def test_meal_refresh_skips_crawl_within_cooldown(monkeypatch, tmp_path):
    """마지막 성공 크롤링이 쿨다운 이내면 크롤링 없이 현재 데이터를 반환한다."""
    monkeypatch.setattr(main, "OUTPUT_DIR", str(tmp_path))
    payload = {
        "post": {"date": date.today().isoformat(), "title": "recent"},
        "daily_menus": {"2026-10-16 (금)": {}},
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_menu(payload)

    fake = _FakeCroll(payload)
    monkeypatch.setitem(sys.modules, "croll", fake)

    result = main.meal_refresh()

    # 크롤링이 호출되지 않고 성공으로 처리된다 (남용 방지)
    assert fake.calls == 0
    assert result["refreshed"] is True
    assert "message" in result
    assert "2026-10-16 (금)" in result["data"]["daily_menus"]


def test_meal_refresh_after_cooldown_crawls(monkeypatch, tmp_path):
    """captured_at이 쿨다운보다 오래되었으면 다시 크롤링한다."""
    monkeypatch.setattr(main, "OUTPUT_DIR", str(tmp_path))
    old_captured = datetime.now(timezone.utc) - timedelta(
        seconds=main.CRAWL_COOLDOWN_SECONDS + 1
    )
    payload = {
        "post": {"date": "2026-10-01", "title": "old"},
        "daily_menus": {"old-key": {}},
        "captured_at": old_captured.isoformat(),
    }
    _write_menu(payload)

    fresh_payload = {
        "post": {"date": date.today().isoformat(), "title": "new"},
        "daily_menus": {"2026-10-16 (금)": {}},
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    fake = _FakeCroll(fresh_payload)
    monkeypatch.setitem(sys.modules, "croll", fake)

    result = main.meal_refresh()

    assert fake.calls == 1
    assert result["refreshed"] is True


def test_meal_auto_recrawl_skipped_during_cooldown(monkeypatch, tmp_path):
    """/meal은 stale이어도 쿨다운 중이면 크롤링을 재시도하지 않는다."""
    monkeypatch.setattr(main, "OUTPUT_DIR", str(tmp_path))
    stale_payload = {
        "post": {"date": "2026-10-01", "title": "old"},
        "daily_menus": {"old-key": {}},
    }
    _write_menu(stale_payload)

    # 직전에 크롤링을 시도한 직후라고 가정
    main._touch_crawl_attempt()

    fake = _FakeCroll(None)
    monkeypatch.setitem(sys.modules, "croll", fake)

    result = main.meal()

    assert fake.calls == 0
    assert "old-key" in result["daily_menus"]


def test_meal_auto_recrawl_runs_after_cooldown(monkeypatch, tmp_path):
    """/meal은 stale + 쿨다운 경과 시 크롤링을 재시도한다."""
    monkeypatch.setattr(main, "OUTPUT_DIR", str(tmp_path))
    stale_payload = {
        "post": {"date": "2026-10-01", "title": "old"},
        "daily_menus": {"old-key": {}},
    }
    _write_menu(stale_payload)

    # 마커 파일을 쿨다운 이전 시각으로 조작
    marker = os.path.join(str(tmp_path), ".last_crawl_attempt")
    old = datetime.now(timezone.utc) - timedelta(
        seconds=main.CRAWL_COOLDOWN_SECONDS + 1
    )
    with open(marker, "w", encoding="utf-8") as f:
        f.write(old.isoformat())

    fresh_payload = {
        "post": {"date": date.today().isoformat(), "title": "new"},
        "daily_menus": {"2026-10-16 (금)": {}},
    }
    fake = _FakeCroll(fresh_payload)
    monkeypatch.setitem(sys.modules, "croll", fake)

    result = main.meal()

    assert fake.calls == 1
    assert "2026-10-16 (금)" in result["daily_menus"]


# ------------------------------------------------------------
# FastAPI 라우트 레벨 테스트 (TestClient)
# ------------------------------------------------------------

def test_meal_route_returns_fresh_data(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(main, "OUTPUT_DIR", str(tmp_path))
    payload = {
        "post": {"date": date.today().isoformat(), "title": "new"},
        "daily_menus": {"2026-10-16 (금)": {"courses": {}}},
    }
    _write_menu(payload)

    client = TestClient(main.app)
    response = client.get("/meal")

    assert response.status_code == 200
    assert "2026-10-16 (금)" in response.json()["daily_menus"]


def test_meal_refresh_route_contract(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(main, "OUTPUT_DIR", str(tmp_path))
    fresh_payload = {
        "post": {"date": date.today().isoformat(), "title": "new"},
        "daily_menus": {"2026-10-16 (금)": {"courses": {}}},
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_menu(fresh_payload)

    client = TestClient(main.app)
    response = client.post("/meal/refresh")

    # 쿨다운 이내 → 크롤링 없이 성공 응답
    assert response.status_code == 200
    body = response.json()
    assert body["refreshed"] is True
    assert "message" in body
    assert "data" in body
