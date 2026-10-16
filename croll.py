# meal_crawler.py

import os
import re
import json
import datetime
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from io import BytesIO
from PIL import Image


# ============================================================
# PaddleOCR oneDNN 호환성 패치
# (paddlepaddle 3.3.x + Windows 환경에서 발생하는
#  ConvertPirAttribute2RuntimeAttribute 에러 우회)
# ============================================================

def _patch_paddle_onednn():
    """paddle.inference.create_predictor를 패치해서
    oneDNN/MKL-DNN을 비활성화한다."""
    try:
        import paddle.inference as pi

        _orig_create_predictor = pi.create_predictor

        def _patched_create_predictor(config):
            if hasattr(config, "disable_onednn"):
                config.disable_onednn()
            if hasattr(config, "disable_mkldnn"):
                config.disable_mkldnn()
            return _orig_create_predictor(config)

        pi.create_predictor = _patched_create_predictor

    except Exception:
        pass


_patch_paddle_onednn()

# pyrefly: ignore [missing-import]
try:
    from paddleocr import PaddleOCR
except Exception:
    # paddleocr 미설치 환경에서도 순수 파싱 함수들을 import해
    # 단위/회귀 테스트를 실행할 수 있도록 격리한다.
    PaddleOCR = None


# ============================================================
# 설정
# ============================================================

BASE_URL = "https://www.g5w.co.kr"
BOARD_URL = "https://www.g5w.co.kr/home/m_board.php?ps_db=b7"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "meal_output")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )
}

# 요일 키워드 → 정규화
DAY_KEYWORDS = {
    "MON": "월", "TUE": "화", "WED": "수",
    "THU": "목", "FRI": "금", "SAT": "토", "SUN": "일",
    "월": "월", "화": "화", "수": "수",
    "목": "목", "금": "금", "토": "토", "일": "일",
}


# ============================================================
# Session
# ============================================================

session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# 유틸
# ============================================================

def clean_text(text):
    """OCR/HTML 텍스트 정리"""
    if not text:
        return ""

    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# OCR 정규화용 전각 → 반각 치환 테이블
_FULLWIDTH_TRANS = str.maketrans({
    "（": "(",
    "）": ")",
    "　": " ",
})


def _normalize_ocr_text(text):
    """OCR 텍스트를 날짜/토큰 매칭에 적합한 정규형으로 변환한다.

    - 전각 괄호/공백 → 반각
    - 숫자와 월/일 사이 공백 제거 ('10 월 1 2 일' → '10월12일')
    - 다중 공백 축약
    """
    if not text:
        return ""

    text = text.translate(_FULLWIDTH_TRANS)
    text = re.sub(r"\s+", " ", text)
    # OCR이 숫자를 분리한 경우 접착 ('1 0' → '10')
    text = re.sub(r"(\d)\s+(?=\d)", r"\1", text)
    # 숫자와 월/일 경계의 공백 제거
    text = re.sub(r"(\d)\s*월", r"\1월", text)
    text = re.sub(r"월\s*(\d)", r"월\1", text)
    text = re.sub(r"(\d)\s*일", r"\1일", text)

    return text.strip()


# 날짜 정규식: MM월DD일 (요일) — 요일/괄호는 선택
_DATE_PATTERN = re.compile(
    r"(\d{1,2})\s*월\s*(\d{1,2})\s*일(?:\s*[\(（]?\s*([월화수목금토일])\s*[\)）])?"
)

# 요일 토큰 정규식: 괄호 요일 또는 단독 요일 한 글자
_WEEKDAY_TOKEN_PATTERN = re.compile(r"^[\(（]?[월화수목금토일][\)）]?$")

# 요일 헤더 정규식: MON ~ SUN 단어 경계 매칭
_DAY_HEADER_PATTERN = re.compile(
    r"\b(MON|TUE|WED|THU|FRI|SAT|SUN)\b"
)

_WEEKDAY_INDEX = {0: "월", 1: "화", 2: "수", 3: "목", 4: "금", 5: "토", 6: "일"}


def _weekday_from_date(year, month, day):
    """날짜가 유효하면 한글 요일을, 아니면 None을 반환한다."""
    try:
        return _WEEKDAY_INDEX[datetime.date(year, month, day).weekday()]
    except Exception:
        return None


def _parse_date_component(year_str, month_str, day_str):
    """'26'/'2026' 형식의 연도 문자열을 포함해 datetime.date로 변환한다."""
    try:
        y = int(year_str)
        if y < 100:
            y += 2000
        return datetime.date(y, int(month_str), int(day_str))
    except (TypeError, ValueError):
        return None


def _parse_period_dates(period_str):
    """period 문자열에서 (시작일, 종료일)을 datetime.date로 반환한다.

    예: '26.10.12~10.16' → (2026-10-12, 2026-10-16)
    종료일이 파싱되지 않으면 (시작일, None).
    """
    if not period_str:
        return None, None

    text = _normalize_ocr_text(period_str).replace(" ", "")

    start_match = re.search(r"(\d{2,4})[.\-](\d{1,2})[.\-](\d{1,2})", text)
    if not start_match:
        return None, None

    start = _parse_date_component(
        start_match.group(1),
        start_match.group(2),
        start_match.group(3),
    )
    if start is None:
        return None, None

    rest = text[start_match.end():]
    end_match = re.search(r"(?:(\d{2,4})[.\-])?(\d{1,2})[.\-](\d{1,2})", rest)
    if not end_match:
        return start, None

    if end_match.group(1):
        end = _parse_date_component(
            end_match.group(1),
            end_match.group(2),
            end_match.group(3),
        )
    else:
        # 연도 생략 시 시작일의 연도를 따른다
        end = _parse_date_component(
            str(start.year),
            end_match.group(2),
            end_match.group(3),
        )

    if end is not None and end < start:
        end = None

    return start, end


def make_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


# ============================================================
# 1. 게시판에서 최신 구내식 게시물 찾기
# ============================================================

def get_latest_meal_post():

    print("[1] 게시판 접속 중...")

    response = session.get(
        BOARD_URL,
        timeout=20
    )

    response.raise_for_status()

    # 한글 인코딩
    response.encoding = response.apparent_encoding

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    rows = soup.select(
        "#tb_board_list tbody tr"
    )

    if not rows:
        raise Exception(
            "게시판 목록을 찾지 못했습니다."
        )

    meal_posts = []

    for row in rows:

        num_elem = row.select_one(
            "td.tb_num"
        )

        title_elem = row.select_one(
            "td.tb_subject a"
        )

        date_elem = row.select_one(
            "td.tb_data"
        )

        views_elem = row.select_one(
            "td.tb_count"
        )

        if not num_elem or not title_elem:
            continue

        num = clean_text(
            num_elem.get_text()
        )

        title = clean_text(
            title_elem.get_text()
        )

        href = title_elem.get(
            "href",
            ""
        )

        link = urljoin(
            BOARD_URL,
            href
        )

        date = ""

        if date_elem:
            date = clean_text(
                date_elem.get_text()
            )

        views = ""

        if views_elem:
            views = clean_text(
                views_elem.get_text()
            )

        # 구내식 관련 게시물
        keywords = [
            "구내식",
            "식단",
            "메뉴"
        ]

        if any(
            keyword in title
            for keyword in keywords
        ):
            meal_posts.append({
                "num": num,
                "title": title,
                "link": link,
                "date": date,
                "views": views
            })

    if not meal_posts:
        raise Exception(
            "구내식/식단/메뉴 게시물을 찾지 못했습니다."
        )

    # 일반적으로 게시판은 최신순이므로 첫 번째
    latest = meal_posts[0]

    print()
    print("=" * 70)
    print("최신 구내식 게시물")
    print("=" * 70)

    print(
        f"번호   : {latest['num']}"
    )

    print(
        f"제목   : {latest['title']}"
    )

    print(
        f"작성일 : {latest['date']}"
    )

    print(
        f"조회수 : {latest['views']}"
    )

    print(
        f"링크   : {latest['link']}"
    )

    return latest


# ============================================================
# 2. 상세 페이지에서 메뉴 이미지 찾기
# ============================================================

def get_menu_images(post):

    print()
    print("[2] 상세 페이지 접속 중...")

    response = session.get(
        post["link"],
        timeout=20
    )

    response.raise_for_status()

    response.encoding = response.apparent_encoding

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    # 실제 사이트 구조
    content = soup.select_one(
        ".tb_body"
    )

    if not content:
        raise Exception(
            ".tb_body 영역을 찾지 못했습니다."
        )

    images = content.select(
        "img"
    )

    if not images:
        raise Exception(
            ".tb_body 안에서 이미지를 찾지 못했습니다."
        )

    result = []

    for img in images:

        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-original")
        )

        if not src:
            continue

        image_url = urljoin(
            post["link"],
            src
        )

        alt = clean_text(
            img.get("alt", "")
        )

        result.append({
            "url": image_url,
            "alt": alt
        })

    print()
    print(f"찾은 이미지: {len(result)}개")

    for i, image in enumerate(
        result,
        1
    ):
        print(
            f"  [{i}] {image['url']}"
        )

        if image["alt"]:
            print(
                f"      ALT: {image['alt']}"
            )

    if not result:
        raise Exception(
            "메뉴 이미지를 찾지 못했습니다."
        )

    return result


# ============================================================
# 3. 이미지 다운로드
# ============================================================

def download_image(
    image_url,
    index
):

    print()
    print(
        f"[3] 이미지 {index} 다운로드 중..."
    )

    response = session.get(
        image_url,
        timeout=30
    )

    response.raise_for_status()

    image = Image.open(
        BytesIO(
            response.content
        )
    )

    # RGB/RGBA 문제 방지
    if image.mode not in (
        "RGB",
        "RGBA"
    ):
        image = image.convert(
            "RGB"
        )

    extension = ".jpg"

    content_type = response.headers.get(
        "Content-Type",
        ""
    ).lower()

    if "png" in content_type:
        extension = ".png"

    elif "webp" in content_type:
        extension = ".webp"

    filepath = os.path.join(
        OUTPUT_DIR,
        f"menu_{index}{extension}"
    )

    image.save(
        filepath
    )

    print(
        f"저장: {filepath}"
    )

    print(
        f"크기: {image.width} x {image.height}"
    )

    return image, filepath


# ============================================================
# 4. OCR
# ============================================================

def run_ocr(
    ocr,
    image_path
):

    print()
    print("[4] OCR 처리 중...")

    result = list(ocr.predict(
        image_path
    ))

    texts = []

    for res in result:

        # PaddleOCR v3.x predict() 결과
        try:
            data = res.json

            if callable(data):
                data = data()

        except Exception:
            continue

        if not isinstance(
            data,
            dict
        ):
            continue

        ocr_data = data.get(
            "res",
            data
        )

        rec_texts = ocr_data.get(
            "rec_texts",
            []
        )

        rec_boxes = ocr_data.get(
            "rec_boxes",
            []
        )

        for i, text in enumerate(
            rec_texts
        ):

            text = clean_text(
                text
            )

            if not text:
                continue

            box = None

            if i < len(
                rec_boxes
            ):
                box = rec_boxes[i]

            # 좌표 계산: 박스 중심(x) + 경계(x1, x2) 저장
            # 병합된 텍스트(여러 날짜/헤더)의 위치 보간에 x1/x2가 필요하다.
            x = 0
            y = 0
            x1 = 0
            x2 = 0

            if box is not None:

                try:
                    x1 = float(box[0])
                    x2 = float(box[2]) if len(box) >= 4 else x1
                    x = (x1 + x2) / 2
                    y = float(box[1])
                    if len(box) >= 4:
                        y = (float(box[1]) + float(box[3])) / 2

                except Exception:
                    pass

            texts.append({
                "text": text,
                "x": x,
                "y": y,
                "x1": x1,
                "x2": x2,
                "text_len": len(text),
            })

    # 위에서 아래
    # 같은 줄에서는 왼쪽에서 오른쪽
    texts.sort(
        key=lambda item: (
            item["y"],
            item["x"]
        )
    )

    return texts


# ============================================================
# 5. OCR 결과를 줄 단위로 묶기
# ============================================================

def group_ocr_lines(
    ocr_items,
    y_threshold=25
):

    if not ocr_items:
        return []

    lines = []

    for item in ocr_items:

        placed = False

        for line in lines:

            avg_y = sum(
                x["y"]
                for x in line
            ) / len(line)

            if abs(
                item["y"] - avg_y
            ) <= y_threshold:

                line.append(
                    item
                )

                placed = True
                break

        if not placed:

            lines.append([
                item
            ])

    # 줄 내부는 x 좌표 순서
    for line in lines:

        line.sort(
            key=lambda x: x["x"]
        )

    # 전체 줄은 y 좌표
    lines.sort(
        key=lambda line: min(
            x["y"]
            for x in line
        )
    )

    result = []

    for line in lines:

        text = " ".join(
            item["text"]
            for item in line
        )

        text = clean_text(
            text
        )

        if text:
            result.append(
                text
            )

    return result


# ============================================================
# 6. OCR 결과 후처리
# ============================================================

def clean_menu_lines(lines):

    cleaned = []

    for line in lines:

        # 너무 짧은 쓰레기 문자 제거
        if len(line.strip()) == 0:
            continue

        # 반복 공백
        line = re.sub(
            r"\s+",
            " ",
            line
        ).strip()

        cleaned.append(
            line
        )

    return cleaned


# ============================================================
# 7. 기간 추출
# ============================================================

def extract_period(
    alt,
    text_lines
):

    # 예:
    # 메뉴 (26.08.31~09.04.jpg)

    text = alt + " " + " ".join(
        text_lines
    )

    patterns = [

        r"(\d{2}\.\d{2}\.\d{2})\s*[~\-]\s*(\d{2}\.\d{2})",

        r"(\d{4}\.\d{2}\.\d{2})\s*[~\-]\s*(\d{4}\.\d{2}\.\d{2})",

        r"(\d{4}-\d{2}-\d{2})\s*[~\-]\s*(\d{4}-\d{2}-\d{2})"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text
        )

        if match:

            return match.group(
                0
            )

    return ""


def _year_from_post_date(post_date_str):
    """게시물 작성일("2026-10-12" 형식)에서 연도를 추출한다.

    파싱에 실패하면 None을 반환하고, parse_daily_menus가
    기간 문자열/오늘 날짜로 대체 추정한다.
    """
    if not post_date_str:
        return None

    try:
        return datetime.date.fromisoformat(str(post_date_str).strip()).year
    except (TypeError, ValueError):
        return None


# ============================================================
# 8. 날짜별 메뉴 파싱
# ============================================================

def _find_date_line(line):
    """OCR 줄에서 날짜 정보를 추출.
    예: '08월31일 (월)', '9월1일 (화)', '09월2일 (수)' 등
    OCR 공백 오차는 _normalize_ocr_text로 흡수한다.
    반환: (month, day, weekday) 또는 None. 요일이 없으면 None.
    """
    normalized = _normalize_ocr_text(line)
    m = _DATE_PATTERN.search(normalized)
    if m:
        return (
            int(m.group(1)),
            int(m.group(2)),
            m.group(3) if m.group(3) else None,
        )
    return None


def _find_all_dates(line):
    """하나의 OCR 텍스트에서 모든 날짜를 등장 순서대로 추출한다.

    하나의 OCR 박스에 여러 날짜가 병합된 경우를 다룬다.
    예: '10월12일 (월) 10월13일(화)' → [(0, 10, 10, 12, '월'), (12, 10, 10, 13, '화')]
    반환: [(match_start, match_len, month, day, weekday_or_None), ...]
    """
    normalized = _normalize_ocr_text(line)
    results = []
    for m in _DATE_PATTERN.finditer(normalized):
        results.append((
            m.start(),
            len(m.group(0)),
            int(m.group(1)),
            int(m.group(2)),
            m.group(3) if m.group(3) else None,
        ))
    return results


def _is_weekday_token(text):
    """괄호 요일 '(월)' 또는 단독 요일 '월' 토큰인지 판별한다.
    이런 토큰은 메뉴 항목으로 유입되면 안 된다.
    """
    normalized = _normalize_ocr_text(text)
    return bool(_WEEKDAY_TOKEN_PATTERN.match(normalized))


def _find_day_header(line):
    """요일 헤더 감지 (MON, TUE, ... 또는 월, 화, ...)
    반환: 정규화된 요일 문자열 또는 None
    """
    upper = line.strip().upper()
    for key, val in DAY_KEYWORDS.items():
        if key.upper() == upper:
            return val
    return None


def _find_day_headers(line):
    """하나의 OCR 텍스트에서 모든 영문 요일 헤더를 등장 순서대로 추출한다.

    하나의 OCR 박스에 여러 헤더가 병합된 경우를 다룬다.
    예: 'MON TUE WED THU FRI' → [(0, 3, '월'), (4, 3, '화'), ...]
    반환: [(match_start, match_len, weekday_한글), ...]
    """
    normalized = _normalize_ocr_text(line)
    results = []
    for m in _DAY_HEADER_PATTERN.finditer(normalized):
        weekday = DAY_KEYWORDS.get(m.group(1))
        if weekday:
            results.append((m.start(), len(m.group(0)), weekday))
    return results


def _find_course_label(line):
    """코스 라벨 감지 (A코스, B코스, 공통 등)
    OCR 오인식 대응: B코ㅅ, A코 스, A 코스 등
    반환: 코스 이름 또는 None
    """
    line_stripped = line.strip()
    # 정확한 매칭: A코스, B코스
    if re.match(r"^[A-Za-z]\s*코\s*스$", line_stripped):
        return line_stripped[0].upper() + "코스"
    # OCR 오인식 대응: B코ㅅ, A코ス 등 (마지막 글자가 다를 수 있음)
    m = re.match(r"^([A-Za-z])\s*코\s*.", line_stripped)
    if m and len(line_stripped) <= 5:
        return m.group(1).upper() + "코스"
    # A 코 스, B 코 스
    m2 = re.match(r"^([A-Za-z])\s+코", line_stripped)
    if m2 and len(line_stripped) <= 6:
        return m2.group(1).upper() + "코스"
    if "공통" in line_stripped and len(line_stripped) <= 4:
        return "공통"
    return None


def parse_daily_menus(ocr_items, period_str="", year=None):
    """OCR 아이템(text, x, y)을 날짜별 구조화 메뉴로 파싱한다.

    메뉴 이미지 구조:
    - 상단: 요일 헤더 (MON ~ FRI)
    - 요일 아래: 날짜 (08월31일 (월))
    - 왼쪽 라벨: A코스 / B코스 / 공통
    - 각 셀: 메뉴 아이템

    접근 방식:
    1. 날짜 감지는 정규화된 텍스트로 수행하고, 하나의 OCR 박스에
       여러 날짜/헤더가 병합된 경우 문자 오프셋 비례로 x를 보간한다.
    2. 날짜 아이템들의 y를 클러스터링해 '날짜 행'을 식별하고,
       행 내 날짜를 x순으로 정렬해 열 앵커로 사용한다.
    3. y 좌표 기준으로 행(코스) 클러스터링
    4. 각 메뉴 아이템을 열(날짜)×행(코스)에 배정
    """
    if not ocr_items:
        return {}

    # ----- 연도 결정: 파라미터 > 기간 문자열 > 오늘 -----
    if year is None:
        year_match = re.search(r"(\d{4})", period_str)
        if year_match:
            year = int(year_match.group(1))
        else:
            y2 = re.search(r"(\d{2})\.\d{2}\.\d{2}", period_str)
            if y2:
                year = 2000 + int(y2.group(1))
            else:
                year = datetime.date.today().year

    def _interp_x(item, match_start, match_len, text_len):
        """박스 내 문자 오프셋 비례로 매치 중심의 x 좌표를 보간한다.

        하나의 박스에 여러 날짜/헤더가 병합된 경우에도
        각 토큰이 서로 다른 x를 갖도록 한다.
        """
        x1 = float(item.get("x1", item.get("x", 0)) or 0)
        x2 = float(item.get("x2", x1) or 0)
        width = x2 - x1
        frac = (match_start + match_len / 2) / max(text_len, 1)
        frac = min(max(frac, 0.0), 1.0)
        return x1 + width * frac

    # ----- 아이템 분류 -----

    date_entries = []   # [{"x","y","month","day","weekday"}]
    day_header_xs = []  # 영문/한글 요일 헤더의 x (보조 앵커용)
    course_rows = []    # [(y_center, course_name)]
    menu_items = []     # 메뉴 후보 텍스트

    for item in ocr_items:
        text = item.get("text", "")
        x = float(item.get("x", 0) or 0)
        y = float(item.get("y", 0) or 0)

        ntext = _normalize_ocr_text(text)

        # 1) 단독 한글 요일 헤더 (괄호 없는 한 글자: '월')
        if re.match(r"^[월화수목금토일]$", ntext):
            day_header_xs.append(x)
            continue

        # 2) 영문 요일 헤더 (병합 박스 지원: 'MON TUE WED THU FRI')
        headers = _find_day_headers(ntext)
        if headers:
            for hstart, hlen, _weekday in headers:
                day_header_xs.append(
                    _interp_x(item, hstart, hlen, len(ntext))
                )
            continue

        # 3) 날짜 감지 (병합 박스에서 다중 날짜 지원)
        date_matches = _find_all_dates(ntext)
        if date_matches:
            for mstart, mlen, month, day, weekday in date_matches:
                date_entries.append({
                    "x": _interp_x(item, mstart, mlen, len(ntext)),
                    "y": y,
                    "month": month,
                    "day": day,
                    "weekday": weekday,
                })
            continue

        # 4) 괄호 요일 토큰 차단: '(월)', '화' 등은 메뉴가 아니다
        if _is_weekday_token(ntext):
            continue

        # 5) 코스 라벨
        course = _find_course_label(text)
        if course:
            course_rows.append((y, course))
            continue

        # 6) 제목/상호명/원산지 등 비메뉴 텍스트 필터
        skip_patterns = [
            r"ELORA",
            r"in\s*garden",
            r"구내식",
            r"원\s*산\s*지",
            r"영양사",
            r"상기\s*메뉴",
            r"식자재",
            r"변경될",
            r"소고기",
            r"돼지고기",
            r"소세지류",
            r"건파래",
            r"메추리알",
            r"양파",
            r"버섯류",
            r"김치류",
            r"국내산",
            r"수입산",
            r"혼합",
            r"중국산",
        ]
        skip = False
        for pat in skip_patterns:
            if re.search(pat, text, re.IGNORECASE):
                skip = True
                break
        if skip:
            continue

        menu_items.append(item)

    # ----- 날짜 행 → 열 앵커 -----
    # y가 가까운 날짜들이 한 행(주간 그리드의 날짜 줄)을 이룬다.
    # 여러 이미지의 OCR 결과가 합쳐진 경우 같은 날짜 행이 중복될 수 있어
    # (month, day) 기준으로 첫 등장(가장 위 행)만 남긴다.
    date_entries.sort(key=lambda e: (e["y"], e["x"]))

    seen_dates = set()
    day_columns = []   # [(x_center, month, day, weekday)]

    for entry in date_entries:
        date_key = (entry["month"], entry["day"])
        if date_key in seen_dates:
            continue
        seen_dates.add(date_key)

        weekday = entry["weekday"] or _weekday_from_date(
            year, entry["month"], entry["day"]
        )
        if weekday is None:
            # 유효하지 않은 날짜(예: 13월)는 열로 만들지 않는다
            continue

        day_columns.append(
            (entry["x"], entry["month"], entry["day"], weekday)
        )

    # ----- fallback 1: 요일 헤더 앵커로 빠진 열 복원 -----
    # 날짜 앵커 수가 요일 헤더 수보다 적고, 각 날짜 앵커가 서로 다른
    # 헤더에 1:1로 대응되면, 매칭되지 않은 헤더 위치를 '날짜 미지정'
    # 열 앵커로 추가한다. (fallback 2가 날짜를 채운다)
    if day_header_xs and len(day_columns) < len(day_header_xs):
        headers_sorted = sorted(day_header_xs)
        used_headers = set()
        snapped = []  # [(anchor_x, month, day, weekday)]

        for col_x, month, day, weekday in day_columns:
            best_h, best_d = None, float("inf")
            for hx in headers_sorted:
                if hx in used_headers:
                    continue
                dist = abs(hx - col_x)
                if dist < best_d:
                    best_h, best_d = hx, dist
            if best_h is not None:
                used_headers.add(best_h)
                snapped.append((best_h, month, day, weekday))
            else:
                snapped.append((col_x, month, day, weekday))

        for hx in headers_sorted:
            if hx not in used_headers:
                snapped.append((hx, None, None, None))

        if len(snapped) > len(day_columns):
            day_columns = snapped
            day_columns.sort(key=lambda c: c[0])

    # ----- fallback 2: period 역산으로 누락 열/날짜 복원 -----
    # 우선순위: 날짜 앵커가 항상 이긴다. period는 앵커가 없는 열/날짜만 채우고,
    # 기존 앵커의 날짜와 충돌하면 앵커를 유지한다.
    known_columns = [
        (col_x, month, day, weekday)
        for col_x, month, day, weekday in day_columns
        if month is not None
    ]
    unknown_columns = [
        (col_x, month, day, weekday)
        for col_x, month, day, weekday in day_columns
        if month is None
    ]

    period_start, period_end = _parse_period_dates(period_str)

    if len(known_columns) >= 2 and period_start is not None:
        # 기간 내 모든 날짜 (최대 7일, 종료일 없으면 시작일+4일 = 월~금)
        if period_end is None:
            period_end = period_start + datetime.timedelta(days=4)

        ref = period_start
        period_days = []
        cursor = period_start
        while cursor <= period_end and len(period_days) < 7:
            period_days.append(cursor)
            cursor += datetime.timedelta(days=1)

        # 알려진 앵커 2개로 (날짜 오프셋 → x) 선형 보간 계수를 구한다
        fitted_points = [
            ((datetime.date(year, month, day) - ref).days, col_x)
            for col_x, month, day, _ in known_columns
            if period_start <= datetime.date(year, month, day) <= period_end
        ]
        fitted_points.sort()

        if len(fitted_points) >= 2:
            off1, x1 = fitted_points[0]
            off2, x2 = fitted_points[-1]
            if off2 > off1 and x2 > x1:
                slope = (x2 - x1) / (off2 - off1)
                intercept = x1 - slope * off1

                existing_dates = {
                    (month, day) for _, month, day, _ in known_columns
                }
                for period_date in period_days:
                    if (period_date.month, period_date.day) in existing_dates:
                        continue
                    fitted_x = intercept + slope * (
                        (period_date - ref).days
                    )
                    day_columns.append((
                        fitted_x,
                        period_date.month,
                        period_date.day,
                        _WEEKDAY_INDEX[period_date.weekday()],
                    ))

                day_columns.sort(key=lambda c: c[0])

    elif unknown_columns and period_start is not None:
        # 헤더 앵커로 만들어진 '날짜 미지정' 열: x순(좌→우)으로
        # period 시작일부터 순서대로 채운다. (이미 앵커가 사용한 날짜 제외)
        if period_end is None:
            period_end = period_start + datetime.timedelta(days=4)

        existing_dates = {
            (month, day) for _, month, day, _ in known_columns
        }
        period_days = []
        cursor = period_start
        while cursor <= period_end and len(period_days) < 7:
            if (cursor.month, cursor.day) not in existing_dates:
                period_days.append(cursor)
            cursor += datetime.timedelta(days=1)

            unknown_columns.sort(key=lambda c: c[0])
        for idx, (col_x, _, _, _) in enumerate(unknown_columns):
            if idx >= len(period_days):
                # 채울 날짜가 부족하면 해당 열은 폐기한다
                day_columns = [
                    c for c in day_columns if not (
                        c[0] == col_x and c[1] is None
                    )
                ]
                continue
            fill_date = period_days[idx]
            for i, (cx, month, day, weekday) in enumerate(day_columns):
                if cx == col_x and month is None:
                    day_columns[i] = (
                        col_x,
                        fill_date.month,
                        fill_date.day,
                        _WEEKDAY_INDEX[fill_date.weekday()],
                    )
                    break

    # 잔존하는 '날짜 미지정' 열 정리 (선형 보간으로 대체되었거나 채우기 실패한 열)
    day_columns = [c for c in day_columns if c[1] is not None]

    # 열(요일) 정렬 (x 기준)
    day_columns.sort(key=lambda c: c[0])

    if not day_columns:
        # 날짜를 찾지 못했으면 빈 결과
        return {}

    # ----- 각 아이템을 열 구간(중간점 경계)에 배정 -----

    col_centers = [c[0] for c in day_columns]

    col_bounds = []
    for i in range(len(col_centers)):
        if i == 0:
            bound_start = float("-inf")
        else:
            bound_start = (col_centers[i - 1] + col_centers[i]) / 2
        if i < len(col_centers) - 1:
            bound_end = (col_centers[i] + col_centers[i + 1]) / 2
        else:
            bound_end = float("inf")
        col_bounds.append((bound_start, bound_end))

    def nearest_col(x):
        """x 좌표가 속하는 열 구간(인접 앵커 중간점 경계)의 인덱스"""
        for i, (bound_start, bound_end) in enumerate(col_bounds):
            if bound_start <= x < bound_end:
                return i
        return len(col_centers) - 1

    # ----- 코스 행 경계 -----
    # 코스 라벨의 y 좌표 중간점으로 구간을 나눈다

    course_rows.sort(key=lambda r: r[0])

    # 코스 간 y 경계 계산 (두 코스 라벨 사이의 중간점)
    course_boundaries = []  # [(y_start, y_end, course_name)]
    for i, (cy, cname) in enumerate(course_rows):
        if i == 0:
            y_start = 0
        else:
            # 이전 코스와 현재 코스의 중간점
            y_start = (course_rows[i - 1][0] + cy) / 2

        if i < len(course_rows) - 1:
            y_end = (cy + course_rows[i + 1][0]) / 2
        else:
            y_end = float("inf")

        course_boundaries.append(
            (y_start, y_end, cname)
        )

    def find_course(y):
        """y 좌표가 속하는 코스 구간 찾기"""
        if not course_boundaries:
            return "메뉴"
        for y_start, y_end, cname in course_boundaries:
            if y_start <= y < y_end:
                return cname
        # 범위 밖이면 마지막 코스
        return course_boundaries[-1][2]

    # ----- 날짜별로 메뉴 모으기 -----

    daily_menus = {}

    for col_idx, (_, month, day, weekday) in enumerate(
        day_columns
    ):
        date_str = f"{year}-{month:02d}-{day:02d}"
        date_key = f"{date_str} ({weekday})"

        daily_menus[date_key] = {
            "date": date_str,
            "weekday": weekday,
            "courses": {}
        }

    # 각 메뉴 아이템을 열/코스에 배정
    col_items = {i: [] for i in range(len(day_columns))}

    for item in menu_items:
        col = nearest_col(item["x"])
        course = find_course(item["y"])
        col_items[col].append({
            "text": item["text"],
            "y": item["y"],
            "course": course,
        })

    # 각 열(날짜)의 아이템을 코스별로 정리
    for col_idx, (_, month, day, weekday) in enumerate(
        day_columns
    ):
        date_str = f"{year}-{month:02d}-{day:02d}"
        date_key = f"{date_str} ({weekday})"

        items = col_items.get(col_idx, [])

        # y 순서로 정렬
        items.sort(key=lambda it: it["y"])

        courses = {}
        for it in items:
            c = it["course"]
            if c not in courses:
                courses[c] = []
            # 중복 방지
            if it["text"] not in courses[c]:
                courses[c].append(it["text"])

        daily_menus[date_key]["courses"] = courses

    return daily_menus


# ============================================================
# 9. 결과 저장
# ============================================================

def save_result(
    post,
    images,
    daily_menus,
    ocr_lines,
    period
):

    print()
    print("[5] 결과 저장 중...")

    result = {
        "post": post,
        "period": period,
        "images": images,
        "daily_menus": daily_menus,
        "menu_text": ocr_lines
    }

    # JSON
    json_path = os.path.join(
        OUTPUT_DIR,
        "menu.json"
    )

    with open(
        json_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            result,
            f,
            ensure_ascii=False,
            indent=2
        )

    # TXT - 날짜별 정리
    txt_path = os.path.join(
        OUTPUT_DIR,
        "menu.txt"
    )

    with open(
        txt_path,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            f"제목: {post['title']}\n"
        )

        f.write(
            f"작성일: {post['date']}\n"
        )

        if period:
            f.write(
                f"메뉴 기간: {period}\n"
            )

        f.write(
            f"링크: {post['link']}\n"
        )

        f.write("\n")

        # 날짜별 메뉴 출력
        if daily_menus:
            for date_key in sorted(
                daily_menus.keys()
            ):
                menu = daily_menus[date_key]
                f.write(
                    "=" * 60 + "\n"
                )
                f.write(
                    f"[{date_key}]\n"
                )
                f.write(
                    "=" * 60 + "\n"
                )

                courses = menu.get(
                    "courses", {}
                )

                for course_name, items in courses.items():
                    f.write(
                        f"\n  [{course_name}]\n"
                    )
                    for item in items:
                        f.write(
                            f"    - {item}\n"
                        )

                f.write("\n")
        else:
            f.write(
                "=" * 60 + "\n\n"
            )
            for line in ocr_lines:
                f.write(
                    line + "\n"
                )

    # 날짜별 개별 JSON 파일도 저장
    if daily_menus:
        for date_key, menu in daily_menus.items():
            date_str = menu["date"]
            day_path = os.path.join(
                OUTPUT_DIR,
                f"menu_{date_str}.json"
            )
            with open(
                day_path,
                "w",
                encoding="utf-8"
            ) as f:
                json.dump(
                    {
                        "date": date_str,
                        "weekday": menu["weekday"],
                        "courses": menu["courses"],
                        "post_title": post["title"],
                        "period": period,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2
                )
            print(
                f"날짜별 JSON: {day_path}"
            )

    print(
        f"JSON 저장: {json_path}"
    )

    print(
        f"TXT 저장 : {txt_path}"
    )

    return result


# ============================================================
# MAIN
# ============================================================

def main():

    if PaddleOCR is None:
        raise RuntimeError(
            "paddleocr가 설치되어 있지 않아 크롤링을 실행할 수 없습니다. "
            "`python3 -m pip install paddlepaddle paddleocr` 후 다시 시도하세요."
        )

    print()
    print("=" * 70)
    print("구내식 메뉴 자동 크롤러")
    print("=" * 70)

    make_output_dir()

    # ----------------------------------------
    # 최신 게시물
    # ----------------------------------------

    post = get_latest_meal_post()

    # ----------------------------------------
    # 메뉴 이미지
    # ----------------------------------------

    images = get_menu_images(
        post
    )

    # ----------------------------------------
    # OCR 엔진
    # ----------------------------------------

    print()
    print("[OCR] PaddleOCR 초기화 중...")

    ocr = PaddleOCR(
        lang="korean",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )

    all_ocr_items = []
    all_lines = []

    # ----------------------------------------
    # 이미지별 OCR
    # ----------------------------------------

    for index, image_info in enumerate(
        images,
        1
    ):

        try:

            image, filepath = download_image(
                image_info["url"],
                index
            )

            ocr_items = run_ocr(
                ocr,
                filepath
            )

            all_ocr_items.extend(
                ocr_items
            )

            lines = group_ocr_lines(
                ocr_items
            )

            lines = clean_menu_lines(
                lines
            )

            print()
            print(
                f"--- 이미지 {index} OCR 결과 ---"
            )

            for line in lines:
                print(
                    line
                )

            all_lines.extend(
                lines
            )

        except Exception as e:

            print(
                f"이미지 {index} 처리 실패: {e}"
            )

    # ----------------------------------------
    # 기간
    # ----------------------------------------

    alt_text = " ".join(
        img.get(
            "alt",
            ""
        )
        for img in images
    )

    period = extract_period(
        alt_text,
        all_lines
    )

    # ----------------------------------------
    # 날짜별 메뉴 파싱
    # ----------------------------------------

    print()
    print("[6] 날짜별 메뉴 파싱 중...")

    daily_menus = parse_daily_menus(
        all_ocr_items,
        period,
        year=_year_from_post_date(post.get("date")),
    )

    # ----------------------------------------
    # 결과 저장
    # ----------------------------------------

    result = save_result(
        post,
        images,
        daily_menus,
        all_lines,
        period
    )

    # ----------------------------------------
    # 최종 출력
    # ----------------------------------------

    print()
    print("=" * 70)
    print("날짜별 메뉴")
    print("=" * 70)

    if daily_menus:
        for date_key in sorted(
            daily_menus.keys()
        ):
            menu = daily_menus[date_key]
            print(
                f"\n[{date_key}]"
            )
            print(
                "-" * 40
            )

            for course, items in menu.get(
                "courses", {}
            ).items():
                print(
                    f"  [{course}]"
                )
                for item in items:
                    print(
                        f"    - {item}"
                    )
    else:
        print("날짜별 파싱 실패. 원본 텍스트:")
        for line in all_lines:
            print(line)

    print()
    print("=" * 70)
    print("완료!")
    print("=" * 70)


if __name__ == "__main__":
    main()
