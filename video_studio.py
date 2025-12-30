# -----------------------------------------------------------------------------------------------------------------------------#
# Import
# -----------------------------------------------------------------------------------------------------------------------------#
import os
import sys
import time
import asyncio
import re
import numpy as np
from datetime import datetime

# [Logging Fix] Docker 환경에서 로그가 버퍼링 없이 즉시 출력되도록 설정
sys.stdout.reconfigure(line_buffering=True)

# Edge-TTS
import edge_tts

# Financial & Data
import yfinance as yf

# Visualization
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from PIL import Image

# MoviePy
from moviepy.editor import *
from moviepy.config import change_settings

# Selenium (Web Capture)
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# -----------------------------------------------------------------------------------------------------------------------------#
# Configuration & Environment
# -----------------------------------------------------------------------------------------------------------------------------#
# [설정] ImageMagick 경로 (Linux/Docker 환경용)
if os.name != 'nt':
    change_settings({"IMAGEMAGICK_BINARY": "/usr/bin/convert"})

# -----------------------------------------------------------------------------------------------------------------------------#
# Core: Safety Text System
# -----------------------------------------------------------------------------------------------------------------------------#
def get_safe_font():
    """OS 환경에 맞는 한글 폰트 경로를 탐색하여 반환"""
    possible_paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
        "C:/Windows/Fonts/malgun.ttf"
    ]
    for p in possible_paths:
        if os.path.exists(p): return p
    return "Malgun Gothic" if os.name == 'nt' else "Noto-Sans-CJK-KR"

SAFE_FONT = get_safe_font()

def sanitize_text(text):
    if not text: return " "
    return str(text).strip()

def create_safe_text_clip(text, **kwargs):
    """TextClip 생성 시 폰트 에러 방지 래퍼 함수"""
    try:
        safe_text = sanitize_text(text)
        if 'font' not in kwargs: kwargs['font'] = SAFE_FONT
        return TextClip(safe_text, **kwargs)
    except Exception as e:
        print(f"⚠️ 텍스트 생성 실패: {e}", flush=True)
        # 실패 시 투명 클립 반환
        return ColorClip(size=(10, 10), color=(0,0,0)).set_opacity(0).set_duration(kwargs.get('duration', 1))

# -----------------------------------------------------------------------------------------------------------------------------#
# Helper Functions: Voice & Visuals
# -----------------------------------------------------------------------------------------------------------------------------#
async def _generate_voice(text, filename):
    clean_text  = str(text).replace('*', '').replace('"', '').replace("'", "")
    communicate = edge_tts.Communicate(clean_text, "ko-KR-SunHiNeural")
    await communicate.save(filename)

def create_voice_file(text, filename):
    """Edge-TTS를 사용하여 음성 파일 생성"""
    try:
        loop = asyncio.get_event_loop_policy().get_event_loop()
        loop.run_until_complete(_generate_voice(text, filename))
        return filename
    except Exception as e:
        print(f"⚠️ 음성 생성 에러: {e}")
        return None

def create_date_stamp(date_str, duration):
    if not date_str: return None
    return create_safe_text_clip(
        f"Date: {date_str}", fontsize=24, color='#888888', align='East'
    ).set_position((1080, 30)).set_duration(duration)

def create_title_strip(text, fontsize=45, bg_color=(0,0,0), text_color='white', position=('center', 40), duration=5):
    """상단 제목띠 생성"""
    strip_bg = ColorClip(size=(1280, 110), color=bg_color)\
               .set_opacity(0.9)\
               .set_position(('center', position[1]-10))\
               .set_duration(duration)
    
    txt_clip = create_safe_text_clip(text, fontsize=fontsize, color=text_color)\
               .set_position(('center', position[1] + 10))\
               .set_duration(duration)
    
    return [strip_bg, txt_clip]

# -----------------------------------------------------------------------------------------------------------------------------#
# External Data Capture (Selenium & Matplotlib)
# -----------------------------------------------------------------------------------------------------------------------------#
def capture_finviz_map(output_file="finviz_map.png"):
    print("📸 Finviz 맵 캡처 시도 (Docker 안정화 모드)...", flush=True)
    driver = None
    try:
        chrome_options = Options()
        
        # [1] 시스템에 설치된 Chromium 바이너리 위치 지정 (Docker 환경 필수)
        # apt-get install chromium으로 설치된 경로는 보통 아래와 같습니다.
        chrome_options.binary_location = "/usr/bin/chromium"

        # [2] Headless 및 봇 탐지 회피 설정
        chrome_options.add_argument('--headless=new') 
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage') # 메모리 공유 에러 방지
        chrome_options.add_argument('--disable-gpu')
        
        # [3] 타임아웃 방지 핵심 옵션 (연결 안정화)
        chrome_options.add_argument('--remote-debugging-port=9222') 
        chrome_options.add_argument('--disable-software-rasterizer')
        chrome_options.add_argument('--window-size=1920,1080')

        # [4] User-Agent 설정
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        chrome_options.add_argument(f'user-agent={user_agent}')

        # [5] 드라이버 설정 (시스템에 설치된 chromedriver 사용 권장)
        # Dockerfile에서 apt-get install chromium-driver를 했다면 경로는 /usr/bin/chromedriver 입니다.
        # webdriver_manager 대신 시스템 드라이버를 쓰는 것이 버전 충돌을 막습니다.
        if os.path.exists("/usr/bin/chromedriver"):
            service = ChromeService(executable_path="/usr/bin/chromedriver")
            driver = webdriver.Chrome(service=service, options=chrome_options)
        else:
            # 로컬 테스트용 (webdriver_manager 사용)
            from webdriver_manager.chrome import ChromeDriverManager
            service = ChromeService(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)

        # [6] 페이지 로딩 타임아웃 설정 (30초 지나면 에러 발생시키고 다음으로 넘어감)
        driver.set_page_load_timeout(30)
        
        # 탐지 우회 스크립트
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        print("   🌐 Finviz 접속 중...", flush=True)
        try:
            driver.get("https://finviz.com/map.ashx")
        except Exception as e:
            print(f"   ⚠️ 페이지 로딩 시간 초과 또는 접속 에러 (무시하고 캡처 시도): {e}")

        # 로딩 대기 (Cloudflare 통과 시간)
        time.sleep(10)
        
        driver.save_screenshot(output_file)
        
        if os.path.exists(output_file):
            img = Image.open(output_file)
            width, height = img.size
            cropped_img = img.crop((0, 0, width, int(height * 0.85)))
            cropped_img.save(output_file)
            print("   ✅ 캡처 및 저장 완료", flush=True)
            return output_file
        else:
            print("   ⚠️ 파일이 생성되지 않았습니다.", flush=True)
            return None

    except Exception as e:
        print(f"⚠️ 캡처 실패: {e}", flush=True)
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass


# -----------------------------------------------------------------------------------------------------------------------------#
# Data Processing & Visualization (Matplotlib)
# -----------------------------------------------------------------------------------------------------------------------------#
def create_chart_image(symbol):
    """특정 종목의 1일 차트 생성 (Matplotlib)"""
    print(f"📊 차트 생성 시도: {symbol}", flush=True)
    try:
        ticker = yf.Ticker(symbol)
        hist   = ticker.history(period="1d", interval="5m")
        
        if hist.empty:
            print("   ⚠️ 데이터 없음 (휴장일 가능성)", flush=True)
            return None, None

        last_price = hist['Close'].iloc[-1]
        try:    real_prev_close = ticker.fast_info.previous_close
        except: real_prev_close = hist['Close'].iloc[0]
        
        diff        = last_price - real_prev_close
        pct         = (diff / real_prev_close) * 100
        sign        = "+" if diff > 0 else ""
        color_trend = '#ff3333' if diff > 0 else '#3366ff' # 상승: 빨강, 하락: 파랑

        info = {
            'symbol'    : symbol, 
            'price'     : f"${last_price:.2f}",
            'diff'      : f"{sign}{diff:.2f}", 
            'pct'       : f"({sign}{pct:.2f}%)",
            'prev_close': f"${real_prev_close:.2f}", 
            'color'     : color_trend
        }
        
        # Plotting
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 8))
        ax.set_facecolor('#121212')
        fig.patch.set_facecolor('#000000')
        
        ax.plot(hist.index, hist['Close'], color=color_trend, linewidth=2.5)
        ax.fill_between(hist.index, hist['Close'], hist['Close'].min(), color=color_trend, alpha=0.15)
        ax.axhline(y=real_prev_close, color='white', linestyle='--', linewidth=1, alpha=0.6)
        
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.grid(True, linestyle=':', alpha=0.2)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
        
        output_file = f"{symbol}_chart.png"
        plt.savefig(output_file, bbox_inches='tight', facecolor='black')
        plt.close()
        
        return output_file, info
    except Exception as e:
        print(f"   ⚠️ 차트 에러: {e}", flush=True)
        return None, None


# -----------------------------------------------------------------------------------------------------------------------------#
# Scene Generators
# -----------------------------------------------------------------------------------------------------------------------------#

# [SCENE 1] Market Overview ---------------------------------------------------------------------

def create_scene_market(script_text, date_str, is_market_closed):
    print(f"🎬 Scene 1: Market Overview (Closed? {is_market_closed})", flush=True)
    
    audio_path = create_voice_file(script_text, "scene1.mp3")
    if not audio_path: return None
    audio_clip = AudioFileClip(audio_path)
    duration   = audio_clip.duration + 1.0 

    clips = [ColorClip(size=(1280, 720), color=(0, 0, 0), duration=duration)]
    clips.extend(create_title_strip("Global Market Map (S&P 500)", duration=duration))
    if date_str: clips.append(create_date_stamp(date_str, duration))

    if is_market_closed:
        # [휴장일] 캡처 시도하지 않고 텍스트 표시
        msg = "미국 증시 휴장 (Market Closed)\n데이터 수집 불가"
        clips.append(create_safe_text_clip(msg, fontsize=55, color='gray', align='center')
                     .set_position('center').set_duration(duration))
    else:
        # [개장일] Finviz 맵 캡처
        map_img = capture_finviz_map()
        if map_img and os.path.exists(map_img):
            img_clip = ImageClip(map_img).resize(width=1150).set_position(('center', 160)).set_duration(duration)
            clips.append(img_clip)
        else:
            clips.append(create_safe_text_clip("Map Unavailable", fontsize=60, color='gray')
                         .set_position('center').set_duration(duration))

    return CompositeVideoClip(clips).set_audio(audio_clip)

# [SCENE 2] News ---------------------------------------------------------------------

def create_scene_news(script_text, news_list, date_str):
    print("🎬 Scene 2: News", flush=True)
    
    audio_path = create_voice_file(script_text, "scene2.mp3")
    if not audio_path: return None
    audio_clip = AudioFileClip(audio_path)
    duration   = audio_clip.duration + 1.0

    clips = [ColorClip(size=(1280, 720), color=(15, 20, 35), duration=duration)]
    clips.extend(create_title_strip("Global Economic News", bg_color=(0, 40, 80), duration=duration))
    if date_str: clips.append(create_date_stamp(date_str, duration))
    
    start_y = 160
    for news in news_list[:4]:
        main_text = news.get('summary', news['title'])
        source    = news.get('source', 'News')
        
        main_clip = create_safe_text_clip(f"• {main_text}", fontsize=26, color='#ffd700', method='caption', size=(1100, None), align='West')\
                      .set_position((80, start_y)).set_duration(duration)
        clips.append(main_clip)
        
        sub_clip = create_safe_text_clip(f"   [{source}]", fontsize=18, color='#aaaaaa', align='West')\
                    .set_position((80, start_y + main_clip.h + 5)).set_duration(duration)
        clips.append(sub_clip)
        
        start_y += (main_clip.h + sub_clip.h + 30)

    return CompositeVideoClip(clips).set_audio(audio_clip)


# [SCENE 3] Market Watchlist (Handles Closed Market) -------------------------------------

def create_scene_stock_list(script_text, all_stocks, date_str, is_market_closed):
    print(f"🎬 Scene 3: Stock List (Closed? {is_market_closed})", flush=True)
    
    audio_path = create_voice_file(script_text, "scene3.mp3")
    if not audio_path: return None
    audio_clip = AudioFileClip(audio_path)
    duration   = audio_clip.duration + 1.0

    clips = [ColorClip(size=(1280, 720), color=(10, 10, 10), duration=duration)]
    clips.extend(create_title_strip("Market Watchlist", bg_color=(20, 20, 20), duration=duration))
    if date_str: clips.append(create_date_stamp(date_str, duration))
    
    start_y    = 160
    row_height = 90
    header_y   = 120
    
    # Headers
    headers = [("Ticker", 80), ("Price", 280), ("Change", 480), ("Headline Summary", 680)]
    for text, x_pos in headers:
        clips.append(create_safe_text_clip(text, fontsize=25, color='gray').set_position((x_pos, header_y)).set_duration(duration))

    for stock in all_stocks[:5]:
        symbol  = stock['symbol']
        summary = stock.get('analysis', '') 
        
        # [휴장일 분기 처리]
        if is_market_closed:
            price_disp  = ""      # 휴장 시 빈칸
            change_disp = ""      # 휴장 시 빈칸
            color       = 'gray'
        else:
            price_disp  = stock.get('price', '')
            change_disp = stock.get('change_str', '')
            color       = '#3366ff' if '-' in change_disp else '#ff3333'
        
        # Render Rows
        clips.append(create_safe_text_clip(symbol, fontsize=35, color='white').set_position((80, start_y)).set_duration(duration))
        
        if price_disp:
            clips.append(create_safe_text_clip(price_disp, fontsize=28, color='#ffd700').set_position((280, start_y+5)).set_duration(duration))
        
        if change_disp:
            clips.append(create_safe_text_clip(change_disp, fontsize=26, color=color).set_position((480, start_y+5)).set_duration(duration))
        
        # Summary는 휴장 여부와 상관없이 표시
        clips.append(create_safe_text_clip(summary, fontsize=18, color='#cccccc', method='caption', size=(550, None), align='West')
                     .set_position((680, start_y+8)).set_duration(duration))
        
        clips.append(ColorClip(size=(1150, 1), color=(50,50,50)).set_position(('center', start_y + row_height - 10)).set_duration(duration))
        start_y += row_height

    return CompositeVideoClip(clips).set_audio(audio_clip)


# [SCENE 4] Stock Chart (Handles Closed Market) -------------------------------------

def create_scene_stock_chart(script_text, stock_data, date_str, is_market_closed):
    symbol = stock_data.get('symbol', 'INDEX')
    print(f"🎬 Scene 4: Analysis ({symbol})", flush=True)
    
    audio_path = create_voice_file(script_text, "scene4.mp3")
    if not audio_path: return None
    audio_clip = AudioFileClip(audio_path)
    duration   = audio_clip.duration + 1.0
    
    clips = [ColorClip(size=(1280, 720), color=(0, 0, 0), duration=duration)]
    clips.extend(create_title_strip(f"{symbol} Analysis", bg_color=(20, 20, 20), duration=duration))
    if date_str: clips.append(create_date_stamp(date_str, duration))

    if is_market_closed:
        # [휴장일] 차트 생성 생략
        msg = "증시 정보 없음 (No Market Data)\n휴장일 또는 데이터 수집 불가"
        clips.append(create_safe_text_clip(msg, fontsize=50, color='#555555', align='center')
                     .set_position('center').set_duration(duration))
    else:
        # [개장일] 차트 생성 및 표시
        chart_img, info = create_chart_image(symbol)
        
        if chart_img and os.path.exists(chart_img):
            price      = info['price']
            change_str = info['pct']
            color      = info['color']
            
            left_x = 80; base_y = 200
            clips.append(create_safe_text_clip(f"{symbol} / USD", fontsize=25, color='#888888').set_position((left_x, base_y)).set_duration(duration))
            clips.append(create_safe_text_clip(price, fontsize=80, color='white').set_position((left_x, base_y + 40)).set_duration(duration))
            clips.append(create_safe_text_clip(change_str, fontsize=40, color=color).set_position((left_x, base_y + 140)).set_duration(duration))
            
            chart_clip = ImageClip(chart_img).resize(height=520).set_position((520, 160)).set_duration(duration)
            clips.append(chart_clip)
        else:
            clips.append(create_safe_text_clip("Chart Unavailable", fontsize=50, color='#555555').set_position('center').set_duration(duration))

    return CompositeVideoClip(clips).set_audio(audio_clip)


# [SCENE 5] YouTube Insight -------------------------------------

def create_scene_youtube(script_text, youtube_list, date_str):
    print("🎬 Scene 5: YouTube Insight", flush=True)
    
    audio_path = create_voice_file(script_text, "scene5.mp3")
    if not audio_path: return None
    audio_clip = AudioFileClip(audio_path)
    duration   = audio_clip.duration + 1.0
    
    clips = [ColorClip(size=(1280, 720), color=(25, 20, 20), duration=duration)] 
    clips.extend(create_title_strip("YouTube Insight", bg_color=(150, 0, 0), duration=duration))
    if date_str: clips.append(create_date_stamp(date_str, duration))
    
    start_y = 170
    for vid in youtube_list[:4]:
        channel = sanitize_text(vid.get('channel_name', 'Channel'))
        summary = sanitize_text(vid.get('summary', vid.get('title', '')))
        
        ch_clip = create_safe_text_clip(f"[{channel}]", fontsize=24, color='#ffd700', align='West')\
                  .set_position((80, start_y)).set_duration(duration)
        clips.append(ch_clip)
        
        txt_clip = create_safe_text_clip(summary, fontsize=26, color='white', method='caption', size=(1000, None), align='West')\
                   .set_position((80 + ch_clip.w + 15, start_y)).set_duration(duration)
        clips.append(txt_clip)
        
        start_y += max(ch_clip.h, txt_clip.h) + 35

    return CompositeVideoClip(clips).set_audio(audio_clip)


# [SCENE 6] Outro (With Disclaimer) -------------------------------------

def create_scene_outro(script_text, stocks, keywords, youtube, date_str):
    print("🎬 Scene 6: Outro", flush=True)
    
    audio_path = create_voice_file(script_text, "scene6.mp3")
    if not audio_path: return None
    audio_clip = AudioFileClip(audio_path)
    duration   = audio_clip.duration + 1.0
    
    clips = [ColorClip(size=(1280, 720), color=(0, 0, 0), duration=duration)]
    if date_str: clips.append(create_date_stamp(date_str, duration))
    
    left_x = 100
    y_pos  = 220 
    gap    = 80
    
    clips.append(create_safe_text_clip("Reference Info", fontsize=60, color='white').set_position((left_x, 80)).set_duration(duration))
    
    # Stocks & Keywords
    stock_names = [s['symbol'] for s in stocks[:4]] if stocks else ["N/A"]
    stock_str   = ", ".join(stock_names)
    clips.append(create_safe_text_clip(f"• Stocks : {stock_str}", fontsize=35, color='#cccccc').set_position((left_x, y_pos)).set_duration(duration))
    
    key_str = ", ".join(keywords[:3]) if isinstance(keywords, list) else "Global, Market"
    clips.append(create_safe_text_clip(f"• Keywords : {key_str}", fontsize=35, color='#cccccc').set_position((left_x, y_pos + gap)).set_duration(duration))
    
    channel_names = list(set([y.get('channel_name', '') for y in youtube[:5] if y.get('channel_name')]))
    ch_str        = ", ".join(channel_names[:4])
    clips.append(create_safe_text_clip(f"• Channels : {ch_str}", fontsize=35, color='#cccccc', method='caption', size=(1100, None), align='West')
                 .set_position((left_x, y_pos + gap*2)).set_duration(duration))
    
    # [Disclaimer - 정책 준수 필수 사항]
    disclaimer = """
⚠️ 알림 (Disclaimer)
이 영상은 AI를 통해 자동 생성되었습니다. 투자의 책임은 본인에게 있습니다.
(Data: Yahoo Finance / Analysis: Gemini / Voice: Edge-TTS)
    """
    clips.append(create_safe_text_clip(disclaimer, fontsize=20, color='#555555', align='center')
                 .set_position(('center', 600)).set_duration(duration))

    return CompositeVideoClip(clips).set_audio(audio_clip)


# -----------------------------------------------------------------------------------------------------------------------------#
# Main Module Entry
# -----------------------------------------------------------------------------------------------------------------------------#
def make_video_module(scene_scripts, structured_data, date_str):
    print("\n🚀 [Video Studio] 영상 제작 프로세스 시작...", flush=True)
    
    stocks  = structured_data.get('stocks', [])
    news    = structured_data.get('news', [])
    youtube = structured_data.get('youtube', [])
    
    # [Critical Check] 휴장일 판단 로직 (Strict)
    # 1. Stocks 리스트가 비어있음
    # 2. 첫 번째 종목의 Price가 없거나, 'N/A', '-' 인 경우
    is_market_closed = False
    
    if not stocks:
        is_market_closed = True
    else:
        first_price = stocks[0].get('price', 'N/A')
        if first_price in ['N/A', '-', 'Market Closed', None, '']:
            is_market_closed = True
            
    print(f"🔒 [System] Market Status: {'CLOSED (No Data)' if is_market_closed else 'OPEN'}", flush=True)
    
    final_clips = []
    
    # Scene 1: Market Map
    s1 = create_scene_market(scene_scripts.get('scene1', '시장입니다.'), date_str, is_market_closed)
    if s1: final_clips.append(s1)
    
    # Scene 2: News
    s2 = create_scene_news(scene_scripts.get('scene2', '뉴스입니다.'), news, date_str)
    if s2: final_clips.append(s2)
    
    # Scene 3: Stock List
    s3 = create_scene_stock_list(scene_scripts.get('scene3', '주식 목록입니다.'), stocks, date_str, is_market_closed)
    if s3: final_clips.append(s3)
    
    # Scene 4: Stock Chart
    # stocks가 비어있어도 에러나지 않도록 더미 데이터 제공
    target_stock = stocks[0] if stocks else {'symbol': 'INDEX', 'price': 'N/A', 'change_str': '0%'}
    s4 = create_scene_stock_chart(scene_scripts.get('scene4', '차트입니다.'), target_stock, date_str, is_market_closed)
    if s4: final_clips.append(s4)
    
    # Scene 5: YouTube
    s5 = create_scene_youtube(scene_scripts.get('scene5', '유튜브입니다.'), youtube, date_str)
    if s5: final_clips.append(s5)
    
    # Scene 6: Outro
    keywords = ["Economy", "Trend", "Analysis"]
    s6 = create_scene_outro(scene_scripts.get('scene6', '감사합니다.'), stocks, keywords, youtube, date_str)
    if s6: final_clips.append(s6)

    # Rendering
    if not final_clips: 
        print("❌ 생성된 클립이 없습니다.", flush=True)
        return None

    print(f"🔄 {len(final_clips)}개의 씬 병합 및 렌더링 시작...", flush=True)
    
    final_video     = concatenate_videoclips(final_clips, method="compose")
    output_filename = f"daily_brief_{date_str}.mp4"
    
    final_video.write_videofile(
        output_filename, 
        fps=24, 
        codec='libx264', 
        audio_codec='aac', 
        threads=4, 
        logger=None # MoviePy 기본 로거 숨김 (깔끔한 출력 위해)
    )
    
    print(f"✅ 영상 제작 완료: {output_filename}", flush=True)
    return output_filename
    
# -----------------------------------------------------------------------------------------------------------------------------#