import ssl

# SSL 인증서 검증 실패를 무시하고 진행하도록 설정
ssl._create_default_https_context = ssl._create_unverified_context

import time
from flask import Flask, render_template, request
from datetime import datetime, timedelta 

# WebDriver는 중고나라, 당근마켓에만 사용
import undetected_chromedriver as uc 
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.support.ui import WebDriverWait 
from selenium.webdriver.support import expected_conditions as EC 

import sys
import re
import json 
import random 
import requests 
from requests.packages.urllib3.exceptions import InsecureRequestWarning 
from urllib.parse import quote 


# 터미널 인코딩 문제 방지
sys.stdout.reconfigure(encoding='utf-8')

app = Flask(__name__)

# --- Jinja2 필터 등록 (가격 포맷) ---
def format_currency(value):
    """숫자를 통화 형식 문자열로 포맷하는 헬퍼 함수"""
    try:
        if isinstance(value, str):
            value = str(value).replace(',', '')
        if int(value) > 100000000: 
             return "0"
        return f"{int(value):,}"
    except:
        return str(value)

app.jinja_env.filters['format_currency'] = format_currency


# --- 1. WebDriver 및 유틸리티 함수 ---

def get_webdriver():
    """undetected_chromedriver를 사용하여 봇 탐지를 우회하는 웹드라이버를 반환합니다."""
    print("🌐 WebDriver 초기화 (undetected-chromedriver 사용)")
    
    options = uc.ChromeOptions() 
    
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-blink-features=AutomationControlled") 
    options.add_argument('--headless') 

    mobile_user_agents = [
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
        'Mozilla/5.0 (Linux; Android 14; SM-S901B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36',
    ]
    selected_user_agent = random.choice(mobile_user_agents)
    options.add_argument(f"user-agent={selected_user_agent}")
    
    driver = None
    try:
        driver = uc.Chrome(options=options)
        driver.set_window_size(414, 896) 
        
        try:
             driver.execute_cdp_cmd(
                "Emulation.setGeolocationOverride",
                {
                    "latitude": 37.4979, 
                    "longitude": 127.0276, 
                    "accuracy": 100
                }
            )
        except Exception as e:
            print(f"위치 정보 설정 실패: {e}")
            
        return driver
    except Exception as e:
        print(f"❌ WebDriver 초기화 오류: {e}. 'undetected-chromedriver' 설치 상태를 확인해 주세요.")
        return None

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
    return int(price_str) if price_str.isdigit() and len(price_str) < 15 else 0


# --- New Helper Function: 시간 차이 계산 ---
def calculate_time_ago(date_string):
    """
    중고나라/당근마켓의 시간/날짜 문자열을 파싱하여 'X분 전' 또는 'X시간 전'으로 변환
    """
    now = datetime.now()
    date_string = date_string.strip()

    if "분 전" in date_string:
        minutes = int(re.sub(r'[^\d]', '', date_string))
        return f"{minutes}분 전"
    
    if "시간 전" in date_string:
        hours = int(re.sub(r'[^\d]', '', date_string))
        return f"{hours}시간 전"

    # 당근마켓: '3일 전', '1주 전' 처리
    if "일 전" in date_string:
        days = int(re.sub(r'[^\d]', '', date_string))
        if days == 0: return "1시간 전"
        return f"{days}일 전"
    
    if "주 전" in date_string:
        weeks = int(re.sub(r'[^\d]', '', date_string))
        return f"{weeks}주 전"

    # 중고나라: '방금 전' 또는 '1분 이내' 처리
    if "방금 전" in date_string or "1분 이내" in date_string:
        return "방금 전"
        
    # 중고나라: 'yyyy.mm.dd' 형식 (예: 2025.11.26)
    try:
        if len(date_string) == 10 and date_string.count('.') == 2:
            post_date = datetime.strptime(date_string, "%Y.%m.%d")
            diff = now - post_date
            
            if diff.days == 0:
                # 오늘 날짜지만 시간이 명시되지 않았으므로 '오늘'로 표시
                return "오늘"
            elif diff.days < 7:
                return f"{diff.days}일 전"
            else:
                return date_string # 7일 이상이면 원래 날짜 문자열 유지
    except:
        pass
    
    return date_string


# --- 2. 중고나라 크롤링 함수 (시간 차이 계산 적용) ---
def run_joongna_crawl(keyword, driver):
    crawled_data = []
    
    try:
        url = f"https://web.joongna.com/search/{keyword}"
        driver.get(url)
        time.sleep(3) 
        
        items = driver.find_elements(By.CSS_SELECTOR, "a[href*='/product/']") 
        
        for item in items[:10]: 
            try:
                full_text = item.text.split('\n')
                title = full_text[0].strip()
                
                if not title or title == '판매하기': 
                    continue

                price_raw = full_text[1] if len(full_text) > 1 else "0원"
                clean_price = clean_price_string(price_raw)
                
                if clean_price == 0:
                    continue
                    
                link = item.get_attribute('href')
                
                date_posted = "날짜 정보 없음"
                try:
                    date_elem = item.find_element(By.CSS_SELECTOR, 'span.product-card-extra')
                    # 중고나라는 '지역 · 시간' 형식에서 시간 부분 추출
                    date_posted_raw = date_elem.text.split('·')[-1].strip() 
                    date_posted = calculate_time_ago(date_posted_raw) # <<<--- 시간 차이 계산 적용
                except:
                    pass

                img_url = "https://via.placeholder.com/150?text=No+Image" 
                try:
                    img_tag = item.find_element(By.TAG_NAME, 'img')
                    img_url = img_tag.get_attribute('src')
                except Exception:
                    pass

                crawled_data.append({
                    'platform': '중고나라', 
                    'title': title,
                    'price': clean_price,      
                    'link': link,
                    'img_url': img_url,
                    'date_posted': date_posted # <<<--- 변환된 시간 정보
                })
            except Exception as e:
                continue
             
    except Exception as e:
        print(f"❌ 중고나라 크롤링 중 치명적인 오류 발생: {e}")
    
    return crawled_data


# --- 3. 당근마켓 크롤링 함수 (JSON-LD 유지) ---
def run_danggeun_crawl(keyword, driver):
    crawled_data = []
    
    encoded_keyword = quote(keyword)
    url = f"https://www.daangn.com/search/{encoded_keyword}" 
    
    print(f"✅ 당근마켓 PC 웹 크롤링 시작 (JSON-LD 파싱): {url}")
    
    try:
        driver.get(url)
        
        time.sleep(random.uniform(3, 5)) 
        page_source = driver.page_source
        
        json_match = re.search(r'<script type="application/ld\+json">(.*?)</script>', page_source, re.DOTALL)
        
        if not json_match:
            print("🚨🚨🚨 당근마켓: JSON-LD 스크립트 태그를 찾을 수 없습니다. (크롤링 실패) 🚨🚨🚨")
            return []
            
        json_ld_string = json_match.group(1).strip()
        
        try:
            data = json.loads(json_ld_string)
        except json.JSONDecodeError as e:
            print(f"❌ 당근마켓: JSON-LD 데이터 파싱 오류가 발생했습니다. {e}")
            return []

        if 'itemListElement' not in data:
            print("⚠️ 당근마켓: JSON-LD에 itemListElement가 없습니다. (검색 결과 0건 또는 구조 변경) ⚠️")
            return []
            
        for list_item in data['itemListElement'][:10]:
            try:
                item_data = list_item['item']
                
                title = item_data['name']
                link = item_data['url']
                img_url = item_data['image']
                
                offer = item_data['offers']
                price_raw = offer.get('price', '0')
                availability = offer.get('availability', '')
                
                if 'OutOfStock' in availability or float(price_raw) == 0:
                    continue

                # JSON-LD로는 정확한 'X분 전' 시간 정보를 얻을 수 없어 임시 문자열 사용
                date_posted = "날짜 정보 없음" 

                clean_price = int(float(price_raw))
                
                crawled_data.append({
                    'platform': '당근마켓', 
                    'title': title,
                    'price': clean_price,      
                    'link': link,
                    'img_url': img_url,
                    'date_posted': date_posted 
                })
            except Exception as e:
                continue
             
    except Exception as e:
        print(f"❌ 당근마켓 크롤링 중 치명적인 오류 발생: {e}")
    
    return crawled_data


# --- 4. 번개장터 크롤링 함수 (제외 유지) ---
def run_bunjang_crawl(keyword):
    print("✅ 번개장터 크롤링 제외됨")
    return []

# --- 5. 메인 라우트 통합 ---
@app.route('/', methods=['GET'])
def index():
    keyword = request.args.get('keyword')
    all_items = []
    platform_stats = {}
    
    joongna_items = []
    danggeun_items = []
    bunjang_items = []

    if keyword:
        driver = None
        try:
            # 1. WebDriver 초기화 (중고나라/당근마켓용)
            driver = get_webdriver() 
            if driver:
                joongna_items = run_joongna_crawl(keyword, driver)
                danggeun_items = run_danggeun_crawl(keyword, driver)
            
            # 2. 번개장터 크롤링 시도 (제외됨)
            bunjang_items = run_bunjang_crawl(keyword) 

            all_items.extend(joongna_items)
            all_items.extend(danggeun_items)
            all_items.extend(bunjang_items)


            # --- 플랫폼별 통계 계산 ---
            def calculate_stats(items):
                prices = [item['price'] for item in items if item['price'] > 0]
                if not prices:
                    return {'avg_price': 0, 'num_items': 0}
                
                avg = int(sum(prices) / len(prices))
                return {
                    'avg_price': avg,
                    'num_items': len(prices)
                }

            platform_stats['중고나라'] = calculate_stats(joongna_items)
            platform_stats['당근마켓'] = calculate_stats(danggeun_items)
            platform_stats['번개장터'] = calculate_stats(bunjang_items) 

        finally:
            if driver:
                driver.quit() 


    # --- 정렬 ---
    sort_by = request.args.get('sort', 'latest') 
    if all_items:
        if sort_by == 'low_price':
            all_items.sort(key=lambda x: x['price'])
        elif sort_by == 'high_price':
            all_items.sort(key=lambda x: x['price'], reverse=True)


    return render_template('index.html', 
                           items=all_items, 
                           keyword=keyword, 
                           platform_stats=platform_stats,
                           sort_by=sort_by)

if __name__ == '__main__':
    # 기본 Flask 서버 실행
    app.run(debug=True)