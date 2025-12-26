# 베이스 이미지 (Python 3.11)
FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 1. 필수 시스템 패키지 설치
# [수정] findutils 추가 (find 명령어를 확실하게 쓰기 위해)
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    imagemagick \
    ffmpeg \
    fonts-noto-cjk \
    curl \
    unzip \
    libnss3 \
    findutils \
    && rm -rf /var/lib/apt/lists/*

# 2. Python 라이브러리 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Selenium 및 추가 라이브러리 직접 설치
RUN pip install selenium webdriver-manager pillow numpy requests

# 4. [수정] ImageMagick 정책 수정 (경로 자동 탐색)
# "policy.xml"이라는 파일을 /etc 폴더 안에서 찾아서 모두 수정해라
RUN find /etc -name "policy.xml" -exec sed -i 's/none/read,write/g' {} +

# 5. 소스 코드 복사
COPY . .

# 6. 실행 명령어 (기본값)
CMD ["python", "agent.py"]