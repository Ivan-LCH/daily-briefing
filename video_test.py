import asyncio
import edge_tts
from moviepy.editor import *
from moviepy.config import change_settings

# ImageMagick 경로 설정 (Docker 환경)
change_settings({"IMAGEMAGICK_BINARY": "/usr/bin/convert"})

async def create_voice():
    print("1. 음성 생성 중...")
    text = "안녕하세요. 이것은 비디오 생성 테스트입니다. 한글 자막과 음성이 잘 나오는지 확인하고 있습니다."
    # ko-KR-SunHiNeural: 여성 아나운서 톤
    communicate = edge_tts.Communicate(text, "ko-KR-SunHiNeural")
    await communicate.save("test_audio.mp3")
    print("✅ 음성 파일 생성 완료: test_audio.mp3")

def create_video():
    print("2. 영상 합성 중...")
    
    # 1. 오디오 불러오기
    audio_clip = AudioFileClip("test_audio.mp3")
    
    # 2. 배경 생성 (검은색, 9:16 비율 쇼츠 사이즈 720x1280)
    # 길이는 오디오 길이 + 1초
    bg_clip = ColorClip(size=(720, 1280), color=(0, 0, 0), duration=audio_clip.duration + 1)
    
    # 3. 텍스트(자막) 생성
    # 폰트는 Dockerfile에서 설치한 Noto Sans CJK KR 사용
    try:
        txt_clip = TextClip(
            "영상 제작 테스트\n한글 자막 확인", 
            fontsize=70, 
            color='white', 
            font="Noto-Sans-CJK-KR", # 설치된 폰트 이름
            method='caption', # 줄바꿈 자동 처리
            size=(600, None)
        ).set_position('center').set_duration(audio_clip.duration + 1)
    except Exception as e:
        print(f"❌ 폰트 에러 발생: {e}")
        print("기본 폰트로 재시도합니다.")
        txt_clip = TextClip(
            "Font Error", 
            fontsize=70, 
            color='white'
        ).set_position('center').set_duration(audio_clip.duration + 1)

    # 4. 합성 (배경 + 자막 + 오디오)
    final_clip = CompositeVideoClip([bg_clip, txt_clip])
    final_clip = final_clip.set_audio(audio_clip)
    
    # 5. 내보내기 (렌더링)
    output_filename = "test_output.mp4"
    final_clip.write_videofile(
        output_filename, 
        fps=24, 
        codec='libx264', 
        audio_codec='aac',
        threads=4
    )
    print(f"✅ 영상 생성 완료: {output_filename}")

if __name__ == "__main__":
    # 비동기 함수(TTS) 실행
    loop = asyncio.get_event_loop_policy().get_event_loop()
    loop.run_until_complete(create_voice())
    
    # 영상 합성 실행
    create_video()