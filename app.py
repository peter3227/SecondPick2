import ssl
import time
import re
import json
import random
import pymysql
from urllib.parse import quote
from datetime import datetime, timedelta

# Selenium
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Flask
from flask import Flask, render_template, request, session, redirect, url_for, flash, get_flashed_messages
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# 1. DB 설정 (⚠️ 실제 운영시 비밀번호 보안에 유의)
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': 'peter3227',
    'db': 'joongna_db',
    'charset': 'utf8mb4'
}

# 2. Flask 앱 및 Flask-Login 설정
app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production' 

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = '로그인이 필요한 서비스입니다.'

# 3. 환경 설정 및 상수 관리
class AppConfig:
    MOBILE_USER_AGENTS = [
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
        'Mozilla/5.0 (Linux; Android 14; SM-S901B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36',
    ]
    DEFAULT_WINDOW_SIZE = (414, 896)
    DEFAULT_LATITUDE = 37.4979
    DEFAULT_LONGITUDE = 127.0276
    DEFAULT_TIMEOUT = 10

# 4. 유틸리티 함수 (WebDriver 외부 기능)
class Utils:
    @staticmethod
    def format_currency(value):
        try:
            if isinstance(value, str):
                value = str(value).replace(',', '')
            return f"{int(value):,}"
        except:
            return str(value)

    @staticmethod
    def clean_price_string(price_raw):
        price_raw = str(price_raw).strip()
        if '만' in price_raw:
            price_str = price_raw.split('만')[0].replace(',', '').strip()
            try:
                return int(float(price_str) * 10000)
            except ValueError:
                return 0
        if any(substring in price_raw.lower() for substring in ['나눔', '무료', '가격없음', '판매완료', '예약중']):
            return 0
        price_str = re.sub(r'[^\d]', '', price_raw)
        return int(price_str) if price_str.isdigit() and len(price_str) < 15 else 0

    @staticmethod
    def calculate_time_ago(date_string):
        now = datetime.now()
        date_string = date_string.strip()
        if any(unit in date_string for unit in ["분 전", "시간 전", "일 전", "주 전", "방금 전"]):
            return date_string
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
        except ValueError:
            pass
        return date_string

app.jinja_env.filters['format_currency'] = Utils.format_currency

# 5. WebDriver 관리
class WebDriverFactory:
    @staticmethod
    def get_driver():
        print("🌐 WebDriver 초기화 (undetected-chromedriver 사용)")
        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument('--headless')
        selected_user_agent = random.choice(AppConfig.MOBILE_USER_AGENTS)
        options.add_argument(f"user-agent={selected_user_agent}")
        driver = None
        try:
            driver = uc.Chrome(options=options)
            driver.set_window_size(*AppConfig.DEFAULT_WINDOW_SIZE)
            try:
                driver.execute_cdp_cmd(
                    "Emulation.setGeolocationOverride",
                    {"latitude": AppConfig.DEFAULT_LATITUDE, "longitude": AppConfig.DEFAULT_LONGITUDE, "accuracy": 100}
                )
            except Exception as e:
                print(f"위치 정보 설정 실패: {e}")
            return driver
        except Exception as e:
            print(f"❌ WebDriver 초기화 오류: {e}. 'undetected-chromedriver' 설치 상태를 확인해 주세요.")
            if driver: driver.quit()
            return None

# 6. 스크래퍼 베이스 및 플랫폼별 스크래퍼 (로직 유지)
class ScraperBase:
    PLATFORM_NAME = "Unknown"
    def __init__(self, driver): self.driver = driver
    def run_crawl(self, keyword): raise NotImplementedError("Subclass must implement abstract method")
    def _parse_item(self, **kwargs):
        return {
            'platform': self.PLATFORM_NAME, 'title': kwargs.get('title', ''),
            'price': kwargs.get('price', 0), 'link': kwargs.get('link', ''),
            'img_url': kwargs.get('img_url', "https://via.placeholder.com/150?text=No+Image"),
            'date_posted': kwargs.get('date_posted', '날짜 정보 없음')
        }

class JoongnaScraper(ScraperBase):
    PLATFORM_NAME = "중고나라"
    def run_crawl(self, keyword):
        crawled_data = []
        try:
            url = f"https://web.joongna.com/search/{quote(keyword)}"
            self.driver.get(url)
            time.sleep(3) 
            items = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/product/']")
            for item in items[:10]:
                try:
                    full_text = item.text.split('\n')
                    title = full_text[0].strip()
                    if not title or title == '판매하기': continue
                    price_raw = full_text[1] if len(full_text) > 1 else "0원"
                    clean_price = Utils.clean_price_string(price_raw)
                    if clean_price == 0: continue
                    link = item.get_attribute('href')
                    date_posted = "날짜 정보 없음"
                    try:
                        date_elem = item.find_element(By.CSS_SELECTOR, 'span.product-card-extra')
                        date_posted_raw = date_elem.text.split('·')[-1].strip()
                        date_posted = Utils.calculate_time_ago(date_posted_raw)
                    except: pass
                    img_url = "https://via.placeholder.com/150?text=No+Image"
                    try:
                        img_tag = item.find_element(By.TAG_NAME, 'img')
                        img_url = img_tag.get_attribute('src')
                    except: pass
                    crawled_data.append(self._parse_item(
                        title=title, price=clean_price, link=link, img_url=img_url, date_posted=date_posted
                    ))
                except Exception: continue
        except Exception as e:
            print(f"❌ 중고나라 크롤링 중 치명적인 오류 발생: {e}")
        return crawled_data

class DanggeunScraper(ScraperBase):
    PLATFORM_NAME = "당근마켓"
    def run_crawl(self, keyword):
        crawled_data = []
        encoded_keyword = quote(keyword)
        url = f"https://www.daangn.com/search/{encoded_keyword}"
        try:
            self.driver.get(url)
            time.sleep(random.uniform(3, 5))
            page_source = self.driver.page_source
            json_match = re.search(r'<script type="application/ld\+json">(.*?)</script>', page_source, re.DOTALL)
            if not json_match: return []
            data = json.loads(json_match.group(1).strip())
            if 'itemListElement' not in data: return []
            for list_item in data['itemListElement'][:10]:
                try:
                    item_data = list_item['item']
                    offer = item_data['offers']
                    title = item_data['name']
                    link = item_data['url']
                    img_url = item_data.get('image', "https://via.placeholder.com/150?text=No+Image")
                    price_raw = offer.get('price', '0')
                    availability = offer.get('availability', '')
                    if 'OutOfStock' in availability or float(price_raw) == 0: continue
                    clean_price = int(float(price_raw))
                    crawled_data.append(self._parse_item(
                        title=title, price=clean_price, link=link, img_url=img_url, date_posted="날짜 정보 없음"
                    ))
                except Exception: continue
        except Exception as e:
            print(f"❌ 당근마켓 크롤링 중 치명적인 오류 발생: {e}")
        return crawled_data

class BunjangScraper(ScraperBase):
    PLATFORM_NAME = "번개장터"
    def run_crawl(self, keyword): return []

# 7. User 클래스 정의 및 Flask-Login 콜백
class User(UserMixin):
    def __init__(self, user_id, email, nickname):
        self.id = user_id
        self.email = email
        self.nickname = nickname

@login_manager.user_loader
def load_user(user_id):
    conn = None
    try:
        conn = pymysql.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, email, nickname FROM users WHERE user_id = %s", (user_id,))
        user_data = cursor.fetchone()
        if user_data: return User(user_data[0], user_data[1], user_data[2])
    except Exception as e:
           print(f"❌ 사용자 로드 오류: {e}")
    finally:
        if conn: conn.close()
    return None

# 8. 검색 및 통계 처리 헬퍼 함수
def _calculate_platform_stats(items):
    prices = [item['price'] for item in items if item['price'] > 0]
    if not prices: return {'avg_price': 0, 'num_items': 0}
    avg = int(sum(prices) / len(prices))
    return {'avg_price': avg, 'num_items': len(prices)}

def _get_sorted_items_and_stats(keyword, sort_by):
    all_items = session.get('all_items', [])
    platform_stats = session.get('platform_stats', {})
    is_new_search = keyword and (keyword != session.get('last_keyword') or not all_items)
    
    if is_new_search:
        driver = None
        try:
            driver = WebDriverFactory.get_driver()
            if driver:
                joongna_items = JoongnaScraper(driver).run_crawl(keyword)
                danggeun_items = DanggeunScraper(driver).run_crawl(keyword)
            else:
                joongna_items = []
                danggeun_items = []
            bunjang_items = BunjangScraper(None).run_crawl(keyword) 
            all_items = joongna_items + danggeun_items + bunjang_items
            platform_stats['중고나라'] = _calculate_platform_stats(joongna_items)
            platform_stats['당근마켓'] = _calculate_platform_stats(danggeun_items)
            platform_stats['번개장터'] = _calculate_platform_stats(bunjang_items)
            session['all_items'] = all_items
            session['last_keyword'] = keyword
            session['platform_stats'] = platform_stats
        finally:
            if driver: driver.quit()
    elif not keyword:
        all_items = []
        platform_stats = {}

    min_price, max_price, avg_price_all = 0, 0, 0
    if all_items:
        valid_prices = [item['price'] for item in all_items if item['price'] > 0]
        if valid_prices:
            min_price = min(valid_prices)
            max_price = max(valid_prices)
            avg_price_all = int(sum(valid_prices) / len(valid_prices))
        if sort_by == 'low_price':
            all_items.sort(key=lambda x: x['price'])
        elif sort_by == 'high_price':
            all_items.sort(key=lambda x: x['price'], reverse=True)

    return all_items, platform_stats, min_price, max_price, avg_price_all

# 9. 메인 라우트
@app.route('/', methods=['GET'])
def index():
    keyword = request.args.get('keyword')
    sort_by = request.args.get('sort', 'latest')

    all_items, platform_stats, min_price, max_price, avg_price_all = \
        _get_sorted_items_and_stats(keyword, sort_by)
    
    user_id = current_user.get_id() if current_user.is_authenticated else None
    
    return render_template('index.html',
                           items=all_items,
                           keyword=keyword,
                           platform_stats=platform_stats,
                           sort_by=sort_by,
                           min_price=min_price,
                           max_price=max_price,
                           avg_price_all=avg_price_all,
                           user_id=user_id) 

# 10. 로그인/로그아웃, 회원가입 라우트 (페이지 이동 방식 적용)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        nickname = request.form.get('nickname', '').strip()
    
        if not email or not password or not nickname:
            flash('모든 항목을 입력해주세요.', 'error')
            return redirect(url_for('register')) 
            
        if len(password) < 8:
            flash('비밀번호는 8자 이상이어야 합니다.', 'error')
            return redirect(url_for('register'))
            
        conn = None
        try:
            conn = pymysql.connect(**db_config)
            cursor = conn.cursor()
                
            cursor.execute("SELECT email FROM users WHERE email = %s", (email,))
            if cursor.fetchone():
                flash('이미 사용 중인 이메일입니다.', 'error')
                return redirect(url_for('register'))
                
            hashed_password = generate_password_hash(password)
            
            cursor.execute(
                "INSERT INTO users (email, password, nickname, created_at) VALUES (%s, %s, %s, NOW())",
                (email, hashed_password, nickname)
            )
            conn.commit()
                
            flash('회원가입이 완료되었습니다! 로그인해주세요.', 'success')
            return redirect(url_for('login')) # ⬅️ 로그인 페이지로 이동
            
        except Exception as e:
            flash(f'회원가입 중 오류가 발생했습니다: {str(e)}', 'error')
            return redirect(url_for('register'))
        finally:
            if conn: conn.close()

    # ⬅️ GET 요청 시: register.html을 렌더링
    return render_template('register.html') 

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
                
            cursor.execute(
                "SELECT user_id, email, password, nickname FROM users WHERE email = %s",
                (email,)
            )
            user_data = cursor.fetchone()
            
            if not user_data or not check_password_hash(user_data[2], password):
                flash('이메일 또는 비밀번호가 일치하지 않습니다.', 'error')
                return redirect(url_for('login'))

            user = User(user_data[0], user_data[1], user_data[3])
            login_user(user)
                
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
            if conn: conn.close()
    
    # ⬅️ GET 요청 시: login.html을 렌더링
    return render_template('login.html')
    
@app.route('/logout', methods=['POST'])
@login_required
def logout():
    nickname = current_user.nickname
    logout_user()
    flash(f'{nickname}님, 안전하게 로그아웃되었습니다.', 'info')
    return redirect(url_for('index'))

# 11. 실행
if __name__ == '__main__':
    ssl._create_default_https_context = ssl._create_unverified_context
    app.run(debug=True)