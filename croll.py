# meal_crawler.py

import os
import re
import json
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
from paddleocr import PaddleOCR


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

            # 좌표 계산
            x = 0
            y = 0

            if box is not None:

                try:
                    x = float(
                        box[0]
                    )

                    y = float(
                        box[1]
                    )

                except Exception:
                    pass

            texts.append({
                "text": text,
                "x": x,
                "y": y
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


# ============================================================
# 8. 날짜별 메뉴 파싱
# ============================================================

def _find_date_line(line):
    """OCR 줄에서 날짜 정보를 추출.
    예: '08월31일 (월)', '9월1일 (화)', '09월2일 (수)' 등
    반환: (month, day, weekday) 또는 None
    """
    # 패턴: MM월DD일 (요일)
    m = re.search(
        r"(\d{1,2})월\s*(\d{1,2})일\s*\(?([월화수목금토일])\)?",
        line
    )
    if m:
        return (
            int(m.group(1)),
            int(m.group(2)),
            m.group(3)
        )
    return None


def _find_day_header(line):
    """요일 헤더 감지 (MON, TUE, ... 또는 월, 화, ...)
    반환: 정규화된 요일 문자열 또는 None
    """
    upper = line.strip().upper()
    for key, val in DAY_KEYWORDS.items():
        if key.upper() == upper:
            return val
    return None


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


def parse_daily_menus(ocr_items, period_str=""):
    """OCR 아이템(text, x, y)을 날짜별 구조화 메뉴로 파싱한다.

    메뉴 이미지 구조:
    - 상단: 요일 헤더 (MON ~ FRI)
    - 요일 아래: 날짜 (08월31일 (월))
    - 왼쪽 라벨: A코스 / B코스 / 공통
    - 각 셀: 메뉴 아이템

    접근 방식:
    1. x 좌표 기준으로 열(요일) 클러스터링
    2. y 좌표 기준으로 행(코스) 클러스터링
    3. 날짜 텍스트 → 해당 열과 매핑
    4. 코스 라벨 → 해당 행과 매핑
    """
    if not ocr_items:
        return {}

    # ----- x 좌표 기준 열 클러스터링 -----
    # 요일 헤더 / 날짜 라인으로 열 경계를 잡는다

    day_columns = []   # [(x_center, month, day, weekday)]
    course_rows = []   # [(y_center, course_name)]
    menu_items = []    # 나머지 텍스트

    for item in ocr_items:
        text = item["text"]
        x = item["x"]
        y = item["y"]

        # 날짜 감지
        date_info = _find_date_line(text)
        if date_info:
            day_columns.append(
                (x, date_info[0], date_info[1], date_info[2])
            )
            continue

        # 요일 헤더 (MON, TUE 등) → 건너뜀
        day_header = _find_day_header(text)
        if day_header:
            continue

        # 코스 라벨
        course = _find_course_label(text)
        if course:
            course_rows.append((y, course))
            continue

        # 제목/상호명/원산지 등 비메뉴 텍스트 필터
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

    # 열(요일) 정렬 (x 기준)
    day_columns.sort(key=lambda c: c[0])

    if not day_columns:
        # 날짜를 찾지 못했으면 빈 결과
        return {}

    # ----- 각 아이템을 가장 가까운 열에 배정 -----

    col_centers = [c[0] for c in day_columns]

    def nearest_col(x):
        """x 좌표에 가장 가까운 열 인덱스"""
        min_dist = float("inf")
        best = 0
        for i, cx in enumerate(col_centers):
            dist = abs(x - cx)
            if dist < min_dist:
                min_dist = dist
                best = i
        return best

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

    # 연도 추정 (기간 문자열에서)
    year = 2026
    year_match = re.search(r"(\d{4})", period_str)
    if year_match:
        year = int(year_match.group(1))
    elif re.search(r"(\d{2})\.\d{2}\.\d{2}", period_str):
        y2 = re.search(r"(\d{2})\.\d{2}\.\d{2}", period_str)
        if y2:
            year = 2000 + int(y2.group(1))

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
        period
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
