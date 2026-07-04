"""
RoarRhythm Daily Automation — Main Entry Point
Runs in GitHub Actions. No browser, no Drive mount needed.
"""

import sys
import traceback
from topics import get_today_topic
from producer import setup, produce_main, produce_shorts, cleanup
from uploader import get_youtube, upload_video, get_channel_stats
from reporter import report_success, report_error


def main():
    topic = get_today_topic()
    print(f"\n{'='*50}")
    print(f"RoarRhythm Daily — Topic: {topic['name']}")
    print('='*50)

    try:
        # 1. Setup
        setup()

        # 2. Produce videos
        main_path, norm_paths = produce_main(topic)
        short1_path, short2_path = produce_shorts(topic, norm_paths)

        # 3. Upload to YouTube
        print("\n=== UPLOADING TO YOUTUBE ===")
        youtube = get_youtube()

        main_id, main_url = upload_video(
            youtube, main_path,
            title=topic['title_main'],
            description=topic['description_main'],
            tags=topic['tags'],
            category_id=topic['category_id'],
            is_short=False
        )

        short1_id, short1_url = upload_video(
            youtube, short1_path,
            title=topic['title_short1'],
            description=topic['description_short1'],
            tags=topic['tags'],
            category_id=topic['category_id'],
            is_short=True
        )

        short2_id, short2_url = upload_video(
            youtube, short2_path,
            title=topic['title_short2'],
            description=topic['description_short2'],
            tags=topic['tags'],
            category_id=topic['category_id'],
            is_short=True
        )

        # 4. Get channel stats
        channel_stats = get_channel_stats(youtube)

        # 5. Send Telegram report
        report_success(topic['name'], main_url, short1_url, short2_url, channel_stats)

        # 6. Cleanup temp files
        cleanup()

        print(f"\n{'='*50}")
        print(f"SUCCESS! All 3 videos uploaded for: {topic['name']}")
        print(f"  Main:    {main_url}")
        print(f"  Short 1: {short1_url}")
        print(f"  Short 2: {short2_url}")
        print('='*50)

    except Exception as e:
        error = traceback.format_exc()
        print(f"\nFATAL ERROR: {e}")
        print(error)
        report_error(f"{topic['name']}: {e}\n\n{error[-600:]}")
        cleanup()
        sys.exit(1)


if __name__ == '__main__':
    main()
