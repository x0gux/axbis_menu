import json
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import urllib3

# SSL 경고 비활성화
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://g5w.co.kr/home/"
BOARD_URL = "https://g5w.co.kr/home/m_board.php"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def crawl_board(ps_db: str = "b7", page: int = 1) -> list[dict]:
    """
    특정 페이지의 게시판 목록을 크롤링합니다.

    :param ps_db: 게시판 식별자 (기본값: 'b7')
    :param page: 페이지 번호 (기본값: 1)
    :return: 게시글 정보 딕셔너리 리스트
    """
    params = {
        "ps_db": ps_db,
        "ps_page": page,
    }

    try:
        response = requests.get(
            BOARD_URL,
            params=params,
            headers=HEADERS,
            verify=False,
            timeout=10,
        )
        response.raise_for_status()
        # 한글 인코딩 설정 (euc-kr)
        response.encoding = "euc-kr"
    except requests.RequestException as e:
        print(f"[오류] 페이지 {page} 요청 실패: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    posts = []

    # 게시글 행(tr) 찾기
    num_tds = soup.find_all("td", class_="tb_num")

    for num_td in num_tds:
        tr = num_td.find_parent("tr")
        if not tr:
            continue

        # 1. 번호
        no = num_td.get_text(strip=True)

        # 2. 제목 및 링크
        subject_td = tr.find("td", class_="tb_subject")
        title = ""
        link = ""
        if subject_td:
            a_tag = subject_td.find("a")
            if a_tag:
                title = a_tag.get_text(strip=True)
                href = a_tag.get("href", "")
                link = urljoin(BASE_URL, href)
            else:
                title = subject_td.get_text(strip=True)

        # 3. 작성자
        name_td = tr.find("td", class_="tb_name")
        author = ""
        if name_td:
            # 숨김 레이어(div)를 제외한 작성자 텍스트 추출
            author_tag = name_td.find("a", onclick=lambda v: v and "show(" in v)
            if author_tag:
                author = author_tag.get_text(strip=True)
            else:
                # onclick이 없을 경우 레이어 제외하고 텍스트 추출
                for div in name_td.find_all("div"):
                    div.decompose()
                author = name_td.get_text(strip=True)

        # 4. 작성일
        date_td = tr.find("td", class_="tb_data")
        date = date_td.get_text(strip=True) if date_td else ""

        # 5. 조회수
        count_td = tr.find("td", class_="tb_count")
        views = count_td.get_text(strip=True) if count_td else "0"

        posts.append({
            "no": no,
            "title": title,
            "author": author,
            "date": date,
            "views": views,
            "link": link,
        })

    return posts


def crawl_multiple_pages(ps_db: str = "b7", start_page: int = 1, max_pages: int = 3) -> list[dict]:
    """
    여러 페이지의 게시판 목록을 크롤링합니다.

    :param ps_db: 게시판 식별자 (기본값: 'b7')
    :param start_page: 시작 페이지 번호 (기본값: 1)
    :param max_pages: 크롤링할 총 페이지 수 (기본값: 3)
    :return: 수집된 전체 게시글 리스트
    """
    all_posts = []
    for page in range(start_page, start_page + max_pages):
        print(f"[*] {page} 페이지 크롤링 중...")
        posts = crawl_board(ps_db=ps_db, page=page)
        if not posts:
            print(f"[*] 더 이상 게시글이 없거나 요청이 완료되었습니다. (페이지: {page})")
            break
        all_posts.extend(posts)

    return all_posts


def save_to_json(posts: list[dict], filename: str = "posts.json") -> None:
    """수집된 게시글을 JSON 파일로 저장합니다."""
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
    print(f"[+] 총 {len(posts)}개의 게시글이 '{filename}'에 저장되었습니다.")


if __name__ == "__main__":
    print("=" * 60)
    print("가든파이브웍스 (g5w.co.kr) 게시판 크롤러 실행")
    print("=" * 60)

    # 1페이지 크롤링 테스트
    posts = crawl_board(ps_db="b7", page=1)

    print(f"\n[1페이지 크롤링 결과] (총 {len(posts)}개)")
    print("-" * 60)
    for p in posts:
        print(f"[{p['no']}] {p['title']}")
        print(f"     작성자: {p['author']} | 작성일: {p['date']} | 조회수: {p['views']}")
        print(f"     링크: {p['link']}")
        print("-" * 60)

    # JSON 저장
    save_to_json(posts, "posts.json")
