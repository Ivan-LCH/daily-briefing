# -----------------------------------------------------------------------------------------------------------------------------#
# Import
# -----------------------------------------------------------------------------------------------------------------------------#

import os
import time
import json
import re
import schedule
import smtplib
import feedparser
import trafilatura
import urllib.parse
import requests
import yfinance as yf

from datetime import datetime, timedelta
from email.mime.text import MIMEText
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi

import google.generativeai as genai
import video_studio
import youtube_manager
import glob

import pandas_market_calendars as mcal
import pytz

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

# -----------------------------------------------------------------------------------------------------------------------------#
# Set Environment
# -----------------------------------------------------------------------------------------------------------------------------#

GOOGLE_API_KEY  = os.getenv('GOOGLE_API_KEY')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
EMAIL_SENDER    = os.getenv('EMAIL_SENDER')
EMAIL_PASSWORD  = os.getenv('EMAIL_PASSWORD')

genai.configure(api_key=GOOGLE_API_KEY)




# -----------------------------------------------------------------------------------------------------------------------------#
# Find AI Model
# -----------------------------------------------------------------------------------------------------------------------------#

def get_working_model():
    print("🤖 AI 모델 연결 시도 중...")
    try:
        valid_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                valid_models.append(m.name)

        # 우선순위: Flash (Batch 유리) -> Pro -> 구형
        preference = ['flash', '1.5-pro', 'gemini-pro']
        selected_model = None

        for pref in preference:
            for m_name in valid_models:
                if pref in m_name:
                    selected_model = m_name
                    break
            if selected_model: break

        if not selected_model and valid_models:
            selected_model = valid_models[0]

        print(f"  ✅ 최종 선택된 모델: {selected_model}")
        return genai.GenerativeModel(selected_model)
    except:
        return genai.GenerativeModel('gemini-pro')

model = get_working_model()



# -----------------------------------------------------------------------------------------------------------------------------#
# Get Config
# -----------------------------------------------------------------------------------------------------------------------------#

def load_config():
    if not os.path.exists('config.json'): return None
    
    with open('config.json', 'r', encoding='utf-8') as f:
        return json.load(f)



# -----------------------------------------------------------------------------------------------------------------------------#
# --- 공통 유틸: 자막 추출 (타임스탬프) ---
# -----------------------------------------------------------------------------------------------------------------------------#

def get_timed_transcript(video_id):
    try:
        transcript  = YouTubeTranscriptApi.get_transcript(video_id, languages=['ko', 'ko-KR', 'en', 'auto'])
        script_data = ""

        for entry in transcript:
            time_str = f"[{int(entry['start'])//60:02d}:{int(entry['start'])%60:02d}]"
            script_data += f"{time_str} {entry['text']}\n"

        return script_data

    except: 
        return None



# -----------------------------------------------------------------------------------------------------------------------------#
# --- 1. 뉴스 수집 (24시간 & 메이저) ---
# -----------------------------------------------------------------------------------------------------------------------------#

def fetch_news_raw(keywords, limit=2):
    print(f"📰 해외 메이저 뉴스 수집 중...")
    news_data = []
    headers   = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    for keyword in keywords:
        try:
            encoded = urllib.parse.quote(keyword)
            # hl=en-US, gl=US -> 미국판 뉴스 (메이저 외신 우선)
            url = f"https://news.google.com/rss/search?q={encoded}+when:1d&hl=en-US&gl=US&ceid=US:en"
            
            feed  = feedparser.parse(url)
            count = 0

            for entry in feed.entries:
                if count >= limit: break
                
                content = ""
                try:
                    res     = requests.get(entry.link, headers=headers, timeout=3)
                    content = trafilatura.extract(res.text)
                except: pass
                
                raw_text = content if content else entry.description
                if not raw_text or len(raw_text) < 50: continue
                
                clean_text = trafilatura.utils.sanitize(raw_text)[:4000]
                
                news_data.append({
                    'query'   : keyword,
                    'title'   : entry.title,
                    'url'     : entry.link,
                    'content' : clean_text
                })
                count += 1
            print(f"  - [{keyword}] {count}건 확보")

        except: pass

    return news_data


# -----------------------------------------------------------------------------------------------------------------------------#
# 1. Market Status Check (사용자 요청 로직 복원)
# -----------------------------------------------------------------------------------------------------------------------------#

def check_market_status():
    """
    pandas_market_calendars를 이용하여 정밀하게 휴장일을 판단합니다.
    """
    try:
        # 1. NYSE(뉴욕증권거래소) 달력 로드
        nyse         = mcal.get_calendar('NYSE')
        
        # 2. 현재 시간을 뉴욕 시간(US/Eastern)으로 변환
        now_utc      = datetime.now(pytz.utc)
        ny_tz        = pytz.timezone('US/Eastern')
        now_ny       = now_utc.astimezone(ny_tz)
        current_date = now_ny.date()
        
        # 3. 오늘 날짜가 스케줄에 있는지 확인
        schedule     = nyse.schedule(start_date=current_date, end_date=current_date)
        
        # 스케줄이 비어있으면(Empty) 휴장일(주말/공휴일)
        if schedule.empty:
            print(f"⛔ [Market Check] 미 증시 휴장일입니다. (NY Date: {current_date})")
            return False
            
        print(f"✅ [Market Check] 미 증시 개장일입니다. (NY Date: {current_date})")
        return True
        
    except Exception as e:
        print(f"⚠️ 마켓 캘린더 확인 중 에러: {e}")
        # 에러 발생 시 보수적으로 yfinance 데이터 유무로 2차 확인
        try:
            spy = yf.Ticker("SPY")
            return not spy.history(period="1d").empty
        except:
            return False


# -----------------------------------------------------------------------------------------------------------------------------#
# 2. Data Collection (경제 지표 검색 추가 & 포맷 고정)
# -----------------------------------------------------------------------------------------------------------------------------#

def collect_stock_data(tickers):
    print("📈 주식 데이터 수집 중...")
    stock_data     = []
    is_market_open = check_market_status()

    for symbol in tickers:
        try:
            # 뉴스 수집 (기존 로직 유지)
            related_news = fetch_news_raw([f"{symbol} stock news", f"{symbol} analysis"], limit=2)
            
            if is_market_open:
                ticker = yf.Ticker(symbol)
                h = ticker.history(period="5d")
                
                if len(h) >= 2:
                    last       = h['Close'].iloc[-1]
                    prev       = h['Close'].iloc[-2]
                    diff       = last - prev
                    pct        = (diff / prev) * 100
                    
                    price_str  = f"${last:.2f}"
                    # [요청] 증감량 (증감률) 포맷: -15.55 (-3.27%)
                    change_str = f"{diff:+.2f} ({pct:+.2f}%)"
                else:
                    price_str  = "N/A"
                    change_str = "0.00 (0.00%)"
            else:
                price_str  = "N/A"
                change_str = "Market Closed"

            stock_data.append({
                'symbol'     : symbol,
                'price'      : price_str,
                'change_str' : change_str,
                'news_items' : related_news
            })
            print(f"  - [{symbol}] {price_str} / {change_str}")
        except:
            pass
    return stock_data


# -----------------------------------------------------------------------------------------------------------------------------#
# [신규] 공신력 있는 데이터를 위한 검색 함수
# -----------------------------------------------------------------------------------------------------------------------------#

def collect_economy_data():
    print("🌍 경제 지표 및 일정 검색 중...")
    queries = [
        "CNN Fear and Greed Index current score today",
        "Major US Economic Calendar events this week",
        "US Stock Market Sector Performance today"
    ]
    # 기존 fetch_news_raw 활용 (구글 검색 결과 반환)
    return fetch_news_raw(queries, limit=5)



# -----------------------------------------------------------------------------------------------------------------------------#
# --- 3. 채널 기반 유튜브 수집 (24시간 이내) ---
# -----------------------------------------------------------------------------------------------------------------------------#

def collect_channel_youtube_data(channels_dict):
    print("🎥 유튜브 채널 수집 중...")
    youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
    video_data = []
    now = datetime.utcnow()

    for name, channel_id in channels_dict.items():
        try:
            res        = youtube.channels().list(id=channel_id, part='contentDetails').execute()
            uploads_id = res['items'][0]['contentDetails']['relatedPlaylists']['uploads']

            pl_res     = youtube.playlistItems().list(
                playlistId = uploads_id,
                part       = 'snippet',
                maxResults = 5
            ).execute()
            
            if not pl_res.get('items'): continue

            for item in pl_res['items']: 
                vid          = item['snippet']['resourceId']['videoId']
                title        = item['snippet']['title']
                pub_date_str = item['snippet']['publishedAt']
                
                # 24시간 이내
                pub_date_dt = datetime.strptime(pub_date_str, "%Y-%m-%dT%H:%M:%SZ")
                if (now - pub_date_dt).total_seconds() > 24 * 3600:
                    continue
                
                pub_date_kst = (pub_date_dt + timedelta(hours=9)).strftime("%Y-%m-%d")
                transcript   = get_timed_transcript(vid)
                content      = transcript[:40000] if transcript else f"(자막 없음) {item['snippet']['description'][:1000]}"

                video_data.append({
                    'type'          : 'channel',
                    'source'        : name,
                    'channel_name'  : name, # [Fix] Page 5를 위해 명시적으로 추가
                    'title'         : title,
                    'date'          : pub_date_kst,
                    'url'           : f"https://www.youtube.com/watch?v={vid}",
                    'content'       : content
                })
                print(f"   - [{name}] 확보: {title}")
                break 
        except: pass
        
    return video_data



# -----------------------------------------------------------------------------------------------------------------------------#
# 4. AI 편집장: 주식 및 뉴스 요약 (One-Source Multi-Use)
# -----------------------------------------------------------------------------------------------------------------------------#

def analyze_and_summarize(stocks, news, youtube, economy_news):
    print("🧠 AI 편집장: 데이터 분석 및 방송 대본(Script) 집필 중...")
    
    today_date = datetime.now().strftime("%m월 %d일")
    
    if not stocks and not news and not youtube:
        return stocks, news, youtube

    # Raw Data 준비
    raw_context = json.dumps({
        'stocks'               : [ {'symbol': s['symbol'], 'price': s['price'], 'change': s['change_str'], 'news': s.get('news_items', [])} for s in stocks ], 
        'news'                 : news[:5],
        'youtube'              : youtube[:5],
        'economy_search_result': economy_news
    }, ensure_ascii=False)
    
    prompt = f"""
    당신은 월가(Wall St.)의 수석 애널리스트입니다. 제공된 주식/뉴스 데이터를 철저히 분석하여 JSON을 작성하세요.
    **절대 없는 사실을 지어내지 마십시오.**
    **[경제 지표]와 [섹터 동향]은 반드시 'economy_search_result'의 검색 결과에서 팩트를 찾아 기입하십시오.**

    [데이터]
    {raw_context}
    
    [지시사항 1: 데이터 분석 (Visual & Email Data)]
    1. stock_details: 리스트의 모든 주식에 대해 작성.
       A. **video_summary (영상 자막용)**: 
          - 길이: **2문장 내외(40~60자)**. 
          - 내용: 등락의 구체적인 이유(뉴스 기반) 포함. 단순 사실 나열이 아니라 **"왜 올랐는지/내렸는지" 핵심 원인**을 반드시 포함할 것.
          - 예: "실적 호조와 엔비디아 파트너십 발표로 급등했습니다." (O) / "소폭 상승했습니다." (X)

       B. **email_summary (이메일 리포트용)**:
          - 길이: **3~4문장의 깊이 있는 분석**.
          - 내용: 해당 종목과 직접 관련된 뉴스(계약, 실적, CEO 발언, 거시경제 영향)를 찾아 인과관계를 설명.
          - **주의:** 한국 국내 이슈(세제지원 등)를 미국 주식에 억지로 갖다 붙이지 마시오. 뉴스가 없으면 "특이 이슈 없음"이라고 솔직히 적으시오.
          - 형식: "~때문에 상승했습니다."와 같은 평서문.

    2. **economic_insight**:
       - **[경제 뉴스 검색 결과]**에서 팩트를 찾아내세요.
       - **fear_greed_index** (0~100 숫자): 검색 결과에서 확인된 'Fear & Greed Index' 현재 수치 (예: 65). 못 찾으면 "N/A".
       - **market_sentiment**: 수치에 따른 상태 (예: Greed). 못 찾으면 "N/A".
       - **calendar**: 검색 결과에 언급된 이번 주 주요 경제 일정 3가지. **반드시 날짜 포함할 것** (예: "CPI 발표 (2025-12-31)")
       - **sector_summary**: 검색 결과에서 파악된 오늘 상승/하락 주도 섹터 1줄 요약. (예: "기술주 강세, 에너지 약세")
    
    3. **news_items**: 
       - 제공된 뉴스 제목과 1문장 상세 내용(detail).
       - **주의:** 뉴스가 없으면 "특이 이슈 없음"이라고 솔직히 적으시오.

    4. **youtube_items**: 
       - 제공된 유튜브 영상의 제목 등을 보고 핵심 주제를 **1~2문장으로 요약**하세요.
    
    [지시사항 2: 방송 대본 (Audio Script)]
    - **실제 영상에서 읽어줄 내레이션 대본**을 작성하세요. (구어체, 해요체, 자연스럽게)
    - **문장이 너무 길어지지 않게 적절히 끊어서 작성하세요.**
    - **scripts** 객체 안에 씬별로 작성하세요.
       - **scene1 (Opening)**: "안녕하세요, {today_date} 데일리 브리핑입니다. 오늘 미 증시는..." (섹터/맵 분위기 언급)
       - **scene2 (News)**: "먼저 주요 뉴스입니다." (가장 중요한 뉴스 1~2개 헤드라인 언급)
       - **scene2_5 (Economy)**: "오늘의 경제 지표입니다." (공포지수 상태와 주요 일정 언급)
       - **scene3 (Stocks)**: "주요 종목 흐름입니다." (가장 등락이 큰 종목 1~2개 위주로 코멘트. *모든 종목을 다 읽지 말고 특징주 위주로 요약*)
       - **scene4 (Chart)**: "특히 주목할 종목은... (첫번째 종목)입니다." (차트 화면에서 읽을 멘트)
       - **scene5 (YouTube)**: "유튜브 인사이트입니다. (채널명)에서는..." (주요 영상 1개 언급)
       - **scene6 (Closing)**: "이상으로 브리핑을 마칩니다. 성공 투자를 기원합니다."

    [JSON 형식]
    {{
        "stock_details": [ ... ],
        "economic_insight": {{ ... }},
        "news_items": [ ... ],
        "youtube_items": [ ... ],
        "scripts": {{
            "scene1": "...",
            "scene2": "...",
            "scene2_5": "...",
            "scene3": "...",
            "scene4": "...",
            "scene5": "...",
            "scene6": "..."
        }}
    }}
    """

    try:
        res           = model.generate_content(prompt)
        text          = res.text.replace("```json", "").replace("```", "").strip()
        start         = text.find('{')
        end           = text.rfind('}')
        data          = json.loads(text[start:end+1])
        
        # 1. 데이터 매핑 (Visual Data)
        summary_map_v = {item['symbol']: item.get('video_summary', '') for item in data.get('stock_details', [])}
        summary_map_e = {item['symbol']: item.get('email_summary', '') for item in data.get('stock_details', [])}
        
        for s in stocks:
            s['video_summary'] = summary_map_v.get(s['symbol'], "분석 중...")
            s['email_summary'] = summary_map_e.get(s['symbol'], "특이사항 없음")
            s['analysis']      = s['email_summary']

        for i, n in enumerate(news):
            if i < len(data.get('news_items', [])):
                n['detail']    = data['news_items'][i].get('detail', '')
                
        for i, y in enumerate(youtube):
            if i < len(data.get('youtube_items', [])):
                y['summary']   = data['youtube_items'][i].get('summary', '')

        # 2. 대본 추출 (Audio Script)
        # scripts가 없으면 기본 멘트로 방어
        generated_scripts = data.get('scripts', {
            "scene1"  : f"{today_date} 증시 브리핑을 시작합니다.",
            "scene2"  : "주요 뉴스입니다.",
            "scene2_5": "경제 지표를 확인하겠습니다.",
            "scene3"  : "주요 종목 현황입니다.",
            "scene4"  : "차트 분석입니다.",
            "scene5"  : "유튜브 트렌드입니다.",
            "scene6"  : "시청해주셔서 감사합니다."
        })

        return stocks, news, youtube, data.get('economic_insight', {}), generated_scripts
        
    except Exception as e:
        print(f"⚠️ AI 분석/집필 실패: {e}")
        # 실패 시 기본 데이터 반환
        return stocks, news, youtube, {}, {}
        

# -----------------------------------------------------------------------------------------------------------------------------#
# [수정됨] 대본 작성 로직 (주식 데이터 없을 때 대응 추가)
# -----------------------------------------------------------------------------------------------------------------------------#

def plan_video_script(stocks, news, youtube):
    """ 이미 요약된 데이터를 바탕으로 대본(Script)만 작성 """
    print("📝 AI 작가: 영상 대본 작성 중...")
    
    # [수정] 주식이 하나도 없을 경우(휴장일) 대응 로직
    main_topic    = ""
    main_summary  = ""
    
    if stocks:
        target_stock = stocks[0]
        main_topic   = target_stock['symbol']
        main_summary = target_stock.get('analysis', '')
    elif news:
        # 주식이 없으면 첫 번째 뉴스를 메인으로
        main_topic   = "Global News"
        main_summary = news[0].get('summary', news[0]['title'])
    else:
        print("❌ 대본을 작성할 데이터가 부족합니다.")
        return None

    context = json.dumps({
        'main_topic'    : main_topic,
        'main_summary'  : main_summary,
        'news'          : [n.get('summary', n['title']) for n in news[:4]],
        'youtube'       : [y.get('summary', y['title']) for y in youtube[:4]]
    }, ensure_ascii=False)
    
    prompt = f"""
    아래 요약된 금융 데이터를 바탕으로 6단계 쇼츠 대본을 작성해.
    
    [데이터]
    {context}
    
    [구성]
    Scene 1 (Intro): 시장 상황 브리핑 및 오늘의 메인 주제({main_topic}) 언급.
    Scene 2 (News): 주요 뉴스 브리핑 (빠르게).
    Scene 3 (Main Topic): {main_topic} 집중 분석 소개.
    Scene 4 (Detail): {main_topic}에 대한 구체적 분석 멘트 ({main_summary}).
    Scene 5 (Reaction): 유튜브나 대중의 반응 전달.
    Scene 6 (Outro): 클로징 멘트 (투자 유의사항 포함).

    [JSON 반환]
    {{
        "title": "영상 제목 (자극적이고 흥미롭게)",
        "scene1": "대본 내용...", 
        "scene2": "...", 
        "scene3": "...", 
        "scene4": "...", 
        "scene5": "...", 
        "scene6": "..."
    }}
    """
    try:
        res       = model.generate_content(prompt)
        text      = res.text.replace("```json", "").replace("```", "").strip()
        
        start_idx = text.find('{')
        end_idx   = text.rfind('}')
        
        if start_idx != -1 and end_idx != -1:
            text = text[start_idx:end_idx+1]
            
        return json.loads(text)
    except Exception as e: 
        print(f"⚠️ 대본 작성 실패: {e}")
        return None



# -----------------------------------------------------------------------------------------------------------------------------#
# ---  5. 키워드 기반 트렌드 영상 수집 ---
# -----------------------------------------------------------------------------------------------------------------------------#

def collect_keyword_youtube_data(keywords):
    print("🔥 유튜브 트렌드 검색 중...")
    youtube     = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
    trend_data  = []
    
    # 24시간 전 시간 구하기
    yesterday   = (datetime.utcnow() - timedelta(days=1)).isoformat("T") + "Z"

    for keyword in keywords:
        try:
            # 검색 API 호출: 24시간 이내, 관련도 순
            req = youtube.search().list(
                part           = "snippet",
                q              = keyword,
                order          = "relevance", 
                publishedAfter = yesterday,
                type           = "video",
                maxResults     = 1
            )
            res = req.execute()
            
            if not res.get('items'): continue
            
            item           = res['items'][0]
            vid            = item['id']['videoId']
            title          = item['snippet']['title']
            channel_title  = item['snippet']['channelTitle']
            
            transcript     = get_timed_transcript(vid)
            content        = transcript[:40000] if transcript else f"(자막 없음) {item['snippet']['description'][:1000]}"

            trend_data.append({
                'type'          : 'keyword',
                'source'        : f"키워드: {keyword}",
                'channel_name'  : channel_title,
                'title'         : title,
                'url'           : f"https://www.youtube.com/watch?v={vid}",
                'content'       : content
            })
            print(f"  - [트렌드/{keyword}] 확보: {title}")
        except Exception as e:
            print(f"  - [트렌드/{keyword}] 에러: {e}")
            
    return trend_data



# -----------------------------------------------------------------------------------------------------------------------------#
# [NEW] 리포트 생성 함수 (사용자 원본 프롬프트 복원 + 일관성 지침 추가)
# -----------------------------------------------------------------------------------------------------------------------------#
def generate_report(stocks, general_news, channel_videos, trend_videos, video_url=None, economy_data=None):
    print("📝 CEO 맞춤형 심층 리포트 작성 중...")
    
    # 1. [Section 0] 영상 섹션 HTML (기존 동일)
    video_section_html = ""
    if video_url:
        video_section_html = f"""
        <h2>🎬 [Section 0] 오늘자 1분 요약 (Shorts)</h2>
        <p><b>💡 바쁘신 CEO를 위한 1분 브리핑:</b></p>
        <p>오늘의 핵심 이슈와 주가 변동 원인을 영상을 통해 빠르게 확인하세요.</p>
        <div style="background-color: #f8f9fa; padding: 20px; border-radius: 10px; text-align: center; border: 1px solid #e9ecef; margin: 15px 0;">
            <a href="{video_url}" style="font-size: 20px; font-weight: bold; color: #c0392b; text-decoration: none;">
                ▶️ 1분 브리핑 영상 재생하기 (Click)
            </a>
            <p style="color: #666; font-size: 0.9em; margin-top: 10px;">(유튜브 링크로 이동합니다)</p>
        </div>
        <hr style="border: 0; border-top: 1px dashed #ddd; margin: 30px 0;">
        """
    elif not stocks:
        video_section_html = """
        <h2>🎬 [Section 0] 오늘자 1분 요약</h2>
        <p><i>(오늘은 주식 시장 휴장일 또는 데이터 부족으로 영상이 생성되지 않았습니다.)</i></p>
        <hr>
        """

    # [NEW] [Section 1] Market Dashboard (파이썬에서 직접 생성)
    dashboard_html = ""
    if economy_data:
        fg_score = economy_data.get('fear_greed_index', 'N/A')
        fg_state = economy_data.get('market_sentiment', '')
        
        # [핵심 수정] calendar가 문자열("N/A")로 오면 리스트로 변환하여 세로 출력 방지
        calendar = economy_data.get('calendar', [])
        if isinstance(calendar, str):
            calendar = [calendar] # "N/A" -> ["N/A"]
            
        if not calendar: calendar = ["예정된 주요 일정이 없습니다."]

        cal_items = "".join([f"<li style='margin-bottom:5px;'>{evt}</li>" for evt in calendar])
        
        dashboard_html = f"""
        <h2>🗺️ [Section 1] Market Dashboard</h2>
        <h3 style="margin-top: 20px;">1. Global Market Map</h3>
        <div style="text-align:center; margin: 15px 0;">
            <img src="cid:tradingview_map" alt="S&P 500 Heatmap" style="width:100%; max-width:600px; border-radius:10px; border:1px solid #ddd;">
        </div>
        
        <div style="display: flex; gap: 20px; flex-wrap: wrap; margin-top:30px;">
            <div style="flex: 1; background-color: #f8f9fa; padding: 15px; border-radius: 10px;">
                <h4 style="margin: 0 0 10px 0;">🧠 Fear & Greed</h4>
                <p style="font-size: 24px; font-weight: bold; color: #c0392b; margin: 0;">{fg_score}</p>
                <p style="color: #666; margin: 0;">({fg_state})</p>
            </div>
            <div style="flex: 1; background-color: #f8f9fa; padding: 15px; border-radius: 10px;">
                <h4 style="margin: 0 0 10px 0;">📅 Schedule</h4>
                <ul style="padding-left: 20px; margin: 0;">{cal_items}</ul>
            </div>
        </div>
        <hr style="border: 0; border-top: 1px dashed #ddd; margin: 30px 0;">
        """

    # 2. AI 리포트 생성
    full_data = json.dumps({
        "stocks"   : stocks, 
        "news"     : general_news,
        "channels" : channel_videos,
        "trends"   : trend_videos
    }, ensure_ascii=False)

    # [핵심] 사용자가 만족했던 그 프롬프트를 복원하되, 섹션 1 지침만 수정
    prompt = f"""
당신은 바쁜 CEO를 위해 매일 아침 투자 보고서를 작성하는 **수석 투자 분석가**입니다.
제공된 데이터를 기반으로, CEO가 **원본 링크를 클릭할 필요가 없을 정도로** 구체적이고 완결성 있는 HTML 리포트를 작성하세요.

[🚨 절대 금지 사항]
1. **모호한 서술 금지:** '~에 대해 알아봅니다' 대신 **'~때문에 44조 원을 조달했습니다'**처럼 결론부터 말하세요.
2. **형용사 남발 금지:** '파격적인', '상당한' 대신 **'전년 대비 15% 상승', '역대 최고치인 500달러 돌파'** 등 구체적 수치를 제시하세요.

[작성 지침]
1. **언어**: 모든 내용은 **자연스러운 한국어**로 작성 (영어 기사도 완벽 번역).
2. **형식**: 오직 HTML 코드만 출력 (```html 태그 금지, <html>로 시작).
3. **출처**: 각 섹션 하단에 `<a href="...">`로 원본 링크 제공.

---

[섹션 2: 📈 Global Market Insight (관심 종목 & 핵심 이슈)]
- **[중요]** 데이터에 포함된 **'email_summary'** 내용을 기반으로 작성하세요. (영상 내용과 일관성 유지 필수)
- 각 종목의 등락 원인을 명쾌하게 정리하고, 등락률(change_str)을 포함하세요.

[섹션 3: 📰 Deep Dive (주요 경제 뉴스 상세 분석)]
- 해외 메이저 언론(Reuters, Bloomberg 등) 내용을 심층 분석합니다.
- 형식:
  <h4>[키워드] 기사 헤드라인 (한국어)</h4>
  <p><b>핵심 내용:</b> 기사의 결론을 두괄식으로 요약.</p>
  <ul>
    <li><b>Detail:</b> 왜 그런 현상이 일어났는지 구체적 배경과 수치 서술.</li>
    <li><b>Impact:</b> 시장에 미칠 구체적 영향.</li>
  </ul>
  <p style="font-size:0.9em; color:gray;">출처: <a href="URL">원문 읽기</a></p>
  <hr>

[섹션 4: 📺 YouTube 채널 인사이트 (액기스 추출)]
- 영상 내용을 보지 않아도 핵심을 알 수 있게 정리하세요.
- 형식:
  <h3>📺 [채널명] 영상 제목</h3>
  <p><b>💡 핵심 요약:</b> 영상이 주장하는 결론 한 문장.</p>
  <ul>
    <li><b>[시간] 주요 내용:</b> 구체적인 종목명, 추천 전략, 수치 명시.</li>
  </ul>
  <p><a href="URL">👉 영상 바로가기</a></p>
  <hr>

[섹션 5: 🔥 Trending Now (핫이슈 영상)]
- 설정된 키워드로 검색된 가장 핫한 영상을 분석합니다.
- 형식:
  <h3>🔥 [키워드] 영상 제목 (채널명)</h3>
  <p><b>요약:</b> 이 영상이 현재 화제가 되는 이유와 핵심 내용.</p>
  <ul><li><b>내용:</b> 상세 분석 (시간대별)</li></ul>
  <p><a href="URL">👉 영상 바로가기</a></p>
  <hr>

---
[분석할 데이터]
{full_data}
"""

    try:
        response       = model.generate_content(prompt)
        ai_report_body = response.text.replace("```html", "").replace("```", "").strip()
        
        # [최종 조립] 영상(0) + 대시보드(1) + AI분석(2~5)
        final_html     = f"""
        <html>
        <body style="font-family: 'Malgun Gothic', sans-serif; line-height: 1.6; color: #333;">
            {video_section_html}
            {dashboard_html}
            {ai_report_body}
            <div style="margin-top: 50px; font-size: 0.8em; color: #888; text-align: center;">
                Generated by AI Daily Briefing Agent
            </div>
        </body>
        </html>
        """
        return final_html
    
    except Exception as e:
        print(f"⚠️ 리포트 생성 실패: {e}")
        return f"<p>리포트 생성 중 오류 발생: {e}</p>"



# -----------------------------------------------------------------------------------------------------------------------------#
# [통합] 이메일 발송 함수 (스타일 + 이미지 첨부 + BCC)
# -----------------------------------------------------------------------------------------------------------------------------#
def send_email(recipients, subject, html_body, attachment_path=None):
    if not recipients: return
    
    print(f"📧 이메일 통합 발송 중 (수신자 {len(recipients)}명 - 비밀참조)...")
    
    # 1. 설정 로드
    config = load_config()
    sender_email = config['smtp_email']
    sender_password = config['smtp_password']
    
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 2. HTML 스타일 및 래퍼 (기존 디자인 복원)
    style = """<style>
        body { font-family: 'Malgun Gothic', sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; }
        h2 { border-bottom: 2px solid #2c3e50; padding-bottom: 10px; color: #2c3e50; }
        h3 { color: #2980b9; margin-top: 30px; border-left: 5px solid #2980b9; padding-left: 10px; background-color: #f4f6f7; }
        h4 { color: #c0392b; margin-top: 25px; font-weight: bold; }
        ul { background-color: #fdfdfd; padding: 10px 10px 10px 30px; border: 1px solid #eee; border-radius: 5px; }
        li { margin-bottom: 8px; }
        a { text-decoration: none; color: #27ae60; font-weight: bold; }
        .footer { margin-top: 50px; border-top: 1px solid #eee; padding-top: 20px; text-align: center; color: #888; font-size: 12px; }
    </style>"""
    
    # 본문 조립 (헤더 + 본문 + 푸터)
    full_html = f"""
    <html>
    <head>{style}</head>
    <body>
        <h2>📅 {today_str} 글로벌 증시 브리핑</h2>
        {html_body}
        <div class='footer'>Generated by AI Daily Briefing Agent</div>
    </body>
    </html>
    """

    # 3. 메시지 객체 생성 (MIMEMultipart 'related' 사용)
    msg = MIMEMultipart('related')
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = sender_email  # 받는 사람에는 보낸 사람 이메일 표시 (관례)
    msg['Bcc'] = ", ".join(recipients) # 실제 수신자는 비밀참조로 숨김

    # 4. HTML 본문 추가
    msg_alternative = MIMEMultipart('alternative')
    msg.attach(msg_alternative)
    msg_alternative.attach(MIMEText(full_html, 'html'))

    # 5. 이미지 첨부 (있을 경우)
    if attachment_path and os.path.exists(attachment_path):
        try:
            with open(attachment_path, 'rb') as f:
                img_data = f.read()
            
            image = MIMEImage(img_data)
            # HTML의 <img src="cid:tradingview_map"> 와 매칭되는 ID
            image.add_header('Content-ID', '<tradingview_map>') 
            image.add_header('Content-Disposition', 'inline', filename="market_map.png")
            msg.attach(image)
            print("   📎 히트맵 이미지 첨부 완료")
        except Exception as e:
            print(f"⚠️ 이미지 첨부 중 에러: {e}")

    # 6. 발송
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)
        print("✅ 이메일 발송 성공")
    except Exception as e:
        print(f"❌ 이메일 발송 실패: {e}")



# -----------------------------------------------------------------------------------------------------------------------------#
# html to slack-text 
# -----------------------------------------------------------------------------------------------------------------------------#

def html_to_slack_text(html_content):
    """
    HTML 리포트를 슬랙에서 보기 좋은 텍스트로 변환합니다.
    """
    if not html_content: return ""

    text = html_content
    
    # 1. <style> 태그와 그 안의 내용 제거 (가장 중요)
    text = re.sub(r'<style>.*?</style>', '', text, flags=re.DOTALL)
    
    # 2. 불필요한 상위 태그 제거
    text = text.replace("<html>", "").replace("</html>", "")
    text = text.replace("<body>", "").replace("</body>", "")
    text = text.replace("<head>", "").replace("</head>", "")
    
    # 3. 줄바꿈 처리
    text = text.replace("<br>", "\n").replace("</p>", "\n").replace("<p>", "")
    
    # 4. 제목 처리 (<h3> -> *제목*)
    text = re.sub(r'<h[1-6]>(.*?)</h[1-6]>', r'\n\n*\1*\n', text)
    
    # 5. 리스트 처리 (<li> -> •)
    text = text.replace("<ul>", ""  ).replace("</ul>", "")
    text = text.replace("<li>", "• ").replace("</li>", "\n")
    
    # 6. 굵게 처리
    text = re.sub(r'<b>(.*?)</b>', r'*\1*', text)
    text = re.sub(r'<strong>(.*?)</strong>', r'*\1*', text)
    
    # 7. 링크 처리 (<a href="URL">TEXT</a> -> <URL|TEXT>)
    # 슬랙 링크 포맷: <URL|텍스트>
    text = re.sub(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', r'<\1|\2>', text)
    
    # 8. 구분선 처리
    text = text.replace("<hr>", "\n-----------------------------------\n")
    
    # 9. 남은 HTML 태그 제거
    text = re.sub(r'<[^>]+>', '', text)
    
    # 10. 공백 정리 (3개 이상 줄바꿈을 2개로)
    text = re.sub(r'\n\s*\n', '\n\n', text).strip()
    
    return text



# -----------------------------------------------------------------------------------------------------------------------------#
# send slack
# -----------------------------------------------------------------------------------------------------------------------------#

def send_slack(webhook_url, html_body):
    print("📢 슬랙 발송 중...")
    if not webhook_url:
        print("⚠️ 슬랙 URL이 설정되지 않음")
        return

    today      = datetime.now().strftime("%Y-%m-%d")
    # HTML을 보기 좋은 텍스트로 변환
    slack_text = f"📅 *{today} 데일리 투자 리포트*\n\n" + html_to_slack_text(html_body)
    
    # 슬랙은 메시지가 너무 길면 잘릴 수 있으므로 주의 (4000자 제한 등)
    # 여기서는 간단히 텍스트로 보냅니다.
    payload    = {"text": slack_text}
    
    try:
        response = requests.post(webhook_url, json=payload)
        if response.status_code == 200:
            print("✅ 슬랙 발송 완료")
        else:
            print(f"❌ 슬랙 발송 실패: {response.text}")
    except Exception as e:
        print(f"❌ 슬랙 에러: {e}")


# -----------------------------------------------------------------------------------------------------------------------------#
# [NEW] HTML to YouTube Description (URL 보존 & AI 고지 추가)
# -----------------------------------------------------------------------------------------------------------------------------#
def html_to_youtube_description(html_content):
    if not html_content: return ""
    text = html_content
    
    # 스타일 제거
    text = re.sub(r'<style>.*?</style>', '', text, flags=re.DOTALL)
    
    # 태그 -> 텍스트 변환
    text = text.replace("<br>", "\n").replace("</p>", "\n").replace("</li>", "\n")
    text = re.sub(r'<h[1-6]>(.*?)</h[1-6]>', r'\n\n■ \1\n', text) 
    text = text.replace("<li>", "- ")
    
    # 링크 처리: <a href="URL">TEXT</a> -> "TEXT: URL"
    text = re.sub(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', r'\2: \1', text)
    
    # 나머지 태그 제거
    text = re.sub(r'<[^>]+>', '', text)
    
    # 공백 정리
    text = re.sub(r'\n\s*\n', '\n\n', text).strip()
    
    # [Fix] 유튜브 정책 준수를 위한 AI 생성 고지 문구 추가
    disclaimer = """
    
------------------------------------------------
⚠️ 알림 (Disclaimer)
이 영상은 인공지능(AI)을 활용하여 자동 생성되었습니다.
- 대본 및 분석: Google Gemini 1.5
- 음성: Microsoft Edge TTS
- 영상 편집: Python (MoviePy)

투자의 책임은 투자자 본인에게 있으며, 제공된 정보는 참고용입니다.
------------------------------------------------
    """
    
    return text + disclaimer




# -----------------------------------------------------------------------------------------------------------------------------#
# [NEW] Cleanup Function (청소부)
# -----------------------------------------------------------------------------------------------------------------------------#
def cleanup_files():
    print("🧹 임시 파일 및 이전 결과물 정리 중...")
    
    # 삭제할 파일 패턴 목록
    patterns = [
        "*.mp4",       # 모든 동영상 파일 (daily_*.mp4 등)
        "*.mp3",       # 모든 음성 파일 (voice.mp3 등)
        "*_chart.png", # 생성된 차트 이미지
        "logo_temp.png" # 혹시 모를 임시 로고
    ]
    
    # logos 폴더 안의 파일은 삭제하지 않습니다 (캐시 역할)
    
    for pattern in patterns:
        # 현재 폴더에서 패턴에 맞는 파일 찾기
        for file_path in glob.glob(pattern):
            try:
                os.remove(file_path)
                print(f"   - 삭제 완료: {file_path}")
            except Exception as e:
                print(f"   ⚠️ 삭제 실패: {file_path} ({e})")




# -----------------------------------------------------------------------------------------------------------------------------#
# job (Final: Full Automation)
# -----------------------------------------------------------------------------------------------------------------------------#

# -----------------------------------------------------------------------------------------------------------------------------#
# job (Final: Full Automation)
# -----------------------------------------------------------------------------------------------------------------------------#
def job():
    print(f"\n🚀 [Final] 데일리 브리핑 시작: {datetime.now()}")
    
    # [수정] 시작 전 임시 파일 정리
    cleanup_files()
    
    config = load_config()
    if not config: 
        print("❌ 설정 파일(config.json)을 찾을 수 없습니다.")
        return
    
    today_str        = datetime.now().strftime("%Y-%m-%d")
    
    # 1. 데이터 수집
    stocks           = collect_stock_data(config.get('stock_tickers', []))
    general_news     = fetch_news_raw(config.get('news_keywords', []), limit=5)
    channel_videos   = collect_channel_youtube_data(config.get('youtube_channels', {}))
    trend_videos     = collect_keyword_youtube_data(config.get('youtube_keywords', []))    
    all_youtube      = channel_videos + trend_videos
    economy_news_raw = collect_economy_data()
    
    if stocks or general_news or all_youtube:
        try:
            # [수정 1] 변수 미리 초기화 (에러 방지용)
            video_url = None 
            
            # 2. 콘텐츠 요약 생성
            stocks, general_news, all_youtube, economy_data, generated_scripts = analyze_and_summarize(stocks, general_news, all_youtube, economy_news_raw)
            
            video_title = "글로벌 증시 브리핑"
            print(f"🎬 대본 및 콘텐츠 확정: {video_title}")
            
            structured_data = {
                'stocks'  : stocks,
                'news'    : general_news,
                'youtube' : all_youtube,
                'economy' : economy_data
            }

            # 4. 영상 제작
            map_image_path = "tradingview_map.png" # 캡처된 파일명 예상

            if hasattr(video_studio, 'make_video_module'):
                video_file = video_studio.make_video_module(
                    scene_scripts   = generated_scripts, 
                    structured_data = structured_data,
                    date_str        = today_str
                )                
                
                # 영상 완료 후 맵 이미지가 생성되었는지 확인 (video_studio 내부에서 capture 수행함)
                if not os.path.exists(map_image_path):
                    print("⚠️ 맵 이미지를 찾을 수 없음. 메일 첨부 실패 가능성.")

                # 5. 유튜브 업로드
                if video_file and os.path.exists(video_file):
                    
                    print("📤 유튜브 업로드 시작...")
                    temp_report = generate_report(stocks, general_news, channel_videos, trend_videos, video_url=None, economy_data=economy_data)
                    desc_text   = html_to_youtube_description(temp_report)
                        
                    video_url = youtube_manager.upload_short(
                        video_file, 
                        title       = f"{today_str}일자- {video_title}", 
                        description = desc_text
                    )
                    print(f"✅ 업로드 완료: {video_url}")
                else:
                    print("⚠️ 생성된 영상 파일이 없거나 video_studio에서 반환되지 않았습니다.")
            else:
                print("⚠️ video_studio 모듈 오류: make_video_module 함수가 없습니다.")
            
            # 6. 메일 및 슬랙 발송
            # video_url이 None이어도 안전하게 체크
            if video_url:
                print("📧 리포트 배포 준비...")
                report = generate_report(stocks, general_news, channel_videos, trend_videos, video_url, economy_data=economy_data)
                # [수정된 호출 방식]
                # 인자 순서: 수신자목록, 제목, HTML본문, 첨부파일경로
                send_email(
                    config.get('email_recipients', []), 
                    f"[Insight] {today_str} 글로벌 증시 브리핑", 
                    report, 
                    attachment_path="tradingview_map.png" # video_studio가 만든 이미지
                )
                
            else:
                print("⚠️ 영상 URL 없음. 리포트 발송 스킵.")

        except Exception as e:
            print(f"⚠️ 전체 프로세스 중 에러: {e}")
            import traceback
            traceback.print_exc()
            
    else:
        print("💤 수집된 데이터가 없습니다.")

    print("🏁 [Final] 모든 작업 완료\n")



# -----------------------------------------------------------------------------------------------------------------------------#
# main (One-Shot Execution)
# -----------------------------------------------------------------------------------------------------------------------------#
if __name__ == "__main__":
    print(f"[{datetime.now()}] 데일리 브리핑 에이전트 실행 (One-Shot Mode)")

    # 1회 실행
    job()

    print(f"[{datetime.now()}] 모든 작업 완료. 프로세스를 종료합니다.")
    # 루프 없이 여기서 프로그램이 끝나면, 도커 컨테이너도 자동으로 꺼집니다.


# -----------------------------------------------------------------------------------------------------------------------------#
