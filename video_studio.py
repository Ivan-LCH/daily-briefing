# ===================================================================================================================
# Import
# ===================================================================================================================
import os
import asyncio
import edge_tts
import yfinance as yf
import requests
import re
import matplotlib
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from moviepy.editor import *
from moviepy.config import change_settings
import PIL.Image
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

change_settings({"IMAGEMAGICK_BINARY": "/usr/bin/convert"})

# ... (기존 헬퍼 함수들: _generate_voice, create_voice_file, create_chart_image 등은 동일하므로 생략하지 않고 포함) ...

# ===================================================================================================================
# generate voice
# ===================================================================================================================

async def _generate_voice(text, filename):
    clean_text = re.sub(r'\([^)]*\)', '', text)
    communicate = edge_tts.Communicate(clean_text, "ko-KR-SunHiNeural")
    await communicate.save(filename)



# ===================================================================================================================
# create voice file
# ===================================================================================================================

def create_voice_file(text, filename="voice.mp3"):
    try:
        loop = asyncio.get_event_loop_policy().get_event_loop()
        loop.run_until_complete(_generate_voice(text, filename))
        return filename
    except: return None


# ===================================================================================================================
# create chart image
# ===================================================================================================================

# ===================================================================================================================
# Create Chart Image (Intraday Pro Style) - [Fix: 실제 데이터 날짜 표시]
# ===================================================================================================================

def create_chart_image(symbol):
    try:
        print(f"📊 [{symbol}] 전문가 스타일 차트 생성 중...")
        ticker = yf.Ticker(symbol)
        
        # 1순위: 1일치 5분봉
        hist = ticker.history(
            period   = "1d", 
            interval = "5m"
        )
        is_intraday = True
        
        # 데이터 없음 -> 2순위: 5일치 1시간봉
        if hist.empty:
            print("   (오늘 데이터 없음 -> 5일치로 대체)")
            hist = ticker.history(
                period   = "5d", 
                interval = "1h"
            )
            is_intraday = False
        
        if hist.empty: return None, None

        # --- 가격 정보 추출 ---
        # [Fix] 오늘 날짜 대신, 데이터의 실제 날짜(인덱스)를 사용
        last_dt = hist.index[-1]
        
        # 시간대 조정 (UTC -> 한국 시간 근사치 혹은 현지 날짜 유지)
        # yfinance 데이터는 보통 현지 시간대(미국 ET) 기준이거나 UTC임.
        # 단순히 날짜만 보여줄 거면 strftime으로 포맷팅
        real_date_str = last_dt.strftime("%Y.%m.%d")
        
        last_price = hist['Close'].iloc[-1]
        
        try:
            prev_close = ticker.info.get('previousClose', hist['Close'].iloc[0])
        except:
            prev_close = hist['Close'].iloc[0] # 실패시 차트 시작점 기준

        diff = last_price - prev_close
        pct  = (diff / prev_close) * 100
        sign = "+" if diff > 0 else "" 
        color_trend = '#00ff00' if diff > 0 else '#ff0000'

        # [Fix] price_info에 실제 데이터 날짜 적용
        price_info = {
            'date'   : real_date_str, # 예: 2024.12.20
            'price'  : f"${last_price:.2f}",
            'change' : f"({sign}${diff:.2f}, {sign}{pct:.2f}%)",
            'color'  : color_trend
        }

        # [디자인] 차트 그리기
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 8))
        ax.set_facecolor('#121212') 
        fig.patch.set_facecolor('#000000')

        # 1. 메인 라인
        ax.plot(
            hist.index, 
            hist['Close'], 
            color=color_trend, 
            linewidth=2, 
            label='Price'
        )
        
        # 2. 영역 채우기
        ax.fill_between(
            hist.index, 
            hist['Close'], 
            hist['Close'].min(), 
            color=color_trend, 
            alpha=0.15
        )

        # 3. 이동평균선
        window = 10 if is_intraday else 5
        ma = hist['Close'].rolling(window=window).mean()
        ax.plot(
            hist.index, 
            ma, 
            color='white', 
            linewidth=1, 
            linestyle='--', 
            alpha=0.6, 
            label='MA'
        )

        # 4. 최고가 마킹
        max_price = hist['Close'].max()
        ax.axhline(
            y=max_price, 
            color='gray', 
            linestyle=':', 
            linewidth=0.5, 
            alpha=0.5
        )

        # 5. 축 설정
        ax.spines['top'   ].set_visible(False)
        ax.spines['right' ].set_visible(False)
        ax.spines['left'  ].set_visible(False)
        ax.spines['bottom'].set_color('white')
        
        # X축 포맷
        if is_intraday:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        else:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
            
        ax.tick_params(
            axis='x', 
            colors='gray', 
            labelsize=9
        )
        ax.tick_params(
            axis='y', 
            colors='gray', 
            labelsize=9
        )
        ax.grid(
            True, 
            which='major', 
            color='gray', 
            linestyle=':', 
            linewidth=0.3, 
            alpha=0.3
        )

        output_file = f"{symbol}_chart.png"
        plt.savefig(
            output_file, 
            bbox_inches='tight', 
            facecolor='black', 
            dpi=100
        )
        plt.close()

        return output_file, price_info

    except Exception as e:
        print(f"❌ 차트 생성 실패: {e}")
        return None, None



# ===================================================================================================================
# [NEW] Intro Video Generator (Bloomberg Style Dashboard) - [Fix: bold 옵션 완전 제거]
# ===================================================================================================================

def make_intro_clip(stock_list, news_list, youtube_list, trend_list):
    print("🎬 인트로 영상 제작 중 (대시보드 스타일)...")
    
    # 오디오
    intro_script = "안녕하세요! 한량을 꿈꾸는 이반입니다. 오늘의 핵심 브리핑입니다. 잠시 화면을 멈추고 확인해 보세요."
    intro_audio  = create_voice_file(intro_script, "intro_voice.mp3")
    if not intro_audio: return None
    
    audio_clip   = AudioFileClip(intro_audio)
    duration     = max(audio_clip.duration + 4, 8) 
    
    # 배경
    bg_clip = ColorClip(
        size        = (1280, 720), 
        color       = (15, 20, 35), 
        duration    = duration
    )
    clips = [bg_clip]
    
    # 타이틀
    clips.append(TextClip(
        "TODAY'S BRIEFING", 
        fontsize    = 50, 
        color       = 'white', 
        font        = "Noto-Sans-CJK-KR", 
        align       = 'West'
    ).set_position(('center', 30)).set_duration(duration))
    
    # -----------------------------------------------------------
    # [좌측] Global Market (3x2 Grid) + Deep Dive
    # -----------------------------------------------------------
    left_x = 50
    left_y = 120
    
    # (1) Global Market Insight Header
    clips.append(TextClip(
        "📈 Global Market Insight", 
        fontsize    = 30, 
        color       = '#ffd700', 
        font        = "Noto-Sans-CJK-KR", 
        align       = 'West'
    ).set_position((left_x, left_y)).set_duration(duration))
    left_y += 50
    
    # (2) Stock Grid (3 Columns x 2 Rows)
    grid_cols = 3
    cell_w = 190 # 셀 너비
    cell_h = 100 # 셀 높이
    
    for i, stock in enumerate(stock_list[:6]): # 최대 6개
        row = i // grid_cols
        col = i % grid_cols
        
        cur_x = left_x + (col * cell_w)
        cur_y = left_y + (row * cell_h)
        
        # Symbol (Big) - [Fix] bold=True 삭제
        clips.append(TextClip(
            stock['symbol'], 
            fontsize    = 32, 
            color       = 'white', 
            font        = "Noto-Sans-CJK-KR", 
            align       = 'West'
        ).set_position((cur_x, cur_y)).set_duration(duration))
        
        # Price (Medium)
        clips.append(TextClip(
            stock['price'], 
            fontsize    = 24, 
            color       = '#dddddd', 
            font        = "Noto-Sans-CJK-KR", 
            align       = 'West'
        ).set_position((cur_x, cur_y + 40)).set_duration(duration))
        
        # Change (Small, Colored)
        is_plus   = '+' in stock['change_str']
        chg_color = '#00ff00' if is_plus else '#ff4444'
        clips.append(TextClip(
            stock['change_str'], 
            fontsize    = 20, 
            color       = chg_color, 
            font        = "Noto-Sans-CJK-KR", 
            align       = 'West'
        ).set_position((cur_x, cur_y + 70)).set_duration(duration))

    left_y += (2 * cell_h) + 30 
    
    # (3) Deep Dive (News)
    clips.append(TextClip(
        "📰 Deep Dive (주요 뉴스)", 
        fontsize    = 30, 
        color       = '#ffd700', 
        font        = "Noto-Sans-CJK-KR", 
        align       = 'West'
    ).set_position((left_x, left_y)).set_duration(duration))
    left_y += 50
    
    for news in news_list[:3]: 
        txt = f"• {news['title']}"
        clips.append(TextClip(
            txt, 
            fontsize    = 22, 
            color       = '#eeeeee', 
            font        = "Noto-Sans-CJK-KR", 
            method      = 'caption', 
            size        = (550, None), 
            align       = 'West'
        ).set_position((left_x, left_y)).set_duration(duration))
        left_y += 55 

    # -----------------------------------------------------------
    # [우측] YouTube + Trending
    # -----------------------------------------------------------
    right_x = 660
    right_y = 120
    col_w_right = 570
    
    # (4) YouTube Insights
    clips.append(TextClip(
        "📺 YouTube Insights", 
        fontsize    = 30, 
        color       = '#ffd700', 
        font        = "Noto-Sans-CJK-KR", 
        align       = 'West'
    ).set_position((right_x, right_y)).set_duration(duration))
    right_y += 50
    
    for video in youtube_list[:3]: 
        txt = f"[{video['source']}] {video['title']}"
        clips.append(TextClip(
            txt, 
            fontsize    = 22, 
            color       = '#eeeeee', 
            font        = "Noto-Sans-CJK-KR", 
            method      = 'caption', 
            size        = (col_w_right, None), 
            align       = 'West'
        ).set_position((right_x, right_y)).set_duration(duration))
        right_y += 65 

    right_y += 20 

    # (5) Trending Now
    clips.append(TextClip(
        "🔥 Trending Now (핫이슈)", 
        fontsize    = 30, 
        color       = '#ffd700', 
        font        = "Noto-Sans-CJK-KR", 
        align       = 'West'
    ).set_position((right_x, right_y)).set_duration(duration))
    right_y += 50
    
    for trend in trend_list[:2]: 
        ch_name = trend.get('channel_name', 'YouTube')
        txt = f"[{ch_name}] {trend['title']}"
        clips.append(TextClip(
            txt, 
            fontsize    = 22, 
            color       = '#eeeeee', 
            font        = "Noto-Sans-CJK-KR", 
            method      = 'caption', 
            size        = (col_w_right, None), 
            align       = 'West'
        ).set_position((right_x, right_y)).set_duration(duration))
        right_y += 65

    # 하단 안내
    clips.append(TextClip(
        "※ 상세 내용은 하단 [더보기] 설명란을 참고하세요.", 
        fontsize    = 20, 
        color       = '#aaaaaa', 
        font        = "Noto-Sans-CJK-KR"
    ).set_position(('center', 670)).set_duration(duration))

    return CompositeVideoClip(clips).set_audio(audio_clip)



# ===================================================================================================================
# Main Video Logic (Updated Signature)
# ===================================================================================================================

# ===================================================================================================================
# Main Video Logic (Simpler Logo Logic)
# ===================================================================================================================

def make_video(topic_data, script_text, stock_list=[], news_list=[], youtube_list=[], trend_list=[]):
    symbol = topic_data.get('symbol', 'STOCK')
    
    # 1. 인트로
    intro_clip            = make_intro_clip(stock_list, news_list, youtube_list, trend_list)
    
    # 2. 본문
    chart_img, price_info = create_chart_image(symbol)
    body_audio            = create_voice_file(script_text, "body_voice.mp3")
    
    if not body_audio: return None
    body_audio_clip       = AudioFileClip(body_audio)
    duration              = body_audio_clip.duration + 1
    canvas                = ColorClip(
        size        = (1280, 720), 
        color       = (0,0,0), 
        duration    = duration
    )
    clips_body            = [canvas]

    # 우측 차트
    if chart_img and os.path.exists(chart_img):
        chart_clip          = ImageClip(chart_img).set_duration(duration).resize(height=600).set_position((450, 'center'))
        clips_body.append(chart_clip)

    # 좌측 패널 정보
    left_margin = 50
    current_y   = 100 
    if price_info:
        # 날짜
        clips_body.append(TextClip(
            price_info['date'], 
            fontsize    = 30, 
            color       = '#aaaaaa', 
            font        = "Noto-Sans-CJK-KR", 
            align       = 'West'
        ).set_position((left_margin, current_y)).set_duration(duration))
        current_y += 50
        # 가격
        clips_body.append(TextClip(
            price_info['price'], 
            fontsize    = 60, 
            color       = 'white', 
            font        = "Noto-Sans-CJK-KR", 
            align       = 'West', 
            method      = 'label'
        ).set_position((left_margin, current_y)).set_duration(duration))
        current_y += 80
        # 등락폭
        clips_body.append(TextClip(
            price_info['change'], 
            fontsize    = 30, 
            color       = price_info['color'], 
            font        = "Noto-Sans-CJK-KR", 
            align       = 'West'
        ).set_position((left_margin, current_y)).set_duration(duration))
        current_y += 80

    # -----------------------------------------------------------------------
    # [Fix] 로고 이미지 로직 제거 -> 무조건 텍스트 티커 표시
    # -----------------------------------------------------------------------
    # 티커 (Symbol) 크게 표시
    logo_clip = TextClip(
        symbol, 
        fontsize    = 100,          # 폰트 크기 키움
        color       = 'white', 
        font        = "Noto-Sans-CJK-KR", 
        align       = 'West', 
        stroke_color= 'gray',       # 테두리 추가로 가독성 확보
        stroke_width  = 2
    ).set_position((left_margin, current_y)).set_duration(duration)
    
    clips_body.append(logo_clip)
    current_y += 150 # 다음 요소(헤드라인)와의 간격

    # 헤드라인
    clips_body.append(TextClip(
        topic_data.get('title', ''), 
        fontsize    = 40, 
        color       = 'white', 
        font        = "Noto-Sans-CJK-KR", 
        method      = 'caption', 
        size        = (400, None), 
        align       = 'West'
    ).set_position((left_margin, current_y)).set_duration(duration))
    
    # 출처
    clips_body.append(TextClip(
        "Powered by Ivan AI", 
        fontsize    = 15, 
        color       = '#555555', 
        font        = "Noto-Sans-CJK-KR"
    ).set_position((left_margin, 650)).set_duration(duration))

    final_body = CompositeVideoClip(clips_body).set_audio(body_audio_clip)
    

    print("🔄 인트로와 본문 병합 중...")
    if intro_clip:
        final_video = concatenate_videoclips([intro_clip, final_body])
    else:
        final_video = final_body

    output_filename = "daily_briefing_full.mp4"
    final_video.write_videofile(
        output_filename, 
        fps=24, 
        codec='libx264', 
        audio_codec='aac', 
        threads=4, 
        logger=None
    )
    
    return output_filename