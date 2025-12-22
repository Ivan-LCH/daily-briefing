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
# --- 2. 주식 수집 ---
# -----------------------------------------------------------------------------------------------------------------------------#

def collect_stock_data(tickers):
    # [수정] 요일 체크(휴장일 스킵) 로직을 과감히 삭제했습니다.
    # 주말/휴일이라도 '가장 최근 데이터(Last Close)'를 가져와서 보여줍니다.
    
    print("📈 주식 데이터 수집 중...")
    stock_data = []
    
    for symbol in tickers:
        try:
            ticker = yf.Ticker(symbol)
            # 5일치 데이터를 가져오면 휴일 상관없이 마지막 거래일 데이터가 포함됨
            hist = ticker.history(period="5d")
            if len(hist) < 2: continue
            
            last_close = hist['Close'].iloc[-1]
            prev_close = hist['Close'].iloc[-2]
            change = last_close - prev_close
            pct_change = (change / prev_close) * 100
            
            # 주식 관련 뉴스도 함께 수집
            related_news = fetch_news_raw([f"{symbol} stock news", f"{symbol} analysis"], limit=2)
            
            stock_data.append({
                'symbol'    : symbol,
                'price'     : f"${last_close:.2f}",
                'change_str': f"{change:+.2f} ({pct_change:+.2f}%)",
                'news_items': related_news
            })
            print(f"  - [{symbol}] 완료")
        except: pass

    return stock_data



# -----------------------------------------------------------------------------------------------------------------------------#
# --- 3. 채널 기반 유튜브 수집 (48시간 이내) ---
# -----------------------------------------------------------------------------------------------------------------------------#

def collect_channel_youtube_data(channels_dict):
    print("🎥 유튜브 채널 수집 중...")
    youtube    = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
    video_data = []
    now        = datetime.utcnow()

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

            for item in pl_res['items']: # 최신 5개 중 시간 맞는것 탐색
                vid          = item['snippet']['resourceId']['videoId']
                title        = item['snippet']['title']
                pub_date_str = item['snippet']['publishedAt']
                
                # [수정] 48시간 -> 24시간으로 변경
                pub_date_dt = datetime.strptime(pub_date_str, "%Y-%m-%dT%H:%M:%SZ")
                if (now - pub_date_dt).total_seconds() > 24 * 3600:
                    continue # 24시간 지난 건 패스
                
                pub_date_kst = (pub_date_dt + timedelta(hours=9)).strftime("%Y-%m-%d")
                transcript   = get_timed_transcript(vid)
                content      = transcript[:40000] if transcript else f"(자막 없음) {item['snippet']['description'][:1000]}"

                video_data.append({
                    'type'      : 'channel',
                    'source'    : name,
                    'title'     : title,
                    'date'      : pub_date_kst,
                    'url'       : f"https://www.youtube.com/watch?v={vid}",
                    'content'   : content
                })
                print(f"  - [{name}] 확보: {title}")
                break # 채널당 최신 1개만 확보하고 탈출 (원하면 break 제거)
        except: pass
        
    return video_data



# -----------------------------------------------------------------------------------------------------------------------------#
# --- [NEW] 4. AI 편집장: 주제 선정 및 대본 작성 ---
# -----------------------------------------------------------------------------------------------------------------------------#

def plan_and_script_video(stocks, news):
    print("🧠 AI 편집장이 쇼츠 주제를 선정 중...")
    
    # 데이터 요약
    context = json.dumps({'stocks': stocks, 'news': news}, ensure_ascii=False)
    
    # 프롬프트 수정: 인사는 인트로 영상이 하니까, AI는 '본론'만 작성
    prompt = f"""
    너는 주식 유튜버야. 아래 데이터에서 '가장 조회수 터질만한' 주제 1개를 골라.
    그리고 45초 분량의 쇼츠 대본을 써줘.
    
    [데이터]
    {context}
    
    [요구사항]
    1. 주제: 등락폭이 가장 크거나, 호재/악재가 명확한 종목 선택 (우선순위: TSLA, PLTR, GOOG, 나머지).
    2. 톤: 자극적이지만 차분한 구어체로.
    3. **[중요] 인사 생략**: "안녕하세요" 같은 인사는 절대 하지 마. (앞에 인트로 영상이 따로 있음)
    4. **바로 본론 시작**: "오늘 테슬라가 무려 10%나 폭등했습니다. 그 이유는..." 처럼 바로 분석으로 들어갈 것.
    5. 내용: 호재/악재의 출처와 핵심 내용을 객관적으로 포함.
    6. JSON 포맷으로만 응답해:
    {{
        "symbol": "종목코드(예:TSLA)", 
        "title" : "로보택시 규제 승인 임박! 역대급 폭등 시작되나?", 
        "script": "오늘 테슬라가 로보택시 규제 승인 기대감으로..."
    }}
    """    
    
    try:
        res = model.generate_content(prompt)
        text = res.text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        print(f"❌ 대본 작성 실패: {e}")
        return None


# -----------------------------------------------------------------------------------------------------------------------------#
# ---  5. 키워드 기반 트렌드 영상 수집 ---
# -----------------------------------------------------------------------------------------------------------------------------#

def collect_keyword_youtube_data(keywords):
    print("🔥 유튜브 트렌드 검색 중...")
    youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
    trend_data = []
    
    # 24시간 전 시간 구하기
    yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat("T") + "Z"

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
# --- 통합 리포트 생성 (영상 링크 추가됨) ---
# -----------------------------------------------------------------------------------------------------------------------------#

def generate_report(stock_data, general_news, channel_videos, trend_videos, video_url=None):
    print("🧠 AI 통합 분석 및 리포트 작성 중...")
    
    # 1. [Section 0] 영상 섹션 HTML 생성 (파이썬에서 직접 삽입)
    # 이메일 CSS 스타일(h2)과 통일감을 주기 위해 h2 태그 사용
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
    elif not stock_data:
        # 휴장일일 경우 안내 메시지
        video_section_html = """
        <h2>🎬 [Section 0] 오늘자 1분 요약</h2>
        <p><i>(오늘은 주식 시장 휴장일 또는 데이터 부족으로 영상이 생성되지 않았습니다.)</i></p>
        <hr>
        """

    # 2. AI 리포트 생성 (Section 1 ~ 4)
    full_data = json.dumps({
        "stocks"   : stock_data,
        "news"     : general_news,
        "channels" : channel_videos,
        "trends"   : trend_videos
    }, ensure_ascii=False)

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

[섹션 1: 📈 Global Market Insight (관심 종목 & 핵심 이슈)]
- 관심 종목의 등락 원인을 **'육하원칙'**에 의거하여 명쾌하게 분석하여 3-4줄로 요약하세요.
- 단순히 '올랐다'가 아니라, **'어떤 뉴스/실적/발언 때문에'** 움직였는지 명확하게 설명하세요.

[섹션 2: 📰 Deep Dive (주요 경제 뉴스 상세 분석)]
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

[섹션 3: 📺 YouTube 채널 인사이트 (액기스 추출)]
- 영상 내용을 보지 않아도 핵심을 알 수 있게 정리하세요.
- 형식:
  <h3>📺 [채널명] 영상 제목</h3>
  <p><b>💡 핵심 요약:</b> 영상이 주장하는 결론 한 문장.</p>
  <ul>
    <li><b>[시간] 주요 내용:</b> 구체적인 종목명, 추천 전략, 수치 명시.</li>
  </ul>
  <p><a href="URL">👉 영상 바로가기</a></p>
  <hr>

[섹션 4: 🔥 Trending Now (핫이슈 영상)]
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
        response = model.generate_content(prompt)
        ai_report_body = response.text.replace("```html", "").replace("```", "").strip()
        
        # [최종 합체] Section 0 (영상) + Section 1~4 (AI 리포트)
        return video_section_html + ai_report_body
    
    except Exception as e:
        return f"<p>리포트 생성 실패: {e}</p>"


# ============================================================================================================================#
# ---  SEND EMAIL
# ============================================================================================================================#

def send_email(recipients, html_body):
    if not recipients: return
    print(f"📧 이메일 통합 발송 중 (수신자 {len(recipients)}명 - 비밀참조)...")
    
    today = datetime.now().strftime("%Y-%m-%d")
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
    full_html = f"<html><head>{style}</head><body><h2>📅 {today} 투자 리포트</h2>{html_body}<div class='footer'>Generated by Ivan Agent</div></body></html>"

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            
            msg = MIMEText(full_html, 'html')
            msg['Subject'] = f"[Insight] {today} 데일리 브리핑"
            msg['From']    = EMAIL_SENDER
            
            # [수정 핵심]
            # 1. 'To'에는 보내는 사람 본인 주소를 적습니다. (받는 사람에게는 'To: 보낸사람' 으로 보임)
            msg['To'] = EMAIL_SENDER
            
            # 2. 실제 수신자 리스트는 'Bcc' (비밀참조)에 넣습니다.
            # send_message 함수가 Bcc를 인식해서 발송하고, 헤더에서는 자동으로 지워줍니다.
            msg['Bcc'] = ", ".join(recipients)
            
            server.send_message(msg)
            
        print("✅ 이메일 발송 완료 (비밀참조 처리됨)")
    except Exception as e:
        print(f"❌ 이메일 실패: {e}")



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
    text = text.replace("<ul>", "").replace("</ul>", "")
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

    today = datetime.now().strftime("%Y-%m-%d")
    # HTML을 보기 좋은 텍스트로 변환
    slack_text = f"📅 *{today} 데일리 투자 리포트*\n\n" + html_to_slack_text(html_body)
    
    # 슬랙은 메시지가 너무 길면 잘릴 수 있으므로 주의 (4000자 제한 등)
    # 여기서는 간단히 텍스트로 보냅니다.
    payload = {"text": slack_text}
    
    try:
        response = requests.post(webhook_url, json=payload)
        if response.status_code == 200:
            print("✅ 슬랙 발송 완료")
        else:
            print(f"❌ 슬랙 발송 실패: {response.text}")
    except Exception as e:
        print(f"❌ 슬랙 에러: {e}")


# -----------------------------------------------------------------------------------------------------------------------------#
# [NEW] HTML to YouTube Description (URL 보존)
# -----------------------------------------------------------------------------------------------------------------------------#
def html_to_youtube_description(html_content):
    if not html_content: return ""
    text = html_content
    
    # 스타일 제거
    text = re.sub(r'<style>.*?</style>', '', text, flags=re.DOTALL)
    
    # 태그 -> 텍스트 변환
    text = text.replace("<br>", "\n").replace("</p>", "\n").replace("</li>", "\n")
    text = re.sub(r'<h[1-6]>(.*?)</h[1-6]>', r'\n\n■ \1\n', text) # 제목 앞에 ■ 붙임
    text = text.replace("<li>", "- ")
    
    # [핵심] 링크 처리: <a href="URL">TEXT</a> -> "TEXT: URL" 형태로 변환
    # 예: <a href="https://google.com">기사 읽기</a> -> 기사 읽기: https://google.com
    text = re.sub(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', r'\2: \1', text)
    
    # 나머지 태그 제거
    text = re.sub(r'<[^>]+>', '', text)
    
    # 공백 정리
    text = re.sub(r'\n\s*\n', '\n\n', text).strip()
    
    return text




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
# job (Updated)
# -----------------------------------------------------------------------------------------------------------------------------#

def job():
    print(f"\n🚀 시작: {datetime.now()}")
    cleanup_files() # 청소
    
    config = load_config()
    if not config: return
    
    # 1. 데이터 수집
    stocks         = collect_stock_data(config.get('stock_tickers', []))
    general_news   = fetch_news_raw(config.get('news_keywords', []), limit=3)
    channel_videos = collect_channel_youtube_data(config.get('youtube_channels', {}))
    trend_videos   = collect_keyword_youtube_data(config.get('youtube_keywords', []))
    
    video_url = None
    
    # 인트로용 뉴스 리스트
    headline_list = []
    if general_news:
        headline_list = [item['title'] for item in general_news[:2]]

    # [수정] stocks가 없어도 general_news가 있으면 영상 제작 시도
    if stocks or general_news:
        try:
            # 만약 stocks가 비어있다면, 차트 그릴 때 에러가 날 수 있으므로
            # plan_and_script_video 함수가 '뉴스' 중심으로 대본을 짜도록 유도해야 함.
            # 하지만 현재 video_studio는 'symbol'이 필수이므로, 
            # stocks가 비어있을 경우를 대비해 가상의 symbol이나 대표 종목(예: 주식 리스트 첫번째)을 지정하는 로직이 필요.
            
            target_stocks = stocks if stocks else [{'symbol': 'SPY', 'price': '-', 'change_str': '-'}] # 비상용 더미
            
            plan = plan_and_script_video(target_stocks, general_news) 
            if plan:
                print(f"🎬 선택된 주제: {plan['title']}")
                
                # 영상 제작
                video_file = video_studio.make_video(
                    topic_data=plan, 
                    script_text=plan['script'], 
                    stock_list=stocks, 
                    news_list=general_news, 
                    youtube_list=channel_videos,
                    trend_list=trend_videos
                )
                
                if video_file:
                    temp_report = generate_report(stocks, general_news, channel_videos, trend_videos, video_url=None)
                    description_text = html_to_youtube_description(temp_report)
                    full_description = f"[상세 분석 리포트]\n{description_text}"
                    video_url = youtube_manager.upload_short(video_file, plan['title'], description=full_description)

        except Exception as e:
            print(f"⚠️ 영상 제작 중 에러: {e}")
            import traceback
            traceback.print_exc()
            
    # 리포트 발송
    if any([stocks, general_news, channel_videos, trend_videos]):
        report = generate_report(stocks, general_news, channel_videos, trend_videos, video_url)
        send_email(config.get('email_recipients', []), report)
        send_slack(config.get('slack_webhook_url'), report)
        
        cleanup_files() # 정리
    else:
        print("수집된 데이터가 없습니다.")

    print("🏁 끝\n")



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
