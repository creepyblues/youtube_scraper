import re
import time
from typing import Optional

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

from backend.models import (
    VideoMetadata,
    TranscriptSegment,
    ScraperResult,
)


def extract_video_id(url: str) -> Optional[str]:
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


class TranscriptScraper:
    def __init__(self, preferred_languages: list[str] = None):
        self.preferred_languages = preferred_languages or ['en', 'en-US', 'en-GB']
        self._api = YouTubeTranscriptApi()

    def scrape(self, url: str) -> ScraperResult:
        start_time = time.time()

        try:
            video_id = extract_video_id(url)
            if not video_id:
                return ScraperResult(
                    success=False,
                    method="youtube-transcript-api",
                    error="Could not extract video ID from URL"
                )

            transcript_list = self._api.list(video_id)

            available_languages = []
            manual_languages = []
            auto_languages = []

            for transcript in transcript_list:
                lang_code = transcript.language_code
                available_languages.append(lang_code)
                if transcript.is_generated:
                    auto_languages.append(lang_code)
                else:
                    manual_languages.append(lang_code)

            transcript_data = None
            used_language = None
            is_auto_generated = False

            for lang in self.preferred_languages:
                try:
                    transcript_obj = transcript_list.find_transcript([lang])
                    transcript_data = transcript_obj.fetch()
                    used_language = transcript_obj.language_code
                    is_auto_generated = transcript_obj.is_generated
                    break
                except NoTranscriptFound:
                    continue

            if not transcript_data:
                try:
                    transcript_obj = transcript_list.find_manually_created_transcript(self.preferred_languages)
                    transcript_data = transcript_obj.fetch()
                    used_language = transcript_obj.language_code
                    is_auto_generated = False
                except NoTranscriptFound:
                    pass

            if not transcript_data:
                try:
                    transcript_obj = transcript_list.find_generated_transcript(self.preferred_languages)
                    transcript_data = transcript_obj.fetch()
                    used_language = transcript_obj.language_code
                    is_auto_generated = True
                except NoTranscriptFound:
                    pass

            if not transcript_data and available_languages:
                first_transcript = list(transcript_list)[0]
                transcript_data = first_transcript.fetch()
                used_language = first_transcript.language_code
                is_auto_generated = first_transcript.is_generated

            if not transcript_data:
                return ScraperResult(
                    success=False,
                    method="youtube-transcript-api",
                    error="No transcripts available for this video",
                    execution_time_ms=round((time.time() - start_time) * 1000, 2)
                )

            segments = []
            for item in transcript_data:
                segments.append(TranscriptSegment(
                    text=item.text,
                    start=item.start,
                    duration=item.duration
                ))

            full_text = ' '.join(seg.text for seg in segments)
            word_count = len(full_text.split())

            metadata = VideoMetadata(
                video_id=video_id,
                title="",
                description=None,
                transcript=segments,
                available_languages=available_languages,
                webpage_url=f"https://www.youtube.com/watch?v={video_id}",
                scraper_method="youtube-transcript-api",
                raw_data={
                    "transcript_language": used_language,
                    "is_auto_generated": is_auto_generated,
                    "manual_languages": manual_languages,
                    "auto_languages": auto_languages,
                    "word_count": word_count,
                    "segment_count": len(segments),
                    "full_transcript_text": full_text
                }
            )

            execution_time = (time.time() - start_time) * 1000

            return ScraperResult(
                success=True,
                method="youtube-transcript-api",
                data=metadata,
                execution_time_ms=round(execution_time, 2),
                fields_extracted=len(segments) + len(available_languages) + 2
            )

        except TranscriptsDisabled:
            return ScraperResult(
                success=False,
                method="youtube-transcript-api",
                error="Transcripts are disabled for this video",
                execution_time_ms=round((time.time() - start_time) * 1000, 2)
            )
        except VideoUnavailable:
            return ScraperResult(
                success=False,
                method="youtube-transcript-api",
                error="Video is unavailable",
                execution_time_ms=round((time.time() - start_time) * 1000, 2)
            )
        except Exception as e:
            return ScraperResult(
                success=False,
                method="youtube-transcript-api",
                error=f"Unexpected error: {str(e)}",
                execution_time_ms=round((time.time() - start_time) * 1000, 2)
            )

    def get_transcript_text(self, url: str, include_timestamps: bool = False) -> dict:
        result = self.scrape(url)

        if not result.success or not result.data:
            return {
                "success": False,
                "error": result.error,
                "text": None
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
            "is_auto_generated": result.data.raw_data.get("is_auto_generated"),
            "word_count": result.data.raw_data.get("word_count")
        }
