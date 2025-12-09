import os
import re
import tempfile
import time
from typing import Optional

import yt_dlp

from backend.models import (
    VideoMetadata,
    TranscriptSegment,
    ScraperResult,
)


def is_cloud_environment() -> bool:
    """Check if running in a cloud/serverless environment (e.g., Vercel)."""
    return any([
        os.environ.get("VERCEL"),
        os.environ.get("AWS_LAMBDA_FUNCTION_NAME"),
        os.environ.get("GOOGLE_CLOUD_PROJECT"),
    ])


def extract_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from URL."""
    patterns = [
        r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'(?:embed/)([a-zA-Z0-9_-]{11})',
        r'(?:shorts/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def download_audio(video_url: str, output_dir: str) -> tuple[str, dict]:
    """
    Download audio from YouTube video using yt-dlp.
    Returns tuple of (audio_file_path, video_info).
    """
    output_template = os.path.join(output_dir, "audio.%(ext)s")

    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)

    audio_path = os.path.join(output_dir, "audio.mp3")
    return audio_path, info


def transcribe_audio(audio_path: str, model_size: str = "base") -> dict:
    """
    Transcribe audio file using OpenAI Whisper.

    Args:
        audio_path: Path to audio file
        model_size: Whisper model size (tiny, base, small, medium, large)

    Returns:
        Dictionary with transcription results
    """
    import whisper

    model = whisper.load_model(model_size)
    result = model.transcribe(audio_path)

    return result


class AITranscriber:
    """Transcribe YouTube videos using OpenAI Whisper (local only)."""

    def __init__(self, model_size: str = "base"):
        """
        Initialize AI transcriber.

        Args:
            model_size: Whisper model size. Options:
                - tiny: ~1GB VRAM, fastest, lower accuracy
                - base: ~1GB VRAM, good balance (default)
                - small: ~2GB VRAM, better accuracy
                - medium: ~5GB VRAM, high accuracy
                - large: ~10GB VRAM, best accuracy
        """
        self.model_size = model_size
        self._model = None

    def is_available(self) -> bool:
        """Check if AI transcription is available in current environment."""
        if is_cloud_environment():
            return False

        try:
            import whisper
            return True
        except ImportError:
            return False

    def _get_model(self):
        """Lazy load Whisper model."""
        if self._model is None:
            import whisper
            self._model = whisper.load_model(self.model_size)
        return self._model

    def scrape(self, url: str) -> ScraperResult:
        """
        Transcribe YouTube video using AI.

        Args:
            url: YouTube video URL

        Returns:
            ScraperResult with transcript data
        """
        start_time = time.time()

        if not self.is_available():
            return ScraperResult(
                success=False,
                method="ai-whisper",
                error="AI transcription is not available in cloud environments",
                execution_time_ms=round((time.time() - start_time) * 1000, 2)
            )

        try:
            video_id = extract_video_id(url)
            if not video_id:
                return ScraperResult(
                    success=False,
                    method="ai-whisper",
                    error="Could not extract video ID from URL",
                    execution_time_ms=round((time.time() - start_time) * 1000, 2)
                )

            with tempfile.TemporaryDirectory() as temp_dir:
                audio_path, video_info = download_audio(url, temp_dir)

                model = self._get_model()
                result = model.transcribe(audio_path)

                segments = []
                for seg in result.get("segments", []):
                    segments.append(TranscriptSegment(
                        text=seg["text"].strip(),
                        start=seg["start"],
                        duration=seg["end"] - seg["start"]
                    ))

                full_text = result.get("text", "").strip()
                word_count = len(full_text.split())
                detected_language = result.get("language", "unknown")

                metadata = VideoMetadata(
                    video_id=video_id,
                    title=video_info.get("title", ""),
                    description=video_info.get("description"),
                    transcript=segments,
                    available_languages=[detected_language],
                    webpage_url=f"https://www.youtube.com/watch?v={video_id}",
                    scraper_method="ai-whisper",
                    raw_data={
                        "transcript_language": detected_language,
                        "is_auto_generated": False,
                        "is_ai_transcribed": True,
                        "whisper_model": self.model_size,
                        "word_count": word_count,
                        "segment_count": len(segments),
                        "full_transcript_text": full_text,
                    }
                )

                execution_time = (time.time() - start_time) * 1000

                return ScraperResult(
                    success=True,
                    method="ai-whisper",
                    data=metadata,
                    execution_time_ms=round(execution_time, 2),
                    fields_extracted=len(segments) + 2
                )

        except Exception as e:
            return ScraperResult(
                success=False,
                method="ai-whisper",
                error=f"AI transcription failed: {str(e)}",
                execution_time_ms=round((time.time() - start_time) * 1000, 2)
            )

    def get_transcript_text(self, url: str, include_timestamps: bool = False) -> dict:
        """
        Get transcript as plain text.

        Args:
            url: YouTube video URL
            include_timestamps: Whether to include timestamps

        Returns:
            Dictionary with transcript text and metadata
        """
        result = self.scrape(url)

        if not result.success or not result.data:
            return {
                "success": False,
                "error": result.error,
                "text": None,
                "is_ai_transcribed": True
            }

        if include_timestamps:
            lines = []
            for seg in result.data.transcript:
                minutes = int(seg.start // 60)
                seconds = int(seg.start % 60)
                lines.append(f"[{minutes:02d}:{seconds:02d}] {seg.text}")
            text = '\n'.join(lines)
        else:
            text = ' '.join(seg.text for seg in result.data.transcript)

        return {
            "success": True,
            "text": text,
            "language": result.data.raw_data.get("transcript_language"),
            "is_ai_transcribed": True,
            "whisper_model": self.model_size,
            "word_count": result.data.raw_data.get("word_count")
        }
