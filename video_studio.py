import os
import sys
import time
import asyncio
import re
import numpy as np
from datetime import datetime
import edge_tts
from moviepy.editor import *
from moviepy.config import change_settings
from PIL import Image, ImageDraw, ImageFont
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# [LOGGING FIX]
sys.stdout.reconfigure(line_buffering=True)
if os.name != 'nt':
    change_settings({"IMAGEMAGICK_BINARY": "/usr/bin/convert"})

# -----------------------------------------------------------------------------------------------------------------------------#
# [CORE] Safety Text System
# -----------------------------------------------------------------------------------------------------------------------------#
def get_safe_font():
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
    try:
        safe_text = sanitize_text(text)
        if 'font' not in kwargs:
            kwargs['font'] = SAFE_FONT
        return TextClip(safe_text, **kwargs)
    except Exception as e:
        print(f"⚠️ 텍스트 생성 실패: {e}", flush=True)
        return ColorClip(size=(10, 10), color=(0,0,0)).set_opacity(0).set_duration(kwargs.get('duration', 1))

# -----------------------------------------------------------------------------------------------------------------------------#
# [NEW] Dynamic Audio & Subtitle Generator
# -----------------------------------------------------------------------------------------------------------------------------#

def strip_markdown_for_tts(text):
    """
    TTS용 텍스트에서 마크다운 기호를 제거합니다.
    예: "**테슬라**가 급등" → "테슬라가 급등"
    """
    if not text:
        return text
    # 볼드/이탤릭 (**text**, *text*, __text__, _text_)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # **bold**
    text = re.sub(r'\*([^*]+)\*', r'\1', text)      # *italic*
    text = re.sub(r'__([^_]+)__', r'\1', text)      # __bold__
    text = re.sub(r'_([^_]+)_', r'\1', text)        # _italic_
    # 취소선 (~~text~~)
    text = re.sub(r'~~([^~]+)~~', r'\1', text)
    # 헤더 (# ## ###)
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    # 링크 [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # 코드 블록 (`code`)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    return text.strip()

async def _gen_voice_file(text, filename):
    # TTS로 보내기 전에 마크다운 기호 제거
    clean_text = strip_markdown_for_tts(text)
    communicate = edge_tts.Communicate(clean_text, "ko-KR-SunHiNeural")
    await communicate.save(filename)

def generate_dynamic_audio_and_subs(script_text, scene_name):
    sentences = re.split(r'(?<=[.?!])\s+', script_text.strip())
    sentences = [s for s in sentences if s.strip()]
    
    audio_clips = []
    text_clips = []
    current_time = 0.0
    
    temp_dir = "temp_audio"
    if not os.path.exists(temp_dir): os.makedirs(temp_dir)
    
    print(f"   🎙️ 오디오/자막 생성 중 ({len(sentences)} 문장)...")
    
    for i, sent in enumerate(sentences):
        fname = os.path.join(temp_dir, f"{scene_name}_{i}.mp3")
        try:
            loop = asyncio.get_event_loop_policy().get_event_loop()
            loop.run_until_complete(_gen_voice_file(sent, fname))
            
            aclip = AudioFileClip(fname)
            dur = aclip.duration
            
            bar_h = 100
            bar_y = 720 - bar_h
            bg_bar = ColorClip(size=(1280, bar_h), color=(0,0,0))\
                     .set_opacity(0.85)\
                     .set_position((0, bar_y))\
                     .set_start(current_time)\
                     .set_duration(dur)
            
            # 자막 위치 상향 조정 (bar_y + 10)
            txt_clip = create_safe_text_clip(sent, fontsize=28, color='white', method='caption', size=(1200, None))\
                       .set_position(('center', bar_y + 10))\
                       .set_start(current_time)\
                       .set_duration(dur)
            
            audio_clips.append(aclip)
            text_clips.append(bg_bar)
            text_clips.append(txt_clip)
            
            current_time += dur
            
        except Exception as e:
            print(f"⚠️ 문장 처리 실패: {sent} / {e}")
            continue

    if not audio_clips: return None, []
    final_audio = concatenate_audioclips(audio_clips)
    return final_audio, text_clips

# -----------------------------------------------------------------------------------------------------------------------------#
# Helper Functions (FIXED)
# -----------------------------------------------------------------------------------------------------------------------------#
def create_date_stamp(date_str, duration):
    if not date_str: return None
    
    # [수정 완료] 람다 함수 제거 -> 고정 좌표 계산 방식 적용
    # 1. 텍스트 클립 생성
    txt_clip = create_safe_text_clip(f"Date: {date_str}", fontsize=24, color='#888888', align='East')
    
    # 2. 너비(w)를 미리 구해서 x좌표 계산 (1280 - 너비 - 40)
    # TextClip은 생성되자마자 w 속성을 가집니다.
    x_pos = 1280 - txt_clip.w - 40
    
    # 3. 계산된 좌표 적용
    return txt_clip.set_position((x_pos, 30)).set_duration(duration)

def create_title_strip(text, fontsize=45, bg_color=(0,0,0), text_color='white', position=('center', 40), duration=5):
    strip_bg = ColorClip(size=(1280, 110), color=bg_color)\
                .set_opacity(0.9)\
                .set_position(('center', position[1]-10))\
                .set_duration(duration)
    txt_clip = create_safe_text_clip(text, fontsize=fontsize, color=text_color)\
                .set_position(('center', position[1] + 10))\
                .set_duration(duration)
    return [strip_bg, txt_clip]

def build_scene_base(duration, title_text, date_str=None, bg_color=(0,0,0)):
    clips = [ColorClip(size=(1280, 720), color=bg_color, duration=duration)]
    if title_text:
        clips.extend(create_title_strip(title_text, position=('center', 30), duration=duration))
    if date_str:
        clips.append(create_date_stamp(date_str, duration))
    return clips

# -----------------------------------------------------------------------------------------------------------------------------#
# External Data Capture
# -----------------------------------------------------------------------------------------------------------------------------#
def capture_tradingview_map(output_file="tradingview_map.png"):
    print("📸 TradingView 맵 캡처 시도...", flush=True)
    driver = None
    try:
        chrome_options = Options()
        chrome_options.binary_location = "/usr/bin/chromium"
        chrome_options.add_argument('--headless=new') 
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--remote-debugging-port=9222')
        chrome_options.add_argument('--window-size=1920,1200')
        
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        chrome_options.add_argument(f'user-agent={user_agent}')

        if os.path.exists("/usr/bin/chromedriver"):
            service = ChromeService(executable_path="/usr/bin/chromedriver")
            driver = webdriver.Chrome(service=service, options=chrome_options)
        else:
            driver = webdriver.Chrome(options=chrome_options)

        driver.set_page_load_timeout(40)
        url = "https://www.tradingview.com/heatmap/stock/?color=change&dataset=SPX500&group=sector&size=market_cap_basic"
        
        driver.get(url)
        time.sleep(15)

        try:
            driver.execute_script("""
                var header = document.querySelector('.tv-header'); if(header) header.style.display = 'none';
                var cookies = document.querySelectorAll('[class*="cookie"]'); cookies.forEach(el => el.remove());
                var toolbar = document.querySelector('.tv-side-toolbar'); if(toolbar) toolbar.style.display = 'none';
            """)
        except: pass
        
        driver.save_screenshot(output_file)
        if os.path.exists(output_file):
            img = Image.open(output_file)
            width, height = img.size
            cropped_img = img.crop((0, 0, width, height))
            cropped_img.save(output_file)
            print("   ✅ TradingView 캡처 완료", flush=True)
            return output_file
        return None
    except Exception as e:
        print(f"⚠️ 캡처 실패: {e}", flush=True)
        return None
    finally:
        if driver: 
            try: driver.quit()
            except: pass

def create_chart_image(symbol):
    print(f"📊 차트 생성 시도: {symbol}", flush=True)
    try:
        ticker = yf.Ticker(symbol)
        hist   = ticker.history(period="1d", interval="5m")
        if hist.empty: return None, None

        last_price      = hist['Close'].iloc[-1]
        real_prev_close = ticker.fast_info.previous_close if hasattr(ticker.fast_info, 'previous_close') else hist['Close'].iloc[0]
        
        diff        = last_price - real_prev_close
        pct         = (diff / real_prev_close) * 100
        color_trend = '#ff3333' if diff > 0 else '#3366ff'

        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(12, 8)) # 차트 폭 확대 유지
        
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
        
        info = {'symbol': symbol, 'price': f"${last_price:.2f}", 'color': color_trend}
        return output_file, info
    except Exception as e:
        print(f"   ⚠️ 차트 에러: {e}", flush=True)
        return None, None


# -----------------------------------------------------------------------------------------------------------------------------#
# Scene Generators
# -----------------------------------------------------------------------------------------------------------------------------#

# [SCENE 1] Market Map
def create_scene_market(script_text, date_str, is_market_closed, economy_data=None):
    print(f"🎬 Scene 1: Market Overview", flush=True)
    audio, subtitle_clips = generate_dynamic_audio_and_subs(script_text, "scene1")
    if not audio: return None
    
    duration = audio.duration + 1.0
    clips    = build_scene_base(duration, "Global Market Map", None) 
    
    if is_market_closed:
        msg = "미국 증시 휴장 (Market Closed)"
        clips.append(create_safe_text_clip(msg, fontsize=50, color='gray').set_position('center').set_duration(duration))
    else:
        sector_txt = economy_data.get('sector_summary', "Market Trend Analysis") if economy_data else "Market Trend Analysis"
        clips.append(create_safe_text_clip(f"Condition: {sector_txt}", fontsize=26, color='#ffdd55')
                     .set_position(('center', 110)).set_duration(duration))

        map_img = capture_tradingview_map()
        if map_img and os.path.exists(map_img):
            img_clip = ImageClip(map_img).resize(height=380).set_position(('center', 160)).set_duration(duration)
            clips.append(img_clip)
        else:
            clips.append(create_safe_text_clip("Map Unavailable", fontsize=60, color='gray').set_position('center').set_duration(duration))

    return CompositeVideoClip(clips + subtitle_clips).set_audio(audio)


# [SCENE 2] News
def create_scene_news(script_text, news_list, date_str):
    print("🎬 Scene 2: News", flush=True)
    audio, subtitle_clips = generate_dynamic_audio_and_subs(script_text, "scene2")
    if not audio: return None
    duration = audio.duration + 1.0
    clips = build_scene_base(duration, "Global Economic News", date_str, bg_color=(15, 20, 35))
    
    start_y = 150
    for news in news_list[:3]:
        title = news.get('title', 'News')
        detail = news.get('detail', '')
        source = news.get('source', '')
        t_clip = create_safe_text_clip(f"• {title}", fontsize=26, color='#ffd700', method='caption', size=(1100, None), align='West').set_position((80, start_y)).set_duration(duration)
        clips.append(t_clip)
        current_h = t_clip.h
        if detail:
            d_clip = create_safe_text_clip(f"   - {detail}", fontsize=20, color='#dddddd', method='caption', size=(1050, None), align='West').set_position((100, start_y + current_h + 5)).set_duration(duration)
            clips.append(d_clip)
            current_h += d_clip.h + 5
        s_clip = create_safe_text_clip(f"   [{source}]", fontsize=16, color='#aaaaaa', align='West').set_position((100, start_y + current_h + 3)).set_duration(duration)
        clips.append(s_clip)
        start_y += (current_h + s_clip.h + 25)
    return CompositeVideoClip(clips + subtitle_clips).set_audio(audio)

# [SCENE 2.5] Economy
def create_scene_economy(script_text, economy_data):
    print("🎬 Scene 2.5: Economy", flush=True)
    audio, subtitle_clips = generate_dynamic_audio_and_subs(script_text, "scene2_5")
    if not audio: return None
    duration = audio.duration + 1.0
    clips = build_scene_base(duration, "Economic Calendar & Sentiment", bg_color=(10, 15, 20))

    calendar = economy_data.get('calendar', [])
    clips.append(create_safe_text_clip("📅 Upcoming Events", fontsize=35, color='#ffd700', align='West').set_position((100, 150)).set_duration(duration))
    y_pos = 220
    if calendar:
        for event in calendar[:3]:
            clips.append(create_safe_text_clip(f"• {event}", fontsize=24, color='white', align='West').set_position((120, y_pos)).set_duration(duration))
            y_pos += 50
    else:
        clips.append(create_safe_text_clip("No major events.", fontsize=24, color='gray').set_position((120, y_pos)).set_duration(duration))

    fg_val = str(economy_data.get('fear_greed_index', 'N/A'))
    fg_state = economy_data.get('market_sentiment', '')
    clips.append(create_safe_text_clip("🧠 Fear & Greed", fontsize=35, color='#ffd700').set_position((750, 150)).set_duration(duration))
    try:
        val_num = int(re.sub(r'[^0-9]', '', fg_val))
        color = '#ff3333' if val_num < 25 else ('#33ff33' if val_num > 75 else '#ffffff')
    except:
        val_num = fg_val
        color = 'white'
    clips.append(create_safe_text_clip(f"{fg_val}", fontsize=100, color=color, font="Impact").set_position((820, 220)).set_duration(duration))
    if fg_state:
        clips.append(create_safe_text_clip(f"({fg_state})", fontsize=35, color='#cccccc').set_position((820, 350)).set_duration(duration))
    return CompositeVideoClip(clips + subtitle_clips).set_audio(audio)

# [SCENE 3] Stock List
def create_scene_stock_list(script_text, all_stocks, date_str, is_market_closed):
    print(f"🎬 Scene 3: Stock List", flush=True)
    audio, subtitle_clips = generate_dynamic_audio_and_subs(script_text, "scene3")
    if not audio: return None
    duration = audio.duration + 1.0
    clips = build_scene_base(duration, "Market Watchlist", date_str, bg_color=(10, 10, 10))
    start_y = 150
    row_height = 110 
    headers = [("Ticker", 80), ("Price", 250), ("Change", 420), ("Headline Summary", 700)]
    for text, x_pos in headers:
        clips.append(create_safe_text_clip(text, fontsize=24, color='gray').set_position((x_pos, 110)).set_duration(duration))
    for stock in all_stocks[:4]:
        symbol = stock['symbol']
        summary = stock.get('video_summary', '')
        change_disp = stock.get('change_str', '')
        price_disp = stock.get('price', '')
        color = '#3366ff' if '-' in change_disp else '#ff3333'
        if is_market_closed: price_disp, change_disp, color = "", "", "gray"
        clips.append(create_safe_text_clip(symbol, fontsize=32, color='white').set_position((80, start_y)).set_duration(duration))
        if price_disp: clips.append(create_safe_text_clip(price_disp, fontsize=26, color='#ffd700').set_position((250, start_y+5)).set_duration(duration))
        if change_disp: clips.append(create_safe_text_clip(change_disp, fontsize=22, color=color).set_position((420, start_y+8)).set_duration(duration))
        clips.append(create_safe_text_clip(summary, fontsize=18, color='#cccccc', method='caption', size=(530, None), align='West').set_position((700, start_y)).set_duration(duration))
        clips.append(ColorClip(size=(1150, 1), color=(50,50,50)).set_position(('center', start_y + row_height - 10)).set_duration(duration))
        start_y += row_height
    return CompositeVideoClip(clips + subtitle_clips).set_audio(audio)


# [SCENE 4] Chart
def create_scene_stock_chart(script_text, stock_data, date_str, is_market_closed):
    symbol = stock_data.get('symbol', 'INDEX')
    print(f"🎬 Scene 4: Analysis ({symbol})", flush=True)
    audio, subtitle_clips = generate_dynamic_audio_and_subs(script_text, "scene4")
    if not audio: return None
    duration = audio.duration + 1.0
    clips = build_scene_base(duration, f"{symbol} Analysis", date_str, bg_color=(0, 0, 0))
    if not is_market_closed:
        chart_img, info = create_chart_image(symbol)
        if chart_img and os.path.exists(chart_img):
            price = info['price']
            change_str = stock_data.get('change_str', '')
            color = info['color']
            left_x, base_y = 80, 200
            clips.append(create_safe_text_clip(f"{symbol} / USD", fontsize=25, color='#888888').set_position((left_x, base_y)).set_duration(duration))
            clips.append(create_safe_text_clip(price, fontsize=80, color='white').set_position((left_x, base_y + 40)).set_duration(duration))
            clips.append(create_safe_text_clip(change_str, fontsize=40, color=color).set_position((left_x, base_y + 140)).set_duration(duration))
            # 차트 높이 450 유지, 폭은 이미지 비율에 따라 자동 조절됨 (생성 시 12:8 비율)
            chart_clip = ImageClip(chart_img).resize(height=450).set_position((520, 160)).set_duration(duration)
            clips.append(chart_clip)
    return CompositeVideoClip(clips + subtitle_clips).set_audio(audio)


# [SCENE 5] YouTube
def create_scene_youtube(script_text, youtube_list, date_str):
    print("🎬 Scene 5: YouTube", flush=True)
    audio, subtitle_clips = generate_dynamic_audio_and_subs(script_text, "scene5")
    if not audio: return None
    
    duration      = audio.duration + 1.0
    clips         = build_scene_base(duration, "YouTube Insight", date_str, bg_color=(25, 20, 20))
    clips.extend(create_title_strip("YouTube Insight", bg_color=(150, 0, 0), duration=duration))
    
    start_y       = 170
    for vid in youtube_list[:4]:
        channel  = sanitize_text(vid.get('channel_name', 'Channel'))
        summary  = sanitize_text(vid.get('summary', vid.get('title', '')))
        ch_clip  = create_safe_text_clip(f"[{channel}]", fontsize=24, color='#ffd700', align='West').set_position((80, start_y)).set_duration(duration)
        clips.append(ch_clip)
        txt_clip = create_safe_text_clip(summary, fontsize=26, color='white', method='caption', size=(1000, None), align='West').set_position((80 + ch_clip.w + 15, start_y)).set_duration(duration)
        clips.append(txt_clip)
        start_y += max(ch_clip.h, txt_clip.h) + 35
    return CompositeVideoClip(clips + subtitle_clips).set_audio(audio)

# [SCENE 6] Outro
def create_scene_outro(script_text, stocks, news_list, youtube, date_str):
    print("🎬 Scene 6: Outro", flush=True)
    audio, subtitle_clips = generate_dynamic_audio_and_subs(script_text, "scene6")
    if not audio: return None
    duration = audio.duration + 1.0

    clips = build_scene_base(duration, "Closing", date_str)
    
    left_x = 100
    y_pos  = 180 
    
    clips.append(create_safe_text_clip("Reference Info", fontsize=50, color='white').set_position((left_x, 80)).set_duration(duration))
    
    # 1. Stocks
    stock_names = [s['symbol'] for s in stocks[:5]] if stocks else ["N/A"]
    clips.append(create_safe_text_clip(f"• Stocks : {', '.join(stock_names)}", fontsize=30, color='#cccccc').set_position((left_x, y_pos)).set_duration(duration))
    
    # 2. Keywords
    keywords = ["Global Market", "Economy"]
    if news_list:
        keywords = [n.get('title', '').split()[0] for n in news_list[:3]]
    keyword_str = ", ".join(keywords)
    clips.append(create_safe_text_clip(f"• Keywords : {keyword_str}", fontsize=30, color='#cccccc').set_position((left_x, y_pos + 60)).set_duration(duration))
    
    # 3. Channels
    channels = [y.get('channel_name', 'YouTube') for y in youtube[:3]]
    channel_str = ", ".join(channels)
    clips.append(create_safe_text_clip(f"• Channels : {channel_str}", fontsize=30, color='#cccccc').set_position((left_x, y_pos + 120)).set_duration(duration))

    disclaimer = """⚠️ 알림 (Disclaimer)\n이 영상은 AI를 통해 자동 생성되었습니다. 투자의 책임은 본인에게 있습니다.\n(Data: Yahoo Finance / Analysis: Gemini / Voice: Edge-TTS)"""
    clips.append(create_safe_text_clip(disclaimer, fontsize=20, color='#555555', align='center').set_position(('center', 480)).set_duration(duration))

    return CompositeVideoClip(clips + subtitle_clips).set_audio(audio)


# [MAIN] Module
def make_video_module(scene_scripts, structured_data, date_str):
    print("\n🚀 [Video Studio] 영상 제작 시작...", flush=True)
    stocks  = structured_data.get('stocks', [])
    news    = structured_data.get('news', [])
    youtube = structured_data.get('youtube', [])
    economy = structured_data.get('economy', {})
    
    final_clips = []
    
    s1 = create_scene_market(scene_scripts.get('scene1', '시장 동향입니다.'), date_str, False, economy)
    if s1: final_clips.append(s1)

    s2 = create_scene_news(scene_scripts.get('scene2', '뉴스'), news, date_str)
    if s2: final_clips.append(s2)
    
    s2_5 = create_scene_economy(scene_scripts.get('scene2_5', '경제'), economy)
    if s2_5: final_clips.append(s2_5)
    
    s3 = create_scene_stock_list(scene_scripts.get('scene3', '주식'), stocks, date_str, False)
    if s3: final_clips.append(s3)

    target_stock = stocks[0] if stocks else {'symbol': 'INDEX', 'price':'0', 'change_str':'0%'}
    s4 = create_scene_stock_chart(scene_scripts.get('scene4', '차트'), target_stock, date_str, False)
    if s4: final_clips.append(s4)

    s5 = create_scene_youtube(scene_scripts.get('scene5', '유튜브'), youtube, date_str)
    if s5: final_clips.append(s5)

    s6 = create_scene_outro(scene_scripts.get('scene6', '감사합니다.'), stocks, news, youtube, date_str)
    if s6: final_clips.append(s6)

    if not final_clips: 
        print("❌ 생성된 클립 없음.", flush=True)
        return None

    final_video = concatenate_videoclips(final_clips, method="compose")
    output_filename = f"daily_brief_{date_str}.mp4"
    final_video.write_videofile(output_filename, fps=24, codec='libx264', audio_codec='aac', threads=4, logger=None)
    print(f"✅ 영상 제작 완료: {output_filename}", flush=True)
    return output_filename