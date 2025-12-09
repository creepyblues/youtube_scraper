import asyncio
import os
import re
import time
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel


# ============ Models ============
from datetime import datetime


class Thumbnail(BaseModel):
    url: str
    width: Optional[int] = None
    height: Optional[int] = None


class Chapter(BaseModel):
    title: str
    start_time: float
    end_time: Optional[float] = None


class TranscriptSegment(BaseModel):
    text: str
    start: float
    duration: float


class Comment(BaseModel):
    author: str
    author_channel_id: Optional[str] = None
    text: str
    likes: int = 0
    published_at: Optional[str] = None
    reply_count: int = 0


class ChannelInfo(BaseModel):
    id: str
    name: str
    url: Optional[str] = None
    subscriber_count: Optional[int] = None


class EngagementMetrics(BaseModel):
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    dislike_count: Optional[int] = None
    comment_count: Optional[int] = None


class TechnicalDetails(BaseModel):
    duration: Optional[int] = None
    duration_string: Optional[str] = None
    definition: Optional[str] = None
    dimension: Optional[str] = None
    fps: Optional[float] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    filesize: Optional[int] = None
    bitrate: Optional[float] = None


class ContentClassification(BaseModel):
    category: Optional[str] = None
    category_id: Optional[str] = None
    tags: list[str] = []
    hashtags: list[str] = []
    is_age_restricted: bool = False
    is_made_for_kids: Optional[bool] = None
    is_live: bool = False
    is_upcoming: bool = False


class VideoMetadata(BaseModel):
    video_id: str
    title: str
    description: Optional[str] = None
    upload_date: Optional[str] = None
    publish_date: Optional[str] = None
    channel: Optional[ChannelInfo] = None
    engagement: Optional[EngagementMetrics] = None
    technical: Optional[TechnicalDetails] = None
    classification: Optional[ContentClassification] = None
    thumbnails: list[Thumbnail] = []
    chapters: list[Chapter] = []
    transcript: list[TranscriptSegment] = []
    available_languages: list[str] = []
    comments: list[Comment] = []
    webpage_url: Optional[str] = None
    embed_url: Optional[str] = None
    is_embeddable: Optional[bool] = None
    license: Optional[str] = None
    raw_data: Optional[dict] = None
    scraper_method: str = "unknown"
    scraped_at: str = ""

    def model_post_init(self, __context):
        if not self.scraped_at:
            self.scraped_at = datetime.utcnow().isoformat()


class ScraperResult(BaseModel):
    success: bool
    method: str
    data: Optional[VideoMetadata] = None
    error: Optional[str] = None
    execution_time_ms: Optional[float] = None
    fields_extracted: int = 0


class ComparisonResult(BaseModel):
    video_url: str
    results: list[ScraperResult]
    comparison_summary: dict = {}


# ============ Helpers ============
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


def extract_hashtags(text: str) -> list[str]:
    if not text:
        return []
    return re.findall(r'#(\w+)', text)


# ============ yt-dlp Scraper ============
import yt_dlp


class YtdlpScraper:
    def __init__(self, include_comments: bool = False, include_subtitles: bool = True):
        self.include_comments = include_comments
        self.include_subtitles = include_subtitles

    def _get_ydl_opts(self) -> dict:
        opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'skip_download': True,
        }
        if self.include_subtitles:
            opts['writesubtitles'] = True
            opts['writeautomaticsub'] = True
            opts['subtitleslangs'] = ['en', 'en-US', 'en-GB']
        if self.include_comments:
            opts['getcomments'] = True
        return opts

    def scrape(self, url: str) -> ScraperResult:
        start_time = time.time()
        try:
            video_id = extract_video_id(url)
            if not video_id:
                return ScraperResult(success=False, method="yt-dlp", error="Could not extract video ID from URL")

            with yt_dlp.YoutubeDL(self._get_ydl_opts()) as ydl:
                info = ydl.extract_info(url, download=False)

            if not info:
                return ScraperResult(success=False, method="yt-dlp", error="Failed to extract video information")

            metadata = self._parse_info(info, video_id)
            execution_time = (time.time() - start_time) * 1000
            fields_count = self._count_fields(metadata)

            return ScraperResult(
                success=True, method="yt-dlp", data=metadata,
                execution_time_ms=round(execution_time, 2), fields_extracted=fields_count
            )
        except yt_dlp.utils.DownloadError as e:
            return ScraperResult(success=False, method="yt-dlp", error=f"Download error: {str(e)}",
                                 execution_time_ms=round((time.time() - start_time) * 1000, 2))
        except Exception as e:
            return ScraperResult(success=False, method="yt-dlp", error=f"Unexpected error: {str(e)}",
                                 execution_time_ms=round((time.time() - start_time) * 1000, 2))

    def _parse_info(self, info: dict, video_id: str) -> VideoMetadata:
        thumbnails = [Thumbnail(url=t['url'], width=t.get('width'), height=t.get('height'))
                      for t in info.get('thumbnails', []) if t.get('url')]

        chapters = [Chapter(title=c.get('title', 'Untitled'), start_time=c.get('start_time', 0), end_time=c.get('end_time'))
                    for c in (info.get('chapters', []) or [])]

        transcript = []
        available_languages = list(set((info.get('subtitles', {}) or {}).keys()) |
                                   set((info.get('automatic_captions', {}) or {}).keys()))

        comments = [Comment(author=c.get('author', 'Unknown'), author_channel_id=c.get('author_id'),
                            text=c.get('text', ''), likes=c.get('like_count', 0) or 0,
                            published_at=c.get('timestamp'), reply_count=c.get('reply_count', 0) or 0)
                    for c in (info.get('comments', []) or [])][:100]

        description = info.get('description', '')
        tags = info.get('tags', []) or []
        hashtags = list(set(extract_hashtags(description) + extract_hashtags(info.get('title', ''))))

        return VideoMetadata(
            video_id=video_id,
            title=info.get('title', ''),
            description=description,
            upload_date=info.get('upload_date'),
            publish_date=info.get('release_date') or info.get('upload_date'),
            channel=ChannelInfo(
                id=info.get('channel_id', ''),
                name=info.get('channel', '') or info.get('uploader', ''),
                url=info.get('channel_url') or info.get('uploader_url'),
                subscriber_count=info.get('channel_follower_count')
            ),
            engagement=EngagementMetrics(
                view_count=info.get('view_count'),
                like_count=info.get('like_count'),
                dislike_count=info.get('dislike_count'),
                comment_count=info.get('comment_count')
            ),
            technical=TechnicalDetails(
                duration=info.get('duration'),
                duration_string=info.get('duration_string'),
                definition='hd' if info.get('height', 0) >= 720 else 'sd',
                dimension='3d' if info.get('is_3d') else '2d',
                fps=info.get('fps'),
                video_codec=info.get('vcodec'),
                audio_codec=info.get('acodec'),
                filesize=info.get('filesize') or info.get('filesize_approx'),
                bitrate=info.get('tbr')
            ),
            classification=ContentClassification(
                category=info.get('categories', [None])[0] if info.get('categories') else None,
                tags=tags, hashtags=hashtags,
                is_age_restricted=info.get('age_limit', 0) > 0,
                is_live=info.get('is_live', False),
                is_upcoming=info.get('live_status') == 'is_upcoming'
            ),
            thumbnails=thumbnails, chapters=chapters, transcript=transcript,
            available_languages=available_languages, comments=comments,
            webpage_url=info.get('webpage_url'),
            embed_url=f"https://www.youtube.com/embed/{video_id}",
            is_embeddable=info.get('playable_in_embed'),
            license=info.get('license'),
            raw_data=info, scraper_method="yt-dlp"
        )

    def _count_fields(self, metadata: VideoMetadata) -> int:
        count = 0
        if metadata.title: count += 1
        if metadata.description: count += 1
        if metadata.upload_date: count += 1
        if metadata.channel: count += 4
        if metadata.engagement:
            if metadata.engagement.view_count is not None: count += 1
            if metadata.engagement.like_count is not None: count += 1
            if metadata.engagement.comment_count is not None: count += 1
        if metadata.technical: count += 5
        if metadata.classification:
            count += len(metadata.classification.tags) + len(metadata.classification.hashtags) + 2
        count += len(metadata.thumbnails) + len(metadata.chapters) + len(metadata.transcript) + len(metadata.comments)
        return count


# ============ yt-dlp Transcript Extractor ============
class YtdlpTranscriptExtractor:
    def __init__(self, preferred_languages: list[str] = None):
        self.preferred_languages = preferred_languages or ['en', 'en-US', 'en-GB', 'en-orig']

    def extract(self, url: str) -> ScraperResult:
        start_time = time.time()
        try:
            video_id = extract_video_id(url)
            if not video_id:
                return ScraperResult(success=False, method="yt-dlp-transcript", error="Could not extract video ID")

            opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'writesubtitles': True,
                'writeautomaticsub': True,
                'subtitleslangs': self.preferred_languages,
                'subtitlesformat': 'json3',
            }

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if not info:
                return ScraperResult(success=False, method="yt-dlp-transcript", error="Failed to extract video info")

            # Try to get subtitles from requested_subtitles or automatic_captions
            subtitles = info.get('subtitles', {}) or {}
            auto_captions = info.get('automatic_captions', {}) or {}
            requested = info.get('requested_subtitles', {}) or {}

            transcript_data = []
            used_language = None
            is_auto = False

            # First try requested subtitles (these have actual content)
            for lang in self.preferred_languages:
                if lang in requested and requested[lang]:
                    sub_info = requested[lang]
                    if 'data' in sub_info:
                        transcript_data = self._parse_json3(sub_info['data'])
                        used_language = lang
                        is_auto = lang in auto_captions
                        break

            # If no requested subtitles, try to fetch from URL
            if not transcript_data:
                import httpx
                for lang in self.preferred_languages:
                    for source, is_auto_source in [(subtitles, False), (auto_captions, True)]:
                        if lang in source:
                            for fmt in source[lang]:
                                if fmt.get('ext') == 'json3' and fmt.get('url'):
                                    try:
                                        resp = httpx.get(fmt['url'], timeout=10)
                                        if resp.status_code == 200:
                                            import json
                                            data = resp.json()
                                            transcript_data = self._parse_json3(data)
                                            used_language = lang
                                            is_auto = is_auto_source
                                            break
                                    except:
                                        continue
                            if transcript_data:
                                break
                    if transcript_data:
                        break

            if not transcript_data:
                return ScraperResult(success=False, method="yt-dlp-transcript",
                                     error="No transcript found via yt-dlp",
                                     execution_time_ms=round((time.time() - start_time) * 1000, 2))

            segments = [TranscriptSegment(text=seg['text'], start=seg['start'], duration=seg['duration'])
                        for seg in transcript_data if seg.get('text')]
            full_text = ' '.join(seg.text for seg in segments)

            available_languages = list(set(subtitles.keys()) | set(auto_captions.keys()))

            metadata = VideoMetadata(
                video_id=video_id, title=info.get('title', ''), transcript=segments,
                available_languages=available_languages,
                webpage_url=f"https://www.youtube.com/watch?v={video_id}",
                scraper_method="yt-dlp-transcript",
                raw_data={"transcript_language": used_language, "is_auto_generated": is_auto,
                          "word_count": len(full_text.split()), "segment_count": len(segments)}
            )

            return ScraperResult(success=True, method="yt-dlp-transcript", data=metadata,
                                 execution_time_ms=round((time.time() - start_time) * 1000, 2),
                                 fields_extracted=len(segments) + len(available_languages) + 2)

        except Exception as e:
            return ScraperResult(success=False, method="yt-dlp-transcript", error=f"Error: {str(e)}",
                                 execution_time_ms=round((time.time() - start_time) * 1000, 2))

    def _parse_json3(self, data: dict) -> list[dict]:
        """Parse YouTube's json3 subtitle format"""
        segments = []
        events = data.get('events', []) if isinstance(data, dict) else []
        for event in events:
            if 'segs' in event:
                text = ''.join(seg.get('utf8', '') for seg in event['segs']).strip()
                if text:
                    segments.append({
                        'text': text,
                        'start': event.get('tStartMs', 0) / 1000,
                        'duration': event.get('dDurationMs', 0) / 1000
                    })
        return segments


# ============ OpenAI Whisper API Transcriber ============
class OpenAIWhisperTranscriber:
    """Transcribe YouTube audio using OpenAI's Whisper API"""

    def __init__(self):
        self.api_key = os.getenv('OPENAI_API_KEY')
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if not self.api_key:
                raise ValueError("OPENAI_API_KEY not configured")
            self._client = OpenAI(api_key=self.api_key)
        return self._client

    def is_available(self) -> bool:
        return bool(self.api_key)

    def scrape(self, url: str) -> ScraperResult:
        start_time = time.time()

        if not self.is_available():
            return ScraperResult(
                success=False,
                method="openai-whisper",
                error="OPENAI_API_KEY not configured. Add it to your environment variables."
            )

        try:
            video_id = extract_video_id(url)
            if not video_id:
                return ScraperResult(
                    success=False,
                    method="openai-whisper",
                    error="Could not extract video ID from URL"
                )

            # Download audio using yt-dlp
            audio_path = self._download_audio(url)
            if not audio_path:
                return ScraperResult(
                    success=False,
                    method="openai-whisper",
                    error="Failed to download audio from YouTube",
                    execution_time_ms=round((time.time() - start_time) * 1000, 2)
                )

            try:
                # Transcribe with OpenAI Whisper API
                transcript_data = self._transcribe_audio(audio_path)

                if not transcript_data:
                    return ScraperResult(
                        success=False,
                        method="openai-whisper",
                        error="Transcription failed",
                        execution_time_ms=round((time.time() - start_time) * 1000, 2)
                    )

                segments = transcript_data.get('segments', [])
                full_text = transcript_data.get('text', '')

                transcript_segments = [
                    TranscriptSegment(
                        text=seg.get('text', '').strip(),
                        start=seg.get('start', 0),
                        duration=seg.get('end', 0) - seg.get('start', 0)
                    )
                    for seg in segments if seg.get('text', '').strip()
                ]

                # If no segments but we have text, create a single segment
                if not transcript_segments and full_text:
                    transcript_segments = [
                        TranscriptSegment(text=full_text, start=0, duration=0)
                    ]

                metadata = VideoMetadata(
                    video_id=video_id,
                    title="",
                    transcript=transcript_segments,
                    webpage_url=f"https://www.youtube.com/watch?v={video_id}",
                    scraper_method="openai-whisper",
                    raw_data={
                        "language": transcript_data.get('language', 'unknown'),
                        "word_count": len(full_text.split()),
                        "segment_count": len(transcript_segments),
                        "full_transcript_text": full_text
                    }
                )

                return ScraperResult(
                    success=True,
                    method="openai-whisper",
                    data=metadata,
                    execution_time_ms=round((time.time() - start_time) * 1000, 2),
                    fields_extracted=len(transcript_segments) + 2
                )

            finally:
                # Clean up temp file
                if os.path.exists(audio_path):
                    os.remove(audio_path)

        except Exception as e:
            return ScraperResult(
                success=False,
                method="openai-whisper",
                error=f"Error: {str(e)}",
                execution_time_ms=round((time.time() - start_time) * 1000, 2)
            )

    def _download_audio(self, url: str) -> Optional[str]:
        """Download audio from YouTube video using yt-dlp"""
        try:
            # Create temp file for audio
            temp_dir = tempfile.gettempdir()
            temp_path = os.path.join(temp_dir, f"yt_audio_{int(time.time())}")

            ydl_opts = {
                'format': 'bestaudio[ext=m4a]/bestaudio/best',
                'outtmpl': temp_path + '.%(ext)s',
                'quiet': True,
                'no_warnings': True,
                'extract_audio': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '64',  # Lower quality = smaller file = faster upload
                }],
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            # Find the output file
            for ext in ['mp3', 'm4a', 'webm', 'opus']:
                path = f"{temp_path}.{ext}"
                if os.path.exists(path):
                    return path

            return None

        except Exception as e:
            print(f"Audio download error: {e}")
            return None

    def _transcribe_audio(self, audio_path: str) -> Optional[dict]:
        """Transcribe audio file using OpenAI Whisper API"""
        try:
            # Check file size (OpenAI limit is 25MB)
            file_size = os.path.getsize(audio_path)
            if file_size > 25 * 1024 * 1024:
                raise ValueError(f"Audio file too large ({file_size / 1024 / 1024:.1f}MB). Max is 25MB.")

            with open(audio_path, 'rb') as audio_file:
                response = self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"]
                )

            return {
                'text': response.text,
                'language': getattr(response, 'language', 'unknown'),
                'segments': [
                    {
                        'start': seg.start,
                        'end': seg.end,
                        'text': seg.text
                    }
                    for seg in getattr(response, 'segments', [])
                ]
            }

        except Exception as e:
            print(f"Transcription error: {e}")
            raise


# ============ Transcript Scraper (youtube-transcript-api) ============
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound, VideoUnavailable


class TranscriptScraper:
    def __init__(self, preferred_languages: list[str] = None):
        self.preferred_languages = preferred_languages or ['en', 'en-US', 'en-GB']
        self._api = YouTubeTranscriptApi()

    def scrape(self, url: str) -> ScraperResult:
        start_time = time.time()
        try:
            video_id = extract_video_id(url)
            if not video_id:
                return ScraperResult(success=False, method="youtube-transcript-api", error="Could not extract video ID")

            transcript_list = self._api.list(video_id)
            available_languages, manual_languages, auto_languages = [], [], []

            for transcript in transcript_list:
                available_languages.append(transcript.language_code)
                (auto_languages if transcript.is_generated else manual_languages).append(transcript.language_code)

            transcript_data, used_language, is_auto_generated = None, None, False

            for lang in self.preferred_languages:
                try:
                    transcript_obj = transcript_list.find_transcript([lang])
                    transcript_data = transcript_obj.fetch()
                    used_language, is_auto_generated = transcript_obj.language_code, transcript_obj.is_generated
                    break
                except NoTranscriptFound:
                    continue

            if not transcript_data:
                for method, is_auto in [(transcript_list.find_manually_created_transcript, False),
                                        (transcript_list.find_generated_transcript, True)]:
                    try:
                        transcript_obj = method(self.preferred_languages)
                        transcript_data = transcript_obj.fetch()
                        used_language, is_auto_generated = transcript_obj.language_code, is_auto
                        break
                    except NoTranscriptFound:
                        continue

            if not transcript_data and available_languages:
                first = list(transcript_list)[0]
                transcript_data = first.fetch()
                used_language, is_auto_generated = first.language_code, first.is_generated

            if not transcript_data:
                return ScraperResult(success=False, method="youtube-transcript-api", error="No transcripts available",
                                     execution_time_ms=round((time.time() - start_time) * 1000, 2))

            segments = [TranscriptSegment(text=item.text, start=item.start, duration=item.duration)
                        for item in transcript_data]
            full_text = ' '.join(seg.text for seg in segments)

            metadata = VideoMetadata(
                video_id=video_id, title="", transcript=segments, available_languages=available_languages,
                webpage_url=f"https://www.youtube.com/watch?v={video_id}", scraper_method="youtube-transcript-api",
                raw_data={"transcript_language": used_language, "is_auto_generated": is_auto_generated,
                          "word_count": len(full_text.split()), "segment_count": len(segments),
                          "full_transcript_text": full_text}
            )

            return ScraperResult(success=True, method="youtube-transcript-api", data=metadata,
                                 execution_time_ms=round((time.time() - start_time) * 1000, 2),
                                 fields_extracted=len(segments) + len(available_languages) + 2)

        except TranscriptsDisabled:
            return ScraperResult(success=False, method="youtube-transcript-api", error="Transcripts are disabled",
                                 execution_time_ms=round((time.time() - start_time) * 1000, 2))
        except VideoUnavailable:
            return ScraperResult(success=False, method="youtube-transcript-api", error="Video is unavailable",
                                 execution_time_ms=round((time.time() - start_time) * 1000, 2))
        except Exception as e:
            return ScraperResult(success=False, method="youtube-transcript-api", error=f"Error: {str(e)}",
                                 execution_time_ms=round((time.time() - start_time) * 1000, 2))


# ============ YouTube API Scraper ============
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

CATEGORY_MAP = {
    "1": "Film & Animation", "2": "Autos & Vehicles", "10": "Music", "15": "Pets & Animals",
    "17": "Sports", "20": "Gaming", "22": "People & Blogs", "23": "Comedy", "24": "Entertainment",
    "25": "News & Politics", "26": "Howto & Style", "27": "Education", "28": "Science & Technology",
}


def parse_duration(duration_str: str) -> Optional[int]:
    if not duration_str:
        return None
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
    if not match:
        return None
    return int(match.group(1) or 0) * 3600 + int(match.group(2) or 0) * 60 + int(match.group(3) or 0)


def format_duration(seconds: Optional[int]) -> Optional[str]:
    if seconds is None:
        return None
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours > 0 else f"{minutes}:{secs:02d}"


class YouTubeAPIScraper:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('YOUTUBE_API_KEY')
        self._youtube = None

    @property
    def youtube(self):
        if self._youtube is None:
            if not self.api_key:
                raise ValueError("YouTube API key is required")
            self._youtube = build('youtube', 'v3', developerKey=self.api_key)
        return self._youtube

    def scrape(self, url: str, include_comments: bool = False) -> ScraperResult:
        start_time = time.time()
        if not self.api_key:
            return ScraperResult(success=False, method="YouTube API v3",
                                 error="YouTube API key not configured. Set YOUTUBE_API_KEY environment variable.")
        try:
            video_id = extract_video_id(url)
            if not video_id:
                return ScraperResult(success=False, method="YouTube API v3", error="Could not extract video ID")

            video_response = self.youtube.videos().list(
                part='snippet,contentDetails,statistics,status,topicDetails,liveStreamingDetails', id=video_id
            ).execute()

            if not video_response.get('items'):
                return ScraperResult(success=False, method="YouTube API v3", error="Video not found or is private")

            video_data = video_response['items'][0]
            snippet = video_data.get('snippet', {})
            channel_id = snippet.get('channelId')

            channel_data = None
            if channel_id:
                channel_response = self.youtube.channels().list(part='snippet,statistics', id=channel_id).execute()
                if channel_response.get('items'):
                    channel_data = channel_response['items'][0]

            comments = []
            if include_comments:
                try:
                    comments_response = self.youtube.commentThreads().list(
                        part='snippet', videoId=video_id, maxResults=100, order='relevance'
                    ).execute()
                    for item in comments_response.get('items', []):
                        s = item['snippet']['topLevelComment']['snippet']
                        comments.append(Comment(
                            author=s.get('authorDisplayName', 'Unknown'),
                            author_channel_id=s.get('authorChannelId', {}).get('value'),
                            text=s.get('textDisplay', ''), likes=s.get('likeCount', 0),
                            published_at=s.get('publishedAt'), reply_count=item['snippet'].get('totalReplyCount', 0)
                        ))
                except HttpError:
                    pass

            metadata = self._parse_response(video_id, video_data, channel_data, comments)
            return ScraperResult(success=True, method="YouTube API v3", data=metadata,
                                 execution_time_ms=round((time.time() - start_time) * 1000, 2),
                                 fields_extracted=self._count_fields(metadata))

        except HttpError as e:
            return ScraperResult(success=False, method="YouTube API v3", error=f"API Error: {e.reason}",
                                 execution_time_ms=round((time.time() - start_time) * 1000, 2))
        except Exception as e:
            return ScraperResult(success=False, method="YouTube API v3", error=f"Error: {str(e)}",
                                 execution_time_ms=round((time.time() - start_time) * 1000, 2))

    def _parse_response(self, video_id: str, video_data: dict, channel_data: Optional[dict],
                        comments: list[Comment]) -> VideoMetadata:
        snippet = video_data.get('snippet', {})
        content_details = video_data.get('contentDetails', {})
        statistics = video_data.get('statistics', {})
        status = video_data.get('status', {})

        thumbnails = [Thumbnail(url=t.get('url', ''), width=t.get('width'), height=t.get('height'))
                      for t in snippet.get('thumbnails', {}).values()]

        description = snippet.get('description', '')
        tags = snippet.get('tags', []) or []
        hashtags = list(set(extract_hashtags(description) + extract_hashtags(snippet.get('title', ''))))
        duration_seconds = parse_duration(content_details.get('duration'))

        channel_info = None
        if channel_data:
            cs, cst = channel_data.get('snippet', {}), channel_data.get('statistics', {})
            channel_info = ChannelInfo(
                id=channel_data.get('id', snippet.get('channelId', '')),
                name=cs.get('title', snippet.get('channelTitle', '')),
                url=f"https://www.youtube.com/channel/{channel_data.get('id', '')}",
                subscriber_count=int(cst.get('subscriberCount', 0)) if cst.get('subscriberCount') else None
            )
        else:
            channel_info = ChannelInfo(id=snippet.get('channelId', ''), name=snippet.get('channelTitle', ''),
                                       url=f"https://www.youtube.com/channel/{snippet.get('channelId', '')}")

        return VideoMetadata(
            video_id=video_id, title=snippet.get('title', ''), description=description,
            upload_date=snippet.get('publishedAt', '').split('T')[0].replace('-', '') if snippet.get('publishedAt') else None,
            publish_date=snippet.get('publishedAt'), channel=channel_info,
            engagement=EngagementMetrics(
                view_count=int(statistics.get('viewCount', 0)) if statistics.get('viewCount') else None,
                like_count=int(statistics.get('likeCount', 0)) if statistics.get('likeCount') else None,
                comment_count=int(statistics.get('commentCount', 0)) if statistics.get('commentCount') else None
            ),
            technical=TechnicalDetails(duration=duration_seconds, duration_string=format_duration(duration_seconds),
                                       definition=content_details.get('definition', 'sd'),
                                       dimension=content_details.get('dimension', '2d')),
            classification=ContentClassification(
                category=CATEGORY_MAP.get(snippet.get('categoryId')), category_id=snippet.get('categoryId'),
                tags=tags, hashtags=hashtags,
                is_age_restricted=content_details.get('contentRating', {}).get('ytRating') == 'ytAgeRestricted',
                is_made_for_kids=status.get('madeForKids')
            ),
            thumbnails=thumbnails, comments=comments,
            webpage_url=f"https://www.youtube.com/watch?v={video_id}",
            embed_url=f"https://www.youtube.com/embed/{video_id}",
            is_embeddable=status.get('embeddable'), license=status.get('license'),
            raw_data=video_data, scraper_method="YouTube API v3"
        )

    def _count_fields(self, metadata: VideoMetadata) -> int:
        count = 0
        if metadata.title: count += 1
        if metadata.description: count += 1
        if metadata.upload_date: count += 1
        if metadata.channel: count += 4
        if metadata.engagement:
            if metadata.engagement.view_count is not None: count += 1
            if metadata.engagement.like_count is not None: count += 1
            if metadata.engagement.comment_count is not None: count += 1
        if metadata.technical: count += 3
        if metadata.classification:
            count += len(metadata.classification.tags) + len(metadata.classification.hashtags) + 3
        count += len(metadata.thumbnails) + len(metadata.comments)
        return count


# ============ FastAPI App ============
app = FastAPI(
    title="YouTube Metadata Scraper",
    description="Extract comprehensive metadata from YouTube videos using multiple methods",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

executor = ThreadPoolExecutor(max_workers=3)


class ScrapeRequest(BaseModel):
    url: str
    include_comments: bool = False
    include_transcript: bool = True


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "YouTube Metadata Scraper"}


@app.post("/api/scrape/ytdlp", response_model=ScraperResult)
async def scrape_with_ytdlp(request: ScrapeRequest):
    loop = asyncio.get_event_loop()
    scraper = YtdlpScraper(include_comments=request.include_comments, include_subtitles=request.include_transcript)
    result = await loop.run_in_executor(executor, scraper.scrape, request.url)
    return result


@app.post("/api/scrape/youtube-api", response_model=ScraperResult)
async def scrape_with_youtube_api(request: ScrapeRequest):
    loop = asyncio.get_event_loop()
    scraper = YouTubeAPIScraper()
    result = await loop.run_in_executor(executor, lambda: scraper.scrape(request.url, request.include_comments))
    return result


@app.post("/api/scrape/transcript", response_model=ScraperResult)
async def scrape_transcript(request: ScrapeRequest):
    """Try yt-dlp first (works better on cloud), fallback to youtube-transcript-api"""
    loop = asyncio.get_event_loop()

    # Try yt-dlp transcript extraction first (better for cloud IPs)
    ytdlp_extractor = YtdlpTranscriptExtractor()
    result = await loop.run_in_executor(executor, ytdlp_extractor.extract, request.url)

    if result.success:
        return result

    # Fallback to youtube-transcript-api
    scraper = TranscriptScraper()
    fallback_result = await loop.run_in_executor(executor, scraper.scrape, request.url)

    # If fallback also failed, return user-friendly error
    if not fallback_result.success:
        is_cloud_block = "bot" in str(result.error).lower() or "blocking" in str(fallback_result.error).lower()
        if is_cloud_block:
            error_msg = "YouTube is blocking requests from this cloud server. Transcript extraction works when running locally. Try: git clone https://github.com/creepyblues/youtube_scraper && cd youtube_scraper && pip install -r requirements.txt && uvicorn backend.main:app"
        else:
            error_msg = f"yt-dlp: {result.error} | youtube-transcript-api: {fallback_result.error}"

        return ScraperResult(
            success=False,
            method="transcript (combined)",
            error=error_msg,
            execution_time_ms=(result.execution_time_ms or 0) + (fallback_result.execution_time_ms or 0)
        )

    return fallback_result


@app.post("/api/scrape/transcript-ai", response_model=ScraperResult)
async def scrape_transcript_ai(request: ScrapeRequest):
    """Transcribe video using OpenAI Whisper API"""
    loop = asyncio.get_event_loop()
    transcriber = OpenAIWhisperTranscriber()

    if not transcriber.is_available():
        return ScraperResult(
            success=False,
            method="openai-whisper",
            error="OPENAI_API_KEY not configured. Add it to your Vercel environment variables."
        )

    result = await loop.run_in_executor(executor, transcriber.scrape, request.url)
    return result


@app.post("/api/scrape/compare", response_model=ComparisonResult)
async def compare_scrapers(request: ScrapeRequest):
    loop = asyncio.get_event_loop()

    ytdlp_scraper = YtdlpScraper(include_comments=request.include_comments, include_subtitles=request.include_transcript)
    api_scraper = YouTubeAPIScraper()
    ytdlp_transcript = YtdlpTranscriptExtractor()

    results = await asyncio.gather(
        loop.run_in_executor(executor, ytdlp_scraper.scrape, request.url),
        loop.run_in_executor(executor, lambda: api_scraper.scrape(request.url, request.include_comments)),
        loop.run_in_executor(executor, ytdlp_transcript.extract, request.url)
    )

    comparison_summary = generate_comparison_summary(results)
    return ComparisonResult(video_url=request.url, results=list(results), comparison_summary=comparison_summary)


def generate_comparison_summary(results: list[ScraperResult]) -> dict:
    summary = {"methods_succeeded": [], "methods_failed": [], "field_comparison": {}, "best_for": {}, "total_unique_fields": 0}

    for result in results:
        if result.success:
            summary["methods_succeeded"].append(result.method)
        else:
            summary["methods_failed"].append({"method": result.method, "error": result.error})

    field_availability = {
        "title": {}, "description": {}, "view_count": {}, "like_count": {}, "comment_count": {},
        "transcript": {}, "chapters": {}, "tags": {}, "thumbnails": {}, "channel_subscribers": {},
        "technical_details": {}, "comments": {}
    }

    for result in results:
        if not result.success or not result.data:
            continue
        method, data = result.method, result.data
        field_availability["title"][method] = bool(data.title)
        field_availability["description"][method] = bool(data.description)
        if data.engagement:
            field_availability["view_count"][method] = data.engagement.view_count is not None
            field_availability["like_count"][method] = data.engagement.like_count is not None
            field_availability["comment_count"][method] = data.engagement.comment_count is not None
        field_availability["transcript"][method] = len(data.transcript) > 0
        field_availability["chapters"][method] = len(data.chapters) > 0
        if data.classification:
            field_availability["tags"][method] = len(data.classification.tags) > 0
        field_availability["thumbnails"][method] = len(data.thumbnails) > 0
        if data.channel:
            field_availability["channel_subscribers"][method] = data.channel.subscriber_count is not None
        if data.technical:
            field_availability["technical_details"][method] = any([data.technical.fps, data.technical.video_codec, data.technical.bitrate])
        field_availability["comments"][method] = len(data.comments) > 0

    summary["field_comparison"] = field_availability

    best_for = {}
    for result in results:
        if result.success and result.data:
            if len(result.data.transcript) > 0:
                if "transcript" not in best_for or len(result.data.transcript) > best_for["transcript"]["count"]:
                    best_for["transcript"] = {"method": result.method, "count": len(result.data.transcript)}
            if result.data.technical and result.data.technical.fps is not None:
                best_for["technical_details"] = {"method": result.method}
            if result.data.classification and len(result.data.classification.tags) > 0:
                if "tags" not in best_for or len(result.data.classification.tags) > best_for["tags"]["count"]:
                    best_for["tags"] = {"method": result.method, "count": len(result.data.classification.tags)}

    summary["best_for"] = best_for
    summary["total_unique_fields"] = len([f for f, methods in field_availability.items() if any(methods.values())])
    return summary
