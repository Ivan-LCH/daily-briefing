# 가볍고 안정적인 Python 3.11 Slim 버전 사용
FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 패키지 업데이트 및 필요한 도구 설치
# - curl: 디버깅용
# - ffmpeg: 영상 편집 엔진
# - imagemagick: 이미지/자막 처리
# - fonts-noto-cjk: 한글 폰트
# - findutils: find 명령어 사용을 위해 명시적 확인 (보통 기본 포함됨)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    imagemagick \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# [핵심 수정] ImageMagick 보안 정책 수정
# 버전(6 또는 7)에 상관없이 policy.xml 위치를 찾아 수정하도록 변경
RUN find /etc -name "policy.xml" -exec sed -i 's/none/read,write/g' {} +

# 시간대 설정 (KST)
ENV TZ=Asia/Seoul
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 의존성 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 현재 폴더의 모든 파일을 컨테이너로 복사
COPY . .

# 컨테이너 실행
CMD ["python", "-u", "agent.py"]