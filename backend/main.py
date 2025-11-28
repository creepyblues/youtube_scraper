import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.scrapers import YtdlpScraper, YouTubeAPIScraper, TranscriptScraper
from backend.models import ScraperResult, ComparisonResult


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


class TranscriptRequest(BaseModel):
    url: str
    include_timestamps: bool = False


@app.get("/")
async def root():
    return FileResponse("frontend/index.html")


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "YouTube Metadata Scraper"}


@app.post("/api/scrape/ytdlp", response_model=ScraperResult)
async def scrape_with_ytdlp(request: ScrapeRequest):
    loop = asyncio.get_event_loop()
    scraper = YtdlpScraper(
        include_comments=request.include_comments,
        include_subtitles=request.include_transcript
    )
    result = await loop.run_in_executor(executor, scraper.scrape, request.url)
    return result


@app.post("/api/scrape/youtube-api", response_model=ScraperResult)
async def scrape_with_youtube_api(request: ScrapeRequest):
    loop = asyncio.get_event_loop()
    scraper = YouTubeAPIScraper()

    def run_scrape():
        return scraper.scrape(request.url, include_comments=request.include_comments)

    result = await loop.run_in_executor(executor, run_scrape)
    return result


@app.post("/api/scrape/transcript", response_model=ScraperResult)
async def scrape_transcript(request: ScrapeRequest):
    loop = asyncio.get_event_loop()
    scraper = TranscriptScraper()
    result = await loop.run_in_executor(executor, scraper.scrape, request.url)
    return result


@app.post("/api/scrape/compare", response_model=ComparisonResult)
async def compare_scrapers(request: ScrapeRequest):
    loop = asyncio.get_event_loop()

    ytdlp_scraper = YtdlpScraper(
        include_comments=request.include_comments,
        include_subtitles=request.include_transcript
    )
    api_scraper = YouTubeAPIScraper()
    transcript_scraper = TranscriptScraper()

    ytdlp_future = loop.run_in_executor(executor, ytdlp_scraper.scrape, request.url)
    api_future = loop.run_in_executor(
        executor,
        lambda: api_scraper.scrape(request.url, include_comments=request.include_comments)
    )
    transcript_future = loop.run_in_executor(executor, transcript_scraper.scrape, request.url)

    results = await asyncio.gather(ytdlp_future, api_future, transcript_future)

    comparison_summary = generate_comparison_summary(results)

    return ComparisonResult(
        video_url=request.url,
        results=list(results),
        comparison_summary=comparison_summary
    )


def generate_comparison_summary(results: list[ScraperResult]) -> dict:
    summary = {
        "methods_succeeded": [],
        "methods_failed": [],
        "field_comparison": {},
        "best_for": {},
        "total_unique_fields": 0
    }

    for result in results:
        if result.success:
            summary["methods_succeeded"].append(result.method)
        else:
            summary["methods_failed"].append({
                "method": result.method,
                "error": result.error
            })

    field_availability = {
        "title": {},
        "description": {},
        "view_count": {},
        "like_count": {},
        "comment_count": {},
        "transcript": {},
        "chapters": {},
        "tags": {},
        "thumbnails": {},
        "channel_subscribers": {},
        "technical_details": {},
        "comments": {}
    }

    for result in results:
        if not result.success or not result.data:
            continue

        method = result.method
        data = result.data

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
            has_technical = any([
                data.technical.fps is not None,
                data.technical.video_codec is not None,
                data.technical.bitrate is not None
            ])
            field_availability["technical_details"][method] = has_technical

        field_availability["comments"][method] = len(data.comments) > 0

    summary["field_comparison"] = field_availability

    best_for = {}

    for result in results:
        if result.success and result.data:
            if len(result.data.transcript) > 0:
                if "transcript" not in best_for or \
                   len(result.data.transcript) > best_for["transcript"]["count"]:
                    best_for["transcript"] = {
                        "method": result.method,
                        "count": len(result.data.transcript)
                    }

            if result.data.technical and result.data.technical.fps is not None:
                best_for["technical_details"] = {"method": result.method}

            if result.data.classification and len(result.data.classification.tags) > 0:
                if "tags" not in best_for or \
                   len(result.data.classification.tags) > best_for["tags"]["count"]:
                    best_for["tags"] = {
                        "method": result.method,
                        "count": len(result.data.classification.tags)
                    }

    summary["best_for"] = best_for

    unique_fields = set()
    for field, methods in field_availability.items():
        if any(methods.values()):
            unique_fields.add(field)
    summary["total_unique_fields"] = len(unique_fields)

    return summary


@app.get("/api/transcript/text")
async def get_transcript_text(
    url: str = Query(..., description="YouTube video URL"),
    include_timestamps: bool = Query(False, description="Include timestamps in output")
):
    loop = asyncio.get_event_loop()
    scraper = TranscriptScraper()

    result = await loop.run_in_executor(
        executor,
        lambda: scraper.get_transcript_text(url, include_timestamps=include_timestamps)
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
