from pydantic import BaseModel
from typing import Optional
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
