import os
import re
import time
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.models import (
    VideoMetadata,
    ChannelInfo,
    EngagementMetrics,
    TechnicalDetails,
    ContentClassification,
    Thumbnail,
    Chapter,
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


def parse_duration(duration_str: str) -> Optional[int]:
    if not duration_str:
        return None

    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
    if not match:
        return None

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)

    return hours * 3600 + minutes * 60 + seconds


def format_duration(seconds: Optional[int]) -> Optional[str]:
    if seconds is None:
        return None

    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def extract_hashtags(text: str) -> list[str]:
    if not text:
        return []
    return re.findall(r'#(\w+)', text)


def parse_chapters_from_description(description: str) -> list[Chapter]:
    if not description:
        return []

    chapters = []
    pattern = r'(?:^|\n)\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s*[-–—]?\s*(.+?)(?=\n|$)'

    matches = re.findall(pattern, description)

    for match in matches:
        hours = int(match[0]) if match[0] else 0
        minutes = int(match[1])
        seconds = int(match[2])
        title = match[3].strip()

        start_time = hours * 3600 + minutes * 60 + seconds

        if title and len(title) > 1:
            chapters.append(Chapter(
                title=title,
                start_time=start_time,
                end_time=None
            ))

    for i in range(len(chapters) - 1):
        chapters[i].end_time = chapters[i + 1].start_time

    return chapters


CATEGORY_MAP = {
    "1": "Film & Animation",
    "2": "Autos & Vehicles",
    "10": "Music",
    "15": "Pets & Animals",
    "17": "Sports",
    "18": "Short Movies",
    "19": "Travel & Events",
    "20": "Gaming",
    "21": "Videoblogging",
    "22": "People & Blogs",
    "23": "Comedy",
    "24": "Entertainment",
    "25": "News & Politics",
    "26": "Howto & Style",
    "27": "Education",
    "28": "Science & Technology",
    "29": "Nonprofits & Activism",
    "30": "Movies",
    "31": "Anime/Animation",
    "32": "Action/Adventure",
    "33": "Classics",
    "34": "Comedy",
    "35": "Documentary",
    "36": "Drama",
    "37": "Family",
    "38": "Foreign",
    "39": "Horror",
    "40": "Sci-Fi/Fantasy",
    "41": "Thriller",
    "42": "Shorts",
    "43": "Shows",
    "44": "Trailers",
}


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
            return ScraperResult(
                success=False,
                method="YouTube API v3",
                error="YouTube API key not configured. Set YOUTUBE_API_KEY environment variable."
            )

        try:
            video_id = extract_video_id(url)
            if not video_id:
                return ScraperResult(
                    success=False,
                    method="YouTube API v3",
                    error="Could not extract video ID from URL"
                )

            video_response = self.youtube.videos().list(
                part='snippet,contentDetails,statistics,status,topicDetails,recordingDetails,liveStreamingDetails',
                id=video_id
            ).execute()

            if not video_response.get('items'):
                return ScraperResult(
                    success=False,
                    method="YouTube API v3",
                    error="Video not found or is private"
                )

            video_data = video_response['items'][0]

            channel_id = video_data['snippet'].get('channelId')
            channel_data = None
            if channel_id:
                channel_response = self.youtube.channels().list(
                    part='snippet,statistics',
                    id=channel_id
                ).execute()
                if channel_response.get('items'):
                    channel_data = channel_response['items'][0]

            comments = []
            if include_comments:
                try:
                    comments_response = self.youtube.commentThreads().list(
                        part='snippet',
                        videoId=video_id,
                        maxResults=100,
                        order='relevance'
                    ).execute()

                    for item in comments_response.get('items', []):
                        snippet = item['snippet']['topLevelComment']['snippet']
                        comments.append(Comment(
                            author=snippet.get('authorDisplayName', 'Unknown'),
                            author_channel_id=snippet.get('authorChannelId', {}).get('value'),
                            text=snippet.get('textDisplay', ''),
                            likes=snippet.get('likeCount', 0),
                            published_at=snippet.get('publishedAt'),
                            reply_count=item['snippet'].get('totalReplyCount', 0)
                        ))
                except HttpError:
                    pass

            metadata = self._parse_response(video_id, video_data, channel_data, comments)

            execution_time = (time.time() - start_time) * 1000
            fields_count = self._count_fields(metadata)

            return ScraperResult(
                success=True,
                method="YouTube API v3",
                data=metadata,
                execution_time_ms=round(execution_time, 2),
                fields_extracted=fields_count
            )

        except HttpError as e:
            return ScraperResult(
                success=False,
                method="YouTube API v3",
                error=f"API Error: {e.reason}",
                execution_time_ms=round((time.time() - start_time) * 1000, 2)
            )
        except Exception as e:
            return ScraperResult(
                success=False,
                method="YouTube API v3",
                error=f"Unexpected error: {str(e)}",
                execution_time_ms=round((time.time() - start_time) * 1000, 2)
            )

    def _parse_response(
        self,
        video_id: str,
        video_data: dict,
        channel_data: Optional[dict],
        comments: list[Comment]
    ) -> VideoMetadata:
        snippet = video_data.get('snippet', {})
        content_details = video_data.get('contentDetails', {})
        statistics = video_data.get('statistics', {})
        status = video_data.get('status', {})
        live_details = video_data.get('liveStreamingDetails', {})

        thumbnails = []
        for key, thumb in snippet.get('thumbnails', {}).items():
            thumbnails.append(Thumbnail(
                url=thumb.get('url', ''),
                width=thumb.get('width'),
                height=thumb.get('height')
            ))

        description = snippet.get('description', '')
        chapters = parse_chapters_from_description(description)

        tags = snippet.get('tags', []) or []
        hashtags = extract_hashtags(description) + extract_hashtags(snippet.get('title', ''))

        duration_seconds = parse_duration(content_details.get('duration'))
        definition = content_details.get('definition', 'sd')

        channel_info = None
        if channel_data:
            channel_snippet = channel_data.get('snippet', {})
            channel_stats = channel_data.get('statistics', {})
            channel_info = ChannelInfo(
                id=channel_data.get('id', snippet.get('channelId', '')),
                name=channel_snippet.get('title', snippet.get('channelTitle', '')),
                url=f"https://www.youtube.com/channel/{channel_data.get('id', '')}",
                subscriber_count=int(channel_stats.get('subscriberCount', 0)) if channel_stats.get('subscriberCount') else None
            )
        else:
            channel_info = ChannelInfo(
                id=snippet.get('channelId', ''),
                name=snippet.get('channelTitle', ''),
                url=f"https://www.youtube.com/channel/{snippet.get('channelId', '')}",
                subscriber_count=None
            )

        category_id = snippet.get('categoryId')

        is_live = live_details.get('activeLiveChatId') is not None
        is_upcoming = live_details.get('scheduledStartTime') is not None and not is_live

        return VideoMetadata(
            video_id=video_id,
            title=snippet.get('title', ''),
            description=description,
            upload_date=snippet.get('publishedAt', '').split('T')[0].replace('-', '') if snippet.get('publishedAt') else None,
            publish_date=snippet.get('publishedAt'),

            channel=channel_info,

            engagement=EngagementMetrics(
                view_count=int(statistics.get('viewCount', 0)) if statistics.get('viewCount') else None,
                like_count=int(statistics.get('likeCount', 0)) if statistics.get('likeCount') else None,
                dislike_count=None,
                comment_count=int(statistics.get('commentCount', 0)) if statistics.get('commentCount') else None
            ),

            technical=TechnicalDetails(
                duration=duration_seconds,
                duration_string=format_duration(duration_seconds),
                definition=definition,
                dimension=content_details.get('dimension', '2d'),
                fps=None,
                video_codec=None,
                audio_codec=None,
                filesize=None,
                bitrate=None
            ),

            classification=ContentClassification(
                category=CATEGORY_MAP.get(category_id),
                category_id=category_id,
                tags=tags,
                hashtags=list(set(hashtags)),
                is_age_restricted=content_details.get('contentRating', {}).get('ytRating') == 'ytAgeRestricted',
                is_made_for_kids=status.get('madeForKids'),
                is_live=is_live,
                is_upcoming=is_upcoming
            ),

            thumbnails=thumbnails,
            chapters=chapters,
            transcript=[],
            available_languages=[],
            comments=comments,

            webpage_url=f"https://www.youtube.com/watch?v={video_id}",
            embed_url=f"https://www.youtube.com/embed/{video_id}",
            is_embeddable=status.get('embeddable'),
            license=status.get('license'),

            raw_data=video_data,
            scraper_method="YouTube API v3"
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
            count += 3
        if metadata.classification:
            count += len(metadata.classification.tags) + len(metadata.classification.hashtags) + 3
        count += len(metadata.thumbnails)
        count += len(metadata.chapters)
        count += len(metadata.comments)
        return count
