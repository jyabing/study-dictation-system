import hashlib
import os
from pathlib import Path
from django.conf import settings
from gtts import gTTS


def generate_tts(text, lang="en"):
    """
    生成 TTS 并返回 audio_url
    """

    # 统一 hash
    hash_id = hashlib.md5(f"{lang}:{text}".encode()).hexdigest()

    filename = f"tts_{hash_id}.mp3"

    audio_dir = Path(settings.MEDIA_ROOT) / "tts"
    audio_dir.mkdir(parents=True, exist_ok=True)

    filepath = audio_dir / filename

    # 如果文件已经存在，就不再生成
    if not filepath.exists():
        tts = gTTS(text=text, lang=lang)
        tts.save(filepath)

    audio_url = f"{settings.MEDIA_URL}tts/{filename}"

    return audio_url