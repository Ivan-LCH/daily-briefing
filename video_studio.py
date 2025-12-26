# ===================================================================================================================
# Import
# ===================================================================================================================
import os
import time
import asyncio
import edge_tts
import yfinance as yf
import re
import numpy as np
from datetime import datetime

from moviepy.editor import *
from moviepy.config import change_settings
from PIL import Image
import matplotlib
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# ImageMagick (Linux)
change_settings({"IMAGEMAGICK_BINARY": "/usr/bin/convert"})


# ===================================================================================================================
# [CORE] Safety Text System
# ===================================================================================================================

def get_safe_font():
    possible_paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"
    ]
    for p in possible_paths:
        if os.path.exists(p): return p
    return "Noto-Sans-CJK-KR"

SAFE_FONT = get_safe_font()

def sanitize_text(text):
    if not text: return " "
    text = str(text)
    clean = re.sub(r'[^\u0000-\uD7FF\uE000-\uFFFF]', '', text)
    clean = clean.strip()
    return clean if clean else " "

def create_safe_text_clip(text, **kwargs):
    try:
        safe_text = sanitize_text(text)
        if 'font' not in kwargs: kwargs['font'] = SAFE_FONT
        return TextClip(safe_text, **kwargs)
    except Exception as e:
        print(f"⚠️ 텍스트 생성 실패 (Skipped): '{text}' -> {e}")
        return ColorClip(size=(10, 10), color=(0,0,0)).set_opacity(0).set_duration(kwargs.get('duration', 1))


# ===================================================================================================================
# Helper Functions
# ===================================================================================================================

async def _generate_voice(text, filename):
    clean_text = sanitize_text(text)
    clean_text = re.sub(r'\([^)]*\)', '', clean_text)
    clean_text = clean_text.replace('*', '').replace('"', '').replace("'", "")
    communicate = edge_tts.Communicate(clean_text, "ko-KR-SunHiNeural")
    await communicate.save(filename)

def create_voice_file(text, filename):
    try:
        loop = asyncio.get_event_loop_policy().get_event_loop()
        loop.run_until_complete(_generate_voice(text, filename))
        return filename
    except: return None

# [Design] 공통 날짜 스탬프 (우측 상단)
def create_date_stamp(date_str, duration):
    if not date_str: return None
    # 전문적인 표기 (예: Date: 2025-12-24)
    return create_safe_text_clip(f"Date: {date_str}", fontsize=24, color='#888888', align='East')\
           .set_position((1080, 30)).set_duration(duration)

def create_title_strip(text, fontsize=45, bg_color=(0,0,0), text_color='white', position=('center', 40), duration=5):
    """ 제목 띠 생성 """
    strip_bg = ColorClip(size=(1280, 110), color=bg_color).set_opacity(0.9).set_position(('center', position[1]-10)).set_duration(duration)
    txt_clip = create_safe_text_clip(text, fontsize=fontsize, color=text_color)\
               .set_position(('center', position[1] + 10)).set_duration(duration)
    return [strip_bg, txt_clip]

def capture_finviz_map(output_file="finviz_map.png"):
    print("📸 Finviz 맵 캡처 시도 중...")
    driver = None
    try:
        chrome_options = Options()
        chrome_options.add_argument('--headless') 
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.page_load_strategy = 'eager' 
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36")
        
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(40)
        
        driver.get("https://finviz.com/map.ashx")
        time.sleep(8) 
        
        driver.save_screenshot(output_file)
        
        if os.path.exists(output_file):
            img = Image.open(output_file)
            width, height = img.size
            cropped_img = img.crop((0, 0, width, int(height * 0.85)))
            cropped_img.save(output_file)

        print(f"   - 캡처 완료: {output_file}")
        return output_file
        
    except Exception as e:
        print(f"⚠️ 캡처 실패: {e}")
        return None
    finally:
        if driver:
            try: driver.quit()
            except: pass

def create_chart_image(symbol):
    """ [Page 4] 차트 생성 (데이터 없으면 None) """
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d", interval="5m")
        is_intraday = True

        if hist.empty: return None

        last_dt = hist.index[-1]
        last_price = hist['Close'].iloc[-1]
        
        info = ticker.fast_info
        real_prev_close = info.previous_close if hasattr(info, 'previous_close') else hist['Close'].iloc[0]

        diff = last_price - real_prev_close
        pct  = (diff / real_prev_close) * 100
        
        if diff > 0:
            color_trend = '#ff3333'
            sign = "+"
        else:
            color_trend = '#3366ff'
            sign = ""

        left_info = {
            'symbol': symbol,
            'price': f"${last_price:.2f}",
            'diff': f"{sign}{diff:.2f}",
            'pct': f"({sign}{pct:.2f}%)",
            'prev_close': f"${real_prev_close:.2f}",
            'color': color_trend
        }

        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 8))
        ax.set_facecolor('#121212') 
        fig.patch.set_facecolor('#000000')
        
        ax.plot(hist.index, hist['Close'], color=color_trend, linewidth=2.5)
        ax.fill_between(hist.index, hist['Close'], hist['Close'].min(), color=color_trend, alpha=0.15)
        ax.axhline(y=real_prev_close, color='white', linestyle='--', linewidth=1, alpha=0.6)

        max_price = hist['Close'].max()
        min_price = hist['Close'].min()
        
        ax.axhline(y=max_price, color='#ffd700', linestyle=':', linewidth=0.5, alpha=0.5)
        ax.text(hist.index[0], max_price, f" High: ${max_price:.2f}", color='#ffd700', fontsize=12, fontweight='bold', va='bottom')
        
        ax.axhline(y=min_price, color='#00ffff', linestyle=':', linewidth=0.5, alpha=0.5)
        ax.text(hist.index[0], min_price, f" Low: ${min_price:.2f}", color='#00ffff', fontsize=12, fontweight='bold', va='top')

        ax.grid(True, linestyle=':', alpha=0.2)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.tick_params(axis='x', colors='#888888')
        ax.tick_params(axis='y', colors='#888888')
        
        if is_intraday:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        else:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        
        output_file = f"{symbol}_chart.png"
        plt.savefig(output_file, bbox_inches='tight', facecolor='black', dpi=100)
        plt.close()
        
        return output_file, left_info
    except Exception as e:
        print(f"Chart Error: {e}")
        return None, None


# ===================================================================================================================
# Scene Generators (All Pages with Date Stamp)
# ===================================================================================================================

# [SCENE 1] Market Overview
def create_scene_market(script_text, date_str):
    print("🎬 Scene 1: Market Overview")
    audio_path = create_voice_file(script_text, "scene1.mp3")
    if not audio_path: return None
    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration + 1.0 

    map_img = capture_finviz_map()
    clips = [ColorClip(size=(1280, 720), color=(0, 0, 0), duration=duration)]
    clips.extend(create_title_strip("Global Market Map (S&P 500)", duration=duration))
    
    # [New] 날짜 표시
    ds = create_date_stamp(date_str, duration)
    if ds: clips.append(ds)

    if map_img and os.path.exists(map_img):
        img_clip = ImageClip(map_img).resize(width=1150).set_position(('center', 160)).set_duration(duration)
        clips.append(img_clip)
    else:
        clips.append(create_safe_text_clip("Market Overview", fontsize=80, color='white').set_position('center').set_duration(duration))

    return CompositeVideoClip(clips).set_audio(audio_clip)


# [SCENE 2] News
def create_scene_news(script_text, news_list, date_str):
    print("🎬 Scene 2: Deep Dive (News)")
    audio_path = create_voice_file(script_text, "scene2.mp3")
    if not audio_path: return None
    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration + 1.0

    clips = [ColorClip(size=(1280, 720), color=(15, 20, 35), duration=duration)]
    clips.extend(create_title_strip("Global Economic News", bg_color=(0, 40, 80), duration=duration))
    
    # [New] 날짜 표시
    ds = create_date_stamp(date_str, duration)
    if ds: clips.append(ds)
    
    start_y = 160
    target_news = news_list[:4]
    
    for news in target_news:
        main_text = news.get('summary', news['title'])
        sub_text = news.get('title', '')
        source = news.get('source', 'News')

        main_clip = create_safe_text_clip(f"• {main_text}", fontsize=26, color='#ffd700', method='caption', size=(1100, None), align='West')\
                     .set_position((80, start_y)).set_duration(duration)
        clips.append(main_clip)
        
        sub_str = f"   [{source}] {sub_text}"
        sub_clip = create_safe_text_clip(sub_str, fontsize=18, color='#aaaaaa', method='caption', size=(1050, None), align='West')\
                   .set_position((80, start_y + main_clip.h + 5)).set_duration(duration)
        clips.append(sub_clip)
        
        start_y += (main_clip.h + sub_clip.h + 30)

    return CompositeVideoClip(clips).set_audio(audio_clip)


# [SCENE 3] Market Watchlist
def create_scene_stock_list(script_text, all_stocks, date_str):
    print(f"🎬 Scene 3: Stock List (Count: {len(all_stocks)})")
    audio_path = create_voice_file(script_text, "scene3.mp3")
    if not audio_path: return None
    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration + 1.0

    clips = [ColorClip(size=(1280, 720), color=(10, 10, 10), duration=duration)]
    clips.extend(create_title_strip("Market Watchlist", bg_color=(20, 20, 20), duration=duration))
    
    # [New] 날짜 표시
    ds = create_date_stamp(date_str, duration)
    if ds: clips.append(ds)
    
    start_y = 160
    row_height = 90
    header_y = 120
    
    # [Layout Fix] Summary 공간 확보
    clips.append(create_safe_text_clip("Ticker", fontsize=25, color='gray').set_position((80, header_y)).set_duration(duration))
    clips.append(create_safe_text_clip("Price", fontsize=25, color='gray').set_position((280, header_y)).set_duration(duration))
    clips.append(create_safe_text_clip("Change", fontsize=25, color='gray').set_position((480, header_y)).set_duration(duration))
    clips.append(create_safe_text_clip("Headline Summary", fontsize=25, color='gray').set_position((680, header_y)).set_duration(duration))

    for stock in all_stocks[:5]:
        symbol = stock['symbol']
        price = stock['price'] 
        change_str = stock['change_str'] 
        summary = stock.get('analysis', '') # 이제 빈칸 아님!
        
        if '-' in change_str: color = '#3366ff' 
        else: color = '#ff3333' 
        
        clips.append(create_safe_text_clip(symbol, fontsize=35, color='white').set_position((80, start_y)).set_duration(duration))
        clips.append(create_safe_text_clip(price, fontsize=28, color='#ffd700').set_position((280, start_y+5)).set_duration(duration))
        clips.append(create_safe_text_clip(change_str, fontsize=26, color=color).set_position((480, start_y+5)).set_duration(duration))
        
        # [Font Fix] 폰트 줄이고 너비 늘림
        clips.append(create_safe_text_clip(summary, fontsize=18, color='#cccccc', method='caption', size=(550, None), align='West')\
                     .set_position((680, start_y+8)).set_duration(duration))
        
        clips.append(ColorClip(size=(1150, 1), color=(50,50,50)).set_position(('center', start_y + row_height - 10)).set_duration(duration))
        start_y += row_height

    return CompositeVideoClip(clips).set_audio(audio_clip)


# [SCENE 4] Stock Chart
def create_scene_stock_chart(script_text, stock_data, date_str):
    symbol = stock_data['symbol']
    print(f"🎬 Scene 4: Stock Chart ({symbol})")
    
    audio_path = create_voice_file(script_text, "scene4.mp3")
    if not audio_path: return None
    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration + 1.0
    
    chart_img, info = create_chart_image(symbol)
    
    clips = [ColorClip(size=(1280, 720), color=(0, 0, 0), duration=duration)]
    clips.extend(create_title_strip(f"{symbol} Technical Analysis", bg_color=(20, 20, 20), duration=duration))
    
    # [New] 날짜 표시
    ds = create_date_stamp(date_str, duration)
    if ds: clips.append(ds)

    price = stock_data['price']
    change_str = stock_data['change_str']
    
    if '-' in change_str: color = '#3366ff'
    else: color = '#ff3333'

    left_x = 80
    base_y = 200
    
    clips.append(create_safe_text_clip(f"{symbol} / USD", fontsize=25, color='#888888').set_position((left_x, base_y)).set_duration(duration))
    clips.append(create_safe_text_clip(price, fontsize=80, color='white').set_position((left_x, base_y + 40)).set_duration(duration))
    clips.append(create_safe_text_clip(change_str, fontsize=40, color=color).set_position((left_x, base_y + 140)).set_duration(duration))

    if chart_img and os.path.exists(chart_img):
        chart_clip = ImageClip(chart_img).resize(height=520).set_position((520, 160)).set_duration(duration)
        clips.append(chart_clip)
    else:
        msg_clip = create_safe_text_clip("Market Closed (No Intraday Data)", fontsize=50, color='#555555')\
                   .set_position((750, 360)).set_duration(duration)
        clips.append(msg_clip)

    return CompositeVideoClip(clips).set_audio(audio_clip)


# [SCENE 5] YouTube
def create_scene_youtube(script_text, youtube_list, date_str):
    print("🎬 Scene 5: YouTube Insight")
    audio_path = create_voice_file(script_text, "scene5.mp3")
    if not audio_path: return None
    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration + 1.0
    
    clips = [ColorClip(size=(1280, 720), color=(25, 20, 20), duration=duration)] 
    clips.extend(create_title_strip("YouTube Insight", bg_color=(150, 0, 0), duration=duration))
    
    # [New] 날짜 표시
    ds = create_date_stamp(date_str, duration)
    if ds: clips.append(ds)
    
    start_y = 170
    target_vids = youtube_list[:4]
    
    for vid in target_vids:
        channel = sanitize_text(vid.get('channel_name', 'Channel'))
        title = sanitize_text(vid.get('title', ''))
        summary = sanitize_text(vid.get('summary', title))
        
        ch_clip = create_safe_text_clip(f"[{channel}]", fontsize=24, color='#ffd700', align='West')\
                  .set_position((80, start_y)).set_duration(duration)
        clips.append(ch_clip)
        
        txt_clip = create_safe_text_clip(summary, fontsize=26, color='white', method='caption', size=(1000, None), align='West')\
                   .set_position((80 + ch_clip.w + 15, start_y)).set_duration(duration)
        clips.append(txt_clip)
        
        start_y += max(ch_clip.h, txt_clip.h) + 35

    return CompositeVideoClip(clips).set_audio(audio_clip)


# [SCENE 6] Outro
def create_scene_outro(script_text, stocks, keywords, youtube, date_str):
    print("🎬 Scene 6: Outro")
    audio_path = create_voice_file(script_text, "scene6.mp3")
    if not audio_path: return None
    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration + 1.0
    
    clips = [ColorClip(size=(1280, 720), color=(0, 0, 0), duration=duration)]
    
    # [New] 날짜 표시
    ds = create_date_stamp(date_str, duration)
    if ds: clips.append(ds)
    
    left_x = 100
    y_pos = 220 
    gap = 80
    
    # 제목
    clips.append(create_safe_text_clip("Reference Info", fontsize=60, color='white').set_position((left_x, 80)).set_duration(duration))
    
    # 1. Stocks
    stock_str = ", ".join([s['symbol'] for s in stocks[:4]])
    clips.append(create_safe_text_clip(f"• Stocks : {stock_str}", fontsize=35, color='#cccccc').set_position((left_x, y_pos)).set_duration(duration))
    
    # 2. Keywords
    if isinstance(keywords, list):
        key_str = ", ".join(keywords[:3])
    else:
        key_str = "Market, Economy"
    clips.append(create_safe_text_clip(f"• Keywords : {key_str}", fontsize=35, color='#cccccc').set_position((left_x, y_pos + gap)).set_duration(duration))
    
    # 3. Channels (채널명 표시)
    channel_names = list(set([y.get('channel_name', '') for y in youtube[:5] if y.get('channel_name')]))
    ch_str = ", ".join(channel_names[:4])
    clips.append(create_safe_text_clip(f"• Channels : {ch_str}", fontsize=35, color='#cccccc', method='caption', size=(1100, None), align='West')\
                 .set_position((left_x, y_pos + gap*2)).set_duration(duration))
    
    clips.append(create_safe_text_clip("Generated by AI Agent (w/ Python)", fontsize=25, color='#555555').set_position((left_x, 600)).set_duration(duration))

    return CompositeVideoClip(clips).set_audio(audio_clip)


# ===================================================================================================================
# [MAIN] Module
# ===================================================================================================================
def make_video_module(scene_scripts, structured_data, date_str):
    print("\n🚀 [Video Studio] 6단계 영상 제작 시작...")
    
    stocks = structured_data['stocks']
    news = structured_data['news']
    youtube = structured_data['youtube']
    
    final_clips = []
    
    # 각 Scene 생성 시 date_str 전달
    s1 = create_scene_market(scene_scripts.get('scene1', '시장입니다.'), date_str)
    if s1: final_clips.append(s1)
    
    s2 = create_scene_news(scene_scripts.get('scene2', '뉴스입니다.'), news, date_str)
    if s2: final_clips.append(s2)
    
    s3 = create_scene_stock_list(scene_scripts.get('scene3', '주요 주식입니다.'), stocks, date_str)
    if s3: final_clips.append(s3)
    
    target_stock = stocks[0] if stocks else {'symbol': 'SPY', 'price': '-', 'change_str': '0'}
    s4 = create_scene_stock_chart(scene_scripts.get('scene4', '차트입니다.'), target_stock, date_str)
    if s4: final_clips.append(s4)
    
    s5 = create_scene_youtube(scene_scripts.get('scene5', '반응입니다.'), youtube, date_str)
    if s5: final_clips.append(s5)
    
    keywords = ["Market", "Economy", "Tech"]
    s6 = create_scene_outro(scene_scripts.get('scene6', '감사합니다.'), stocks, keywords, youtube, date_str)
    if s6: final_clips.append(s6)

    if not final_clips:
        return None

    print(f"🔄 {len(final_clips)}개의 씬 병합 중...")
    final_video = concatenate_videoclips(final_clips)
    output_filename = "daily_briefing_v2.mp4"
    final_video.write_videofile(output_filename, fps=24, codec='libx264', audio_codec='aac', threads=4, logger=None)
    
    print(f"✅ 영상 제작 완료: {output_filename}")
    return output_filename