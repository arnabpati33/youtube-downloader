from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import base64
import stat
import time
from urllib.parse import urlparse

app = Flask(__name__)

# Use Render's ephemeral storage
DOWNLOAD_FOLDER = "/tmp/downloads"
COOKIE_PATH = "/tmp/youtube.com_cookies.txt"
COOKIES_ENV_NAME = "YOUTUBE_COOKIES_B64"

# Create downloads folder if it doesn't exist
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

def is_valid_youtube_url(url):
    """Validate YouTube URL"""
    try:
        parsed = urlparse(url)
        return any(domain in parsed.netloc for domain in ['youtube.com', 'youtu.be'])
    except Exception:
        return False

def write_cookiefile_from_env():
    """If YOUTUBE_COOKIES_B64 exists in env, decode and write binary cookie file."""
    b64 = os.environ.get(COOKIES_ENV_NAME)
    if not b64:
        print("No YOUTUBE_COOKIES_B64 env var found — cookie file will not be written.")
        return False
    try:
        data = base64.b64decode(b64)
        with open(COOKIE_PATH, "wb") as f:
            f.write(data)
        try:
            os.chmod(COOKIE_PATH, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            pass
        print(f"Wrote cookie file to {COOKIE_PATH}")
        return True
    except Exception as e:
        print("Failed to write cookie file from env:", e)
        return False

# Write cookie file on startup
write_cookiefile_from_env()

def build_ydl_opts(extra=None):
    """Return a yt-dlp options dict."""
    opts = {
        'quiet': True,
        'no_warnings': False,
        'noplaylist': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'outtmpl': f'{DOWNLOAD_FOLDER}/%(title).100s.%(ext)s',
    }
    if os.path.exists(COOKIE_PATH):
        opts['cookiefile'] = COOKIE_PATH
    if extra:
        opts.update(extra)
    return opts

def get_video_info(url):
    """Get video information with better error handling"""
    if not is_valid_youtube_url(url):
        return {'error': 'Invalid YouTube URL'}
    
    try:
        ydl_opts = build_ydl_opts({'skip_download': True})
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        formats = info.get("formats", [])
        resolutions = sorted(
            {f.get("height") for f in formats if f.get("height") and f.get("height") >= 144},
            reverse=True
        )
        
        return {
            'title': info.get('title', 'Unknown Title'),
            'thumbnail': info.get('thumbnail', ''),
            'duration': info.get('duration', 0),
            'resolutions': [str(r) + "p" for r in resolutions] + ['mp3'],
            'uploader': info.get('uploader', 'Unknown'),
            'view_count': info.get('view_count', 0)
        }
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        if 'Private video' in error_msg:
            return {'error': 'This video is private and cannot be downloaded'}
        elif 'Members-only' in error_msg:
            return {'error': 'This is a members-only video'}
        elif 'Sign in' in error_msg:
            return {'error': 'blocked', 'message': 'YouTube is blocking requests. Consider adding cookies.'}
        else:
            return {'error': f'YouTube error: {error_msg}'}
    except Exception as e:
        print(f"Unexpected error in get_video_info: {e}")
        return {'error': 'Failed to fetch video information'}

def download_video(url, resolution):
    """Download video with specified resolution"""
    ydl_opts = build_ydl_opts({
        'format': f'bestvideo[height<={resolution}]+bestaudio/best[height<={resolution}]',
        'merge_output_format': 'mp4'
    })
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        if not filename.endswith('.mp4'):
            filename = os.path.splitext(filename)[0] + '.mp4'
        return filename

def download_audio(url):
    """Download audio as MP3"""
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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_formats', methods=['POST'])
def get_formats():
    url = request.form.get('url', '').strip()
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    
    info = get_video_info(url)
    if 'error' in info:
        return jsonify(info), 200
    
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
        return send_file(
            file_path, 
            as_attachment=True,
            download_name=safe_filename
        )
        
    except Exception as e:
        print(f"Download error: {e}")
        return f"Download failed: {str(e)}", 500

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
