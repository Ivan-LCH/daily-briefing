# [Dockerfile]

FROM python:3.11-slim

WORKDIR /app

# 1. 패키지 설치
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

# 2. [핵심] policy.xml 위치를 찾아내서 'read|write' 권한으로 덮어쓰기
# 경로가 /etc/ImageMagick-6/ 이든 /etc/ImageMagick/ 이든 상관없이 작동합니다.
RUN find /etc -name "policy.xml" -exec sh -c 'echo "<policymap>\n\
  <policy domain=\"resource\" name=\"memory\" value=\"256MiB\"/>\n\
  <policy domain=\"resource\" name=\"map\" value=\"512MiB\"/>\n\
  <policy domain=\"resource\" name=\"width\" value=\"16KP\"/>\n\
  <policy domain=\"resource\" name=\"height\" value=\"16KP\"/>\n\
  <policy domain=\"resource\" name=\"area\" value=\"128MB\"/>\n\
  <policy domain=\"resource\" name=\"disk\" value=\"1GiB\"/>\n\
  <policy domain=\"delegate\" rights=\"none\" pattern=\"URL\" />\n\
  <policy domain=\"delegate\" rights=\"none\" pattern=\"HTTPS\" />\n\
  <policy domain=\"delegate\" rights=\"none\" pattern=\"HTTP\" />\n\
  <policy domain=\"path\" rights=\"read|write\" pattern=\"@*\" />\n\
</policymap>" > {}' \;

# 3. 파이썬 라이브러리 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. 소스 복사
COPY . .

CMD ["python", "-u", "agent.py"]