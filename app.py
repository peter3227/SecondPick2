import ssl
import time
import re
import json
import random
import sys
import pymysql
from urllib.parse import quote
from datetime import datetime, timedelta

# DB 설정
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': 'peter3227',
    'db': 'joongna_db',
    'charset': 'utf8'
}

# Selenium
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Flask
from flask import Flask, render_template, request, session, redirect, url_for, flash

#로그인/로그아웃, 회원가입 
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# Flask 로그인 매니저
app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'  # 실제 운영시 변경 필요

# Flask-Login 설정
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = '로그인이 필요한 서비스입니다.'

# sys.stdout.reconfigure(encoding='utf-8') # Flask 환경에서는 필요하지 않습니다.

# ====================================================================
# 1. 환경 설정 및 상수 관리
# ====================================================================
class AppConfig:
    """애플리케이션 전반에 걸쳐 사용되는 설정 및 상수"""
    SECRET_KEY = 'your_unique_and_complex_secret_key'
    MOBILE_USER_AGENTS = [
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
        'Mozilla/5.0 (Linux; Android 14; SM-S901B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36',
    ]
    DEFAULT_WINDOW_SIZE = (414, 896)
    DEFAULT_LATITUDE = 37.4979
    DEFAULT_LONGITUDE = 127.0276
    DEFAULT_TIMEOUT = 10


# ====================================================================
# 2. 유틸리티 함수 (WebDriver 외부 기능)
# ====================================================================
class Utils:
    """데이터 클리닝, 포맷팅, 시간 계산 등의 헬퍼 함수"""

    @staticmethod
    def format_currency(value):
        """숫자를 통화 형식 문자열로 포맷하는 Jinja2 헬퍼 함수"""
        try:
            if isinstance(value, str):
                value = str(value).replace(',', '')
            if int(value) > 100000000:
                return "0"
            return f"{int(value):,}"
        except:
            return str(value)

    @staticmethod
    def clean_price_string(price_raw):
        """가격 문자열에서 숫자만 추출하여 int로 변환"""
        price_raw = str(price_raw).strip()

        if '만' in price_raw:
            price_str = price_raw.split('만')[0].replace(',', '').strip()
            try:
                return int(float(price_str) * 10000)
            except:
                pass

        if ('나눔' in price_raw or '배송비' in price_raw or '검수' in price_raw or '판매하기' in price_raw
            or '판매완료' in price_raw or '예약중' in price_raw or price_raw.lower() in ('0원', '무료', '가격없음', '가격')):
            return 0

        price_str = re.sub(r'[^\d]', '', price_raw)
        # 15자리 이상은 비정상적인 가격으로 간주
        return int(price_str) if price_str.isdigit() and len(price_str) < 15 else 0

    @staticmethod
    def calculate_time_ago(date_string):
        """시간/날짜 문자열을 파싱하여 'X분 전' 등으로 변환"""
        now = datetime.now()
        date_string = date_string.strip()

        # 이미 포맷된 경우
        if any(unit in date_string for unit in ["분 전", "시간 전", "일 전", "주 전", "방금 전"]):
            return date_string
        
        # 날짜 포맷 (예: 2023.11.27)
        try:
            if len(date_string) == 10 and date_string.count('.') == 2:
                post_date = datetime.strptime(date_string, "%Y.%m.%d")
                diff = now - post_date

                if diff.days == 0:
                    return "오늘"
                elif diff.days < 7:
                    return f"{diff.days}일 전"
                else:
                    return date_string
        except:
            pass

        return date_string


# ====================================================================
# 3. WebDriver 관리
# ====================================================================
class WebDriverFactory:
    """undetected-chromedriver 인스턴스를 생성하고 설정합니다."""

    @staticmethod
    def get_driver():
        """봇 탐지를 우회하는 웹드라이버를 반환합니다."""
        print("🌐 WebDriver 초기화 (undetected-chromedriver 사용)")

        options = uc.ChromeOptions()

        # Headless 및 봇 탐지 우회 설정
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument('--headless')

        # 모바일 User-Agent 설정
        selected_user_agent = random.choice(AppConfig.MOBILE_USER_AGENTS)
        options.add_argument(f"user-agent={selected_user_agent}")

        driver = None
        try:
            # WebDriver 생성
            driver = uc.Chrome(options=options)
            driver.set_window_size(*AppConfig.DEFAULT_WINDOW_SIZE)

            # 위치 정보 설정 (CDP Command)
            try:
                driver.execute_cdp_cmd(
                    "Emulation.setGeolocationOverride",
                    {
                        "latitude": AppConfig.DEFAULT_LATITUDE,
                        "longitude": AppConfig.DEFAULT_LONGITUDE,
                        "accuracy": 100
                    }
                )
            except Exception as e:
                print(f"위치 정보 설정 실패: {e}")

            return driver
        except Exception as e:
            print(f"❌ WebDriver 초기화 오류: {e}. 'undetected-chromedriver' 설치 상태를 확인해 주세요.")
            if driver:
                driver.quit()
            return None


# ====================================================================
# 4. 스크래퍼 베이스 및 플랫폼별 스크래퍼
# ====================================================================
class ScraperBase:
    """모든 플랫폼 스크래퍼의 기본 클래스"""
    PLATFORM_NAME = "Unknown"

    def __init__(self, driver):
        self.driver = driver

    def run_crawl(self, keyword):
        """크롤링 로직을 실행하고 결과를 반환합니다. (구현 필요)"""
        raise NotImplementedError("Subclass must implement abstract method")
    
    def _parse_item(self, **kwargs):
        """공통 데이터 구조로 아이템을 파싱"""
        return {
            'platform': self.PLATFORM_NAME,
            'title': kwargs.get('title', ''),
            'price': kwargs.get('price', 0),
            'link': kwargs.get('link', ''),
            'img_url': kwargs.get('img_url', "https://via.placeholder.com/150?text=No+Image"),
            'date_posted': kwargs.get('date_posted', '날짜 정보 없음')
        }


class JoongnaScraper(ScraperBase):
    """중고나라 크롤링 로직"""
    PLATFORM_NAME = "중고나라"
    
    def run_crawl(self, keyword):
        crawled_data = []
        try:
            url = f"https://web.joongna.com/search/{quote(keyword)}"
            self.driver.get(url)
            time.sleep(3) # 로딩 대기

            # 상품 목록 CSS Selector
            items = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/product/']")

            for item in items[:10]:
                try:
                    full_text = item.text.split('\n')
                    title = full_text[0].strip()

                    if not title or title == '판매하기':
                        continue

                    price_raw = full_text[1] if len(full_text) > 1 else "0원"
                    clean_price = Utils.clean_price_string(price_raw)

                    if clean_price == 0:
                        continue

                    link = item.get_attribute('href')
                    
                    # 날짜 추출
                    date_posted = "날짜 정보 없음"
                    try:
                        date_elem = item.find_element(By.CSS_SELECTOR, 'span.product-card-extra')
                        date_posted_raw = date_elem.text.split('·')[-1].strip()
                        date_posted = Utils.calculate_time_ago(date_posted_raw)
                    except:
                        pass
                        
                    # 이미지 추출
                    img_url = "https://via.placeholder.com/150?text=No+Image"
                    try:
                        img_tag = item.find_element(By.TAG_NAME, 'img')
                        img_url = img_tag.get_attribute('src')
                    except:
                        pass

                    crawled_data.append(self._parse_item(
                        title=title, price=clean_price, link=link, 
                        img_url=img_url, date_posted=date_posted
                    ))
                except Exception:
                    continue

        except Exception as e:
            print(f"❌ 중고나라 크롤링 중 치명적인 오류 발생: {e}")

        return crawled_data


class DanggeunScraper(ScraperBase):
    """당근마켓 크롤링 로직 (JSON-LD 활용)"""
    PLATFORM_NAME = "당근마켓"

    def run_crawl(self, keyword):
        crawled_data = []
        encoded_keyword = quote(keyword)
        url = f"https://www.daangn.com/search/{encoded_keyword}"

        try:
            self.driver.get(url)
            # 페이지 로딩 및 클라이언트 측 렌더링 대기
            time.sleep(random.uniform(3, 5))
            page_source = self.driver.page_source

            # JSON-LD 스크립트 태그 추출
            json_match = re.search(r'<script type="application/ld\+json">(.*?)</script>', page_source, re.DOTALL)

            if not json_match:
                print("당근마켓 JSON-LD 데이터 찾기 실패.")
                return []

            json_ld_string = json_match.group(1).strip()
            data = json.loads(json_ld_string)

            if 'itemListElement' not in data:
                return []

            for list_item in data['itemListElement'][:10]:
                try:
                    item_data = list_item['item']
                    offer = item_data['offers']

                    title = item_data['name']
                    link = item_data['url']
                    img_url = item_data.get('image', "https://via.placeholder.com/150?text=No+Image")
                    
                    price_raw = offer.get('price', '0')
                    availability = offer.get('availability', '')

                    # 품절 또는 0원 상품 제외
                    if 'OutOfStock' in availability or float(price_raw) == 0:
                        continue
                        
                    clean_price = int(float(price_raw))
                    
                    # 당근마켓 JSON-LD에는 정확한 게시 시간 정보가 포함되지 않아 '날짜 정보 없음' 유지
                    crawled_data.append(self._parse_item(
                        title=title, price=clean_price, link=link, 
                        img_url=img_url, date_posted="날짜 정보 없음"
                    ))
                except Exception:
                    continue

        except Exception as e:
            print(f"❌ 당근마켓 크롤링 중 치명적인 오류 발생: {e}")

        return crawled_data


class BunjangScraper(ScraperBase):
    """번개장터 크롤링 로직 (현재는 제외)"""
    PLATFORM_NAME = "번개장터"

    def run_crawl(self, keyword):
        # 현재는 번개장터 스크래핑 로직이 비어있으므로 빈 리스트 반환
        return []


# ====================================================================
# 5. Flask 애플리케이션 및 라우트 관리
# ====================================================================
class App:
    """Flask 애플리케이션 정의 및 메인 로직"""

    def __init__(self):
        # SSL 경고/에러 무시 (undetected-chromedriver 사용 시 필요)
        ssl._create_default_https_context = ssl._create_unverified_context
        
        self.app = Flask(__name__)
        self.app.secret_key = AppConfig.SECRET_KEY
        
        # Jinja2 필터 등록
        self.app.jinja_env.filters['format_currency'] = Utils.format_currency
        
        # 라우트 등록
        self.app.add_url_rule('/', view_func=self.index, methods=['GET'])

    def run(self, debug=True):
        """Flask 앱 실행"""
        self.app.run(debug=debug)
        
    def _calculate_platform_stats(self, items):
        """플랫폼별 가격 통계 계산"""
        prices = [item['price'] for item in items if item['price'] > 0]
        if not prices:
            return {'avg_price': 0, 'num_items': 0}
        avg = int(sum(prices) / len(prices))
        return {
            'avg_price': avg,
            'num_items': len(prices)
        }

    def _get_sorted_items_and_stats(self, keyword, sort_by):
        """크롤링을 실행하거나 세션에서 데이터를 가져와 정렬하고 통계를 계산"""
        
        all_items = session.get('all_items', [])
        platform_stats = session.get('platform_stats', {})
        
        # 새로운 키워드 검색이거나 세션 데이터가 없는 경우 크롤링 실행
        is_new_search = keyword and (keyword != session.get('last_keyword') or not all_items)
        
        if is_new_search:
            
            driver = None
            try:
                driver = WebDriverFactory.get_driver()
                
                if driver:
                    # 플랫폼별 스크래퍼 인스턴스 생성 및 크롤링 실행
                    joongna_items = JoongnaScraper(driver).run_crawl(keyword)
                    danggeun_items = DanggeunScraper(driver).run_crawl(keyword)
                else:
                    # 드라이버 초기화 실패 시 빈 리스트
                    joongna_items = []
                    danggeun_items = []

                bunjang_items = BunjangScraper(None).run_crawl(keyword) # driver 필요 없음
                
                all_items = joongna_items + danggeun_items + bunjang_items

                # 플랫폼별 통계 계산 및 저장
                platform_stats['중고나라'] = self._calculate_platform_stats(joongna_items)
                platform_stats['당근마켓'] = self._calculate_platform_stats(danggeun_items)
                platform_stats['번개장터'] = self._calculate_platform_stats(bunjang_items)

                session['all_items'] = all_items
                session['last_keyword'] = keyword
                session['platform_stats'] = platform_stats

            finally:
                if driver:
                    driver.quit()
        elif not keyword:
            all_items = []
            platform_stats = {}

        # --- 가격 통계 계산 및 정렬 ---
        min_price, max_price, avg_price_all = 0, 0, 0

        if all_items:
            valid_prices = [item['price'] for item in all_items if item['price'] > 0]

            if valid_prices:
                min_price = min(valid_prices)
                max_price = max(valid_prices)
                avg_price_all = int(sum(valid_prices) / len(valid_prices))

            # 정렬
            if sort_by == 'low_price':
                all_items.sort(key=lambda x: x['price'])
            elif sort_by == 'high_price':
                all_items.sort(key=lambda x: x['price'], reverse=True)
            # 'latest'는 크롤링 순서이므로 별도 처리 필요 없음

        return all_items, platform_stats, min_price, max_price, avg_price_all
        
    def index(self):
        """메인 검색 및 결과 페이지 라우트"""
        keyword = request.args.get('keyword')
        sort_by = request.args.get('sort', 'latest')

        all_items, platform_stats, min_price, max_price, avg_price_all = \
            self._get_sorted_items_and_stats(keyword, sort_by)

        return render_template('index.html',
                               items=all_items,
                               keyword=keyword,
                               platform_stats=platform_stats,
                               sort_by=sort_by,
                               min_price=min_price,
                               max_price=max_price,
                               avg_price_all=avg_price_all)

# ====================================================================
# 6. User 클래스 정의
# ====================================================================
class User(UserMixin):
    def __init__(self, user_id, email, nickname):
        self.id = user_id
        self.email = email
        self.nickname = nickname

# ====================================================================
# 7. 로그인/로그아웃, 회원가입 라우트
# ====================================================================
@login_manager.user_loader
def load_user(user_id):
    """세션에서 사용자 정보 로드"""
    conn = None
    try:
        conn = pymysql.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, email, nickname FROM users WHERE user_id = %s", (user_id,))
        user_data = cursor.fetchone()
    
        if user_data:
            return User(user_data[0], user_data[1], user_data[2])
    except Exception as e:
           print(f"❌ 사용자 로드 오류: {e}")
    finally:
        if conn:
            conn.close()
    return None
    
# 회원가입 라우트
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        nickname = request.form.get('nickname', '').strip()
    
    # 입력값 검증
    if not email or not password or not nickname:
        flash('모든 항목을 입력해주세요.', 'error')
        return redirect(url_for('register'))
        
    # 비밀번호 길이 검증
    if len(password) < 8:
        flash('비밀번호는 8자 이상이어야 합니다.', 'error')
        return redirect(url_for('register'))
        
    conn = None
    try:
        conn = pymysql.connect(**db_config)
        cursor = conn.cursor()
            
        # 이메일 중복 확인
        cursor.execute("SELECT email FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            flash('이미 사용 중인 이메일입니다.', 'error')
            return redirect(url_for('register'))
            
        # 비밀번호 해싱
        hashed_password = generate_password_hash(password)
        
        # 사용자 등록
        cursor.execute(
            "INSERT INTO users (email, password, nickname) VALUES (%s, %s, %s)",
            (email, hashed_password, nickname)
        )
        conn.commit()
            
        flash('회원가입이 완료되었습니다! 로그인해주세요.', 'success')
        return redirect(url_for('login'))
        
    except Exception as e:
        flash(f'회원가입 중 오류가 발생했습니다: {str(e)}', 'error')
        return redirect(url_for('register'))
    finally:
        if conn:
            conn.close()

    return render_template('register.html')

# 로그인 라우트
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        
    if not email or not password:
        flash('이메일과 비밀번호를 입력해주세요.', 'error')
        return redirect(url_for('login'))
        
    conn = None
    try:
        conn = pymysql.connect(**db_config)
        cursor = conn.cursor()
            
        # 사용자 조회
        cursor.execute(
            "SELECT user_id, email, password, nickname FROM users WHERE email = %s",
            (email,)
        )
        user_data = cursor.fetchone()
        
        if not user_data:
            flash('이메일 또는 비밀번호가 일치하지 않습니다.', 'error')
            return redirect(url_for('login'))
            
        # 비밀번호 검증
        if not check_password_hash(user_data[2], password):
            flash('이메일 또는 비밀번호가 일치하지 않습니다.', 'error')
            return redirect(url_for('login'))

        # 로그인 처리
        user = User(user_data[0], user_data[1], user_data[3])
        login_user(user)
            
        # 마지막 로그인 시간 업데이트
        cursor.execute(
            "UPDATE users SET last_login = %s WHERE user_id = %s",
            (datetime.now(), user.id)
        )
        conn.commit()

        flash(f'{user.nickname}님, 환영합니다! 🎉', 'success')
        return redirect(url_for('index'))
      
    except Exception as e:
        flash(f'로그인 중 오류가 발생했습니다: {str(e)}', 'error')
        return redirect(url_for('login'))
    finally:
        if conn:
            conn.close()
    
    return render_template('login.html')
    
# 로그아웃 라우트
@app.route('/logout')
@login_required
def logout():
    nickname = current_user.nickname
    logout_user()
    flash(f'{nickname}님, 안전하게 로그아웃되었습니다.', 'info')
    return redirect(url_for('login'))

# 실행
if __name__ == '__main__':

    # 웹드라이버가 HTTPS 통신을 수행하므로 SSL 인증서 검증 우회 코드를 main 실행 전에 유지
    ssl._create_default_https_context = ssl._create_unverified_context
    
    app_instance = App()
    app_instance.run(debug=True)