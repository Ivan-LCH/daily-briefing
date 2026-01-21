import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

# 필요한 권한 설정
SCOPES = ['https://www.googleapis.com/auth/youtube.upload', 'https://www.googleapis.com/auth/youtube.force-ssl']

def main():
    if not os.path.exists('client_secret.json'):
        print("❌ 에러: client_secrets.json 파일이 없습니다. 파일을 확인해주세요.")
        return

    print("🚀 수동 인증을 시작합니다...")
    
    # 콘솔 모드(복사-붙여넣기 방식)로 인증 설정
    flow = InstalledAppFlow.from_client_secrets_file(
        'client_secret.json', SCOPES
    )
    
    # 1. URL 출력 및 코드 입력 대기
    # run_console()은 URL을 출력하고 사용자가 입력한 코드를 기다립니다.
    creds = flow.run_console()

    # 2. 토큰 파일 저장
    with open('token.json', 'w') as token:
        token.write(creds.to_json())
    
    print("\n✅ 인증 성공! 'token.json' 파일이 생성되었습니다.")
    print("이제 'docker-compose up'을 실행하면 봇이 정상 작동할 것입니다.")

if __name__ == '__main__':
    main()