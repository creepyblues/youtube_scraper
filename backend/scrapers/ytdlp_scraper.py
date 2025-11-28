import re
import time
from typing import Optional

import yt_dlp

from backend.models import (
    VideoMetadata,
    ChannelInfo,
    EngagementMetrics,
    TechnicalDetails,
    ContentClassification,
    Thumbnail,
    Chapter,
    TranscriptSegment,
    Comment,
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


def extract_hashtags(text: str) -> list[str]:
    if not text:
        return []
    return re.findall(r'#(\w+)', text)


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
                return ScraperResult(
                    success=False,
                    method="yt-dlp",
                    error="Could not extract video ID from URL"
                )

            with yt_dlp.YoutubeDL(self._get_ydl_opts()) as ydl:
                info = ydl.extract_info(url, download=False)

            if not info:
                return ScraperResult(
                    success=False,
                    method="yt-dlp",
                    error="Failed to extract video information"
                )

            metadata = self._parse_info(info, video_id)

            execution_time = (time.time() - start_time) * 1000
            fields_count = self._count_fields(metadata)

            return ScraperResult(
                success=True,
                method="yt-dlp",
                data=metadata,
                execution_time_ms=round(execution_time, 2),
                fields_extracted=fields_count
            )

        except yt_dlp.utils.DownloadError as e:
            return ScraperResult(
                success=False,
                method="yt-dlp",
                error=f"Download error: {str(e)}",
                execution_time_ms=round((time.time() - start_time) * 1000, 2)
            )
        except Exception as e:
            return ScraperResult(
                success=False,
                method="yt-dlp",
                error=f"Unexpected error: {str(e)}",
                execution_time_ms=round((time.time() - start_time) * 1000, 2)
            )

    def _parse_info(self, info: dict, video_id: str) -> VideoMetadata:
        thumbnails = []
        for thumb in info.get('thumbnails', []):
            if thumb.get('url'):
                thumbnails.append(Thumbnail(
                    url=thumb['url'],
                    width=thumb.get('width'),
                    height=thumb.get('height')
                ))

        chapters = []
        for chapter in info.get('chapters', []) or []:
            chapters.append(Chapter(
                title=chapter.get('title', 'Untitled'),
                start_time=chapter.get('start_time', 0),
                end_time=chapter.get('end_time')
            ))

        transcript = []
        subtitles = info.get('subtitles', {}) or {}
        automatic_captions = info.get('automatic_captions', {}) or {}

        all_subs = {**automatic_captions, **subtitles}
        for lang_code in ['en', 'en-US', 'en-GB', 'en-orig']:
            if lang_code in all_subs:
                for sub_format in all_subs[lang_code]:
                    if sub_format.get('ext') == 'json3' and 'data' in sub_format:
                        for event in sub_format.get('data', {}).get('events', []):
                            if 'segs' in event:
                                text = ''.join(seg.get('utf8', '') for seg in event['segs'])
                                if text.strip():
                                    transcript.append(TranscriptSegment(
                                        text=text.strip(),
                                        start=event.get('tStartMs', 0) / 1000,
                                        duration=event.get('dDurationMs', 0) / 1000
                                    ))
                break

        available_languages = list(set(subtitles.keys()) | set(automatic_captions.keys()))

        comments = []
        for comment_data in info.get('comments', []) or []:
            comments.append(Comment(
                author=comment_data.get('author', 'Unknown'),
                author_channel_id=comment_data.get('author_id'),
                text=comment_data.get('text', ''),
                likes=comment_data.get('like_count', 0) or 0,
                published_at=comment_data.get('timestamp'),
                reply_count=comment_data.get('reply_count', 0) or 0
            ))

        description = info.get('description', '')
        tags = info.get('tags', []) or []
        hashtags = extract_hashtags(description) + extract_hashtags(info.get('title', ''))

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
                category_id=None,
                tags=tags,
                hashtags=list(set(hashtags)),
                is_age_restricted=info.get('age_limit', 0) > 0,
                is_made_for_kids=None,
                is_live=info.get('is_live', False),
                is_upcoming=info.get('live_status') == 'is_upcoming'
            ),

            thumbnails=thumbnails,
            chapters=chapters,
            transcript=transcript,
            available_languages=available_languages,
            comments=comments[:100],

            webpage_url=info.get('webpage_url'),
            embed_url=f"https://www.youtube.com/embed/{video_id}",
            is_embeddable=info.get('playable_in_embed'),
            license=info.get('license'),

            raw_data=info,
            scraper_method="yt-dlp"
        )

    def _count_fields(self, metadata: VideoMetadata) -> int:
        count = 0
        if metadata.title:
            count += 1
        if metadata.description:
            count += 1
        if metadata.upload_date:
            count += 1
        if metadata.channel:
            count += 4
        if metadata.engagement:
            if metadata.engagement.view_count is not None:
                count += 1
            if metadata.engagement.like_count is not None:
                count += 1
            if metadata.engagement.comment_count is not None:
                count += 1
        if metadata.technical:
            count += 5
        if metadata.classification:
            count += len(metadata.classification.tags) + len(metadata.classification.hashtags) + 2
        count += len(metadata.thumbnails)
        count += len(metadata.chapters)
        count += len(metadata.transcript)
        count += len(metadata.comments)
        return count
