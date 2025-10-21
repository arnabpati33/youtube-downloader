from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import base64
import time
import traceback
from urllib.parse import urlparse

app = Flask(__name__)

DOWNLOAD_FOLDER = "/tmp/downloads"
COOKIE_PATH = "/tmp/cookies.txt"

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

def setup_cookies():
    """Setup cookies from environment variable"""
    cookies_b64 = os.environ.get("YOUTUBE_COOKIES")
    if not cookies_b64:
        print("No cookies provided - some videos may not work")
        return False
    
    try:
        # Decode base64 cookies
        cookies_text = base64.b64decode(cookies_b64).decode('utf-8')
        
        # Write to file
        with open(COOKIE_PATH, 'w', encoding='utf-8') as f:
            f.write(cookies_text)
        
        print("Cookies setup successfully")
        return True
    except Exception as e:
        print(f"Failed to setup cookies: {e}")
        return False

# Setup cookies on startup
setup_cookies()

def is_valid_youtube_url(url):
    """Validate YouTube URL"""
    try:
        parsed = urlparse(url)
        valid_domains = ['youtube.com', 'youtu.be', 'www.youtube.com', 'm.youtube.com']
        return any(domain in parsed.netloc for domain in valid_domains)
    except Exception:
        return False

def build_ydl_opts(extra=None):
    """Return a yt-dlp options dict."""
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'ignoreerrors': False,
        'extract_flat': False,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
        },
        'outtmpl': f'{DOWNLOAD_FOLDER}/%(title).100s.%(ext)s',
    }
    
    # Add cookies if available
    if os.path.exists(COOKIE_PATH):
        opts['cookiefile'] = COOKIE_PATH
        print("Using cookies for authentication")
    
    if extra:
        opts.update(extra)
    return opts

def get_video_info(url):
    """Get video information"""
    print(f"Fetching info for URL: {url}")
    
    if not url or not url.strip():
        return {'error': 'No URL provided'}
    
    if not is_valid_youtube_url(url):
        return {'error': 'Invalid YouTube URL'}
    
    try:
        ydl_opts = build_ydl_opts({'skip_download': True})
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                return {'error': 'Video not found'}
            
            # Get available formats
            formats = info.get("formats", [])
            video_formats = [f for f in formats if f.get('vcodec') != 'none']
            resolutions = sorted(
                {f.get("height") for f in video_formats if f.get("height") and f.get("height") >= 144},
                reverse=True
            )
            
            # Format duration
            duration = info.get('duration', 0)
            if duration:
                minutes = duration // 60
                seconds = duration % 60
                duration_str = f"{minutes}:{seconds:02d}"
            else:
                duration_str = "Unknown"
            
            return {
                'title': info.get('title', 'Unknown Title'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': duration_str,
                'duration_seconds': duration,
                'resolutions': [str(r) + "p" for r in resolutions] + ['mp3'],
                'uploader': info.get('uploader', 'Unknown'),
                'view_count': info.get('view_count', 0),
            }
            
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        print(f"YouTube error: {error_msg}")
        
        if 'Sign in' in error_msg or 'bot' in error_msg:
            return {'error': 'blocked', 'message': 'YouTube is blocking this request. The server needs valid YouTube cookies to access videos.'}
        elif 'Private video' in error_msg:
            return {'error': 'This video is private'}
        elif 'Video unavailable' in error_msg:
            return {'error': 'Video unavailable'}
        else:
            return {'error': 'YouTube blocked the request'}
            
    except Exception as e:
        print(f"Unexpected error: {e}")
        return {'error': 'Failed to fetch video information'}

def download_video(url, resolution):
    """Download video with specified resolution"""
    try:
        ydl_opts = build_ydl_opts({
            'format': f'best[height<={resolution}]',
            'merge_output_format': 'mp4'
        })
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            return filename
    except Exception as e:
        print(f"Download error: {e}")
        raise

def download_audio(url):
    """Download audio as MP3"""
    try:
        ydl_opts = build_ydl_opts({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            base_path = ydl.prepare_filename(info)
            return os.path.splitext(base_path)[0] + '.mp3'
    except Exception as e:
        print(f"Audio download error: {e}")
        raise

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_formats', methods=['POST'])
def get_formats():
    url = request.form.get('url', '').strip()
    
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    
    info = get_video_info(url)
    return jsonify(info), 200

@app.route('/download', methods=['POST'])
def download():
    url = request.form.get('url', '').strip()
    quality = request.form.get('quality', '').strip()
    
    if not url or not quality:
        return "Missing URL or quality", 400
    
    try:
        if quality == 'mp3':
            file_path = download_audio(url)
        else:
            file_path = download_video(url, quality)
        
        safe_filename = os.path.basename(file_path)
        return send_file(file_path, as_attachment=True, download_name=safe_filename)
        
    except Exception as e:
        print(f"Download failed: {e}")
        return f"Download failed: {str(e)}", 500

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy'})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
