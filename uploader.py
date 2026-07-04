"""
YouTube uploader for RoarRhythm.
Uses OAuth2 refresh token — no browser interaction needed.
"""

import os
import time
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError


def get_youtube():
    creds = Credentials(
        token=None,
        refresh_token=os.environ['YT_REFRESH_TOKEN'],
        client_id=os.environ['YT_CLIENT_ID'],
        client_secret=os.environ['YT_CLIENT_SECRET'],
        token_uri='https://oauth2.googleapis.com/token',
        scopes=[
            'https://www.googleapis.com/auth/youtube.upload',
            'https://www.googleapis.com/auth/youtube',
            'https://www.googleapis.com/auth/yt-analytics.readonly',
        ]
    )
    creds.refresh(Request())
    return build('youtube', 'v3', credentials=creds)


def upload_video(youtube, video_path, title, description, tags,
                 category_id='15', is_short=False, privacy='public'):
    """Upload a video and return its ID."""
    print(f"\nUploading: {title[:60]}...")
    print(f"  File: {Path(video_path).name} ({Path(video_path).stat().st_size/1e6:.1f}MB)")

    # Add #Shorts to title/description for shorts
    if is_short and '#Shorts' not in title:
        title = title + ' #Shorts' if len(title) < 90 else title

    body = {
        'snippet': {
            'title': title[:100],
            'description': description,
            'tags': tags[:500] if isinstance(tags, list) else tags,
            'categoryId': category_id,
            'defaultLanguage': 'en',
        },
        'status': {
            'privacyStatus': privacy,
            'selfDeclaredMadeForKids': False,
            'madeForKids': False,
        }
    }

    media = MediaFileUpload(
        video_path,
        mimetype='video/mp4',
        resumable=True,
        chunksize=10 * 1024 * 1024  # 10MB chunks
    )

    request = youtube.videos().insert(
        part='snippet,status',
        body=body,
        media_body=media
    )

    response = None
    retry = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                print(f"  Upload progress: {pct}%", end='\r')
        except HttpError as e:
            if e.resp.status in [500, 502, 503, 504] and retry < 5:
                retry += 1
                wait = 2 ** retry
                print(f"  Retrying in {wait}s (attempt {retry})...")
                time.sleep(wait)
            else:
                raise

    video_id = response['id']
    url = f"https://youtu.be/{video_id}"
    print(f"\n  ✅ Uploaded: {url}")
    return video_id, url


def get_channel_stats(youtube):
    """Get basic channel statistics."""
    try:
        resp = youtube.channels().list(
            part='statistics,snippet',
            mine=True
        ).execute()
        items = resp.get('items', [])
        if items:
            stats = items[0].get('statistics', {})
            snippet = items[0].get('snippet', {})
            return {
                'name': snippet.get('title', 'RoarRhythm'),
                'subscribers': int(stats.get('subscriberCount', 0)),
                'total_views': int(stats.get('viewCount', 0)),
                'video_count': int(stats.get('videoCount', 0)),
            }
    except Exception as e:
        print(f"Could not get channel stats: {e}")
    return {}


def get_video_stats(youtube, video_id):
    """Get stats for a specific video."""
    try:
        resp = youtube.videos().list(
            part='statistics',
            id=video_id
        ).execute()
        items = resp.get('items', [])
        if items:
            stats = items[0].get('statistics', {})
            return {
                'views': int(stats.get('viewCount', 0)),
                'likes': int(stats.get('likeCount', 0)),
                'comments': int(stats.get('commentCount', 0)),
            }
    except Exception as e:
        print(f"Could not get video stats: {e}")
    return {}
