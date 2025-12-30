# 베이스 이미지 (Python 3.11)
FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 1. 필수 시스템 패키지 설치
# findutils: find 명령어 사용을 위해 필요
# imagemagick, ffmpeg: 영상 처리를 위해 필수
# fonts-noto-cjk: 한글 폰트 지원
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

# 2. [핵심] ImageMagick 보안 정책 완화 (MoviePy 텍스트 에러 해결)
# MoviePy는 텍스트를 임시 파일(@)로 저장해서 읽는데, 최신 ImageMagick은 이를 차단함.
# 이를 허용(read|write)하도록 policy.xml을 찾아서 수정합니다.
RUN find /etc -name "policy.xml" -exec sed -i 's/rights="none" pattern="@\*"/rights="read|write" pattern="@*"/g' {} + && \
    find /etc -name "policy.xml" -exec sed -i 's/rights="none" pattern="PDF"/rights="read|write" pattern="PDF"/g' {} +

# 3. Python 라이브러리 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. 소스 코드 복사
COPY . .

# 5. 실행 명령어
# -u 옵션: 로그를 버퍼링 없이 즉시 출력 (실시간 확인 용이)
CMD ["python", "-u", "agent.py"]