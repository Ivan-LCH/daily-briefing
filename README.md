# 📈 AI Daily Financial Briefing Bot (Auto-Video Generator)

**"매일 아침, AI가 만드는 고품질 주식 시황 브리핑 쇼츠"**

이 프로젝트는 Python과 Google Gemini(AI)를 활용하여 매일 아침 글로벌 증시, 뉴스, 유튜브 트렌드를 분석하고, 이를 **1분짜리 쇼츠(Shorts) 영상으로 자동 제작하여 유튜브에 업로드**하는 완전 자동화 에이전트입니다.

## ✨ Key Features (핵심 기능)

* **🧠 AI 기반 콘텐츠 생성:** Google Gemini 1.5 Flash 모델이 수집된 데이터를 분석하여 방송용 대본과 핵심 요약을 작성합니다.
* **🎥 고품질 영상 자동 편집:** `MoviePy`를 활용하여 6단계 구성의 영상을 렌더링합니다.
    * **Scene 1 (Market Map):** Finviz S&P 500 맵 실시간 캡처 및 크롭.
    * **Scene 2 (Global News):** 주요 거시 경제 뉴스 헤드라인 요약.
    * **Scene 3 (Watchlist):** 주요 종목(TSLA, NVDA 등)의 등락을 **표(Table)** 형태로 시각화.
    * **Scene 4 (Technical Analysis):** 당일 분봉(Intraday) 차트 생성 및 기술적 분석 (상승/하락 색상 자동화).
    * **Scene 5 (YouTube Insight):** 주요 경제 유튜버들의 최신 영상 요약.
    * **Scene 6 (Outro):** 참고 데이터 및 채널 출처 명시.
* **🗣️ AI 보이스 오버:** `Edge-TTS`를 사용하여 자연스러운 한국어 내레이션을 생성합니다.
* **🛡️ 강력한 오류 방지 (Safe Text):** 이모지나 특수문자로 인한 폰트 렌더링 오류를 방지하는 `Sanitize` 로직이 적용되었습니다.
* **🤖 완전 자동화 (Docker):** 데이터 수집 -> 영상 제작 -> 유튜브 업로드 -> 이메일/슬랙 리포트 발송까지 Docker 컨테이너 하나로 해결됩니다.

---

## 🛠️ Tech Stack

* **Language:** Python 3.11
* **AI Model:** Google Gemini Pro / 1.5 Flash (`google-generativeai`)
* **Video Processing:** MoviePy, ImageMagick
* **Data Collection:**
    * `yfinance` (주식 데이터)
    * `Selenium` + `Chrome Driver` (웹 캡처)
    * `Feedparser`, `Trafilatura` (뉴스 크롤링)
    * `YouTube Data API` (유튜브 트렌드)
* **Deployment:** Docker, Docker Compose

---

## 🚀 Installation & Setup

### 1. Prerequisites
* Docker & Docker Compose
* Google Gemini API Key
* YouTube Data API Key & OAuth 2.0 Client ID (`client_secret.json`)
* Gmail App Password (메일 발송용)

### 2. Clone Repository
git clone https://github.com/your-username/daily-briefing-bot.git
cd daily-briefing-bot

### 3. Environment Configuration (.env)
프로젝트 루트에 `.env` 파일을 생성하고 아래 정보를 입력하세요.

GOOGLE_API_KEY=your_gemini_api_key
YOUTUBE_API_KEY=your_youtube_api_key
EMAIL_SENDER=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
SLACK_WEBHOOK_URL=your_slack_webhook_url

### 4. Application Configuration (config.json)
`config.json` 파일에 수집하고 싶은 주식과 뉴스 키워드를 설정합니다.

{
  "stock_tickers": ["TSLA", "PLTR", "GOOGL", "NVDA", "GLD"],
  "news_keywords": ["Global Economy", "US Stock Market", "Fed Interest Rate", "AI Technology"],
  "youtube_channels": {
    "슈카월드": "UCsJ6RuBiTVWRX156FVbeaGg",
    "삼프로TV": "UChxv... (Channel ID)"
  },
  "youtube_keywords": ["트렌드", "AI 기술"],
  "email_recipients": ["user1@example.com"]
}

---

## ▶️ Usage (Run with Docker)

이 프로젝트는 Docker 환경에서 실행하는 것을 권장합니다. (한글 폰트 및 ImageMagick 설정이 포함되어 있음)

# 1. 이미지 빌드 및 백그라운드 실행
docker-compose up --build -d

# 2. 로그 확인 (실시간 진행 상황)
docker-compose logs -f daily_briefing_bot

# 3. 컨테이너 중지
docker-compose down

---

## 📂 Project Structure

.
├── agent.py             # [Main] 데이터 수집, AI 분석, 전체 워크플로우 제어
├── video_studio.py      # [Video] MoviePy 기반 영상 씬(Scene) 제작 및 렌더링
├── youtube_manager.py   # [Upload] 유튜브 업로드 로직
├── config.json          # 사용자 설정 (종목, 키워드 등)
├── requirements.txt     # 파이썬 의존성 패키지
├── Dockerfile           # 도커 이미지 빌드 설정 (폰트, ImageMagick 설치)
└── docker-compose.yml   # 도커 컨테이너 설정

---

## ⚠️ Trouble Shooting

* **폰트 깨짐 현상:** Dockerfile에 포함된 `Noto Sans CJK` 폰트 설치 구문을 확인하세요.
* **ImageMagick 에러:** `video_studio.py` 내의 `SAFE_FONT` 경로 설정과 `sanitize_text` 함수가 특수문자를 올바르게 처리하는지 확인하세요.
* **Finviz 캡처 실패:** Selenium이 Headless 모드에서 실행될 때 창 크기(`window-size`) 설정이 되어 있는지 확인하세요.

---

## 📝 Author

[Ivan-LCH](https://github.com/Ivan-LCH)

Last Updated: 2025-12-26