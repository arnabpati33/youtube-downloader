from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import base64
import stat
import traceback
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
        valid_domains = ['youtube.com', 'youtu.be', 'www.youtube.com', 'm.youtube.com']
        return any(domain in parsed.netloc for domain in valid_domains)
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
    """Return a yt-dlp options dict with better headers."""
    opts = {
        'quiet': False,  # Set to False to see more info
        'no_warnings': False,
        'noplaylist': True,
        'ignoreerrors': False,
        'extract_flat': False,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-us,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7',
            'Connection': 'keep-alive',
        },
        'outtmpl': f'{DOWNLOAD_FOLDER}/%(title).100s.%(ext)s',
    }
    if os.path.exists(COOKIE_PATH):
        opts['cookiefile'] = COOKIE_PATH
        print("Using cookies file for authentication")
    
    if extra:
        opts.update(extra)
    return opts

def get_video_info(url):
    """Get video information with comprehensive error handling"""
    print(f"Fetching info for URL: {url}")
    
    if not url or not url.strip():
        return {'error': 'No URL provided'}
    
    if not is_valid_youtube_url(url):
        return {'error': 'Invalid YouTube URL. Please use a valid YouTube link.'}
    
    try:
        ydl_opts = build_ydl_opts({
            'skip_download': True,
            'force_json': True,
        })
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Test if we can extract info
            info = ydl.extract_info(url, download=False)
            print(f"Successfully extracted info for: {info.get('title', 'Unknown')}")
            
            # Get available formats
            formats = info.get("formats", [])
            print(f"Found {len(formats)} formats")
            
            # Extract unique resolutions
            video_formats = [f for f in formats if f.get('vcodec') != 'none']
            resolutions = sorted(
                {f.get("height") for f in video_formats if f.get("height") and f.get("height") >= 144},
                reverse=True
            )
            
            result = {
                'title': info.get('title', 'Unknown Title'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0),
                'resolutions': [str(r) + "p" for r in resolutions] + ['mp3'],
                'uploader': info.get('uploader', 'Unknown'),
                'view_count': info.get('view_count', 0),
                'description': info.get('description', '')[:100] + '...' if info.get('description') else ''
            }
            
            print(f"Returning info with {len(result['resolutions'])} quality options")
            return result
            
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        print(f"YouTube DownloadError: {error_msg}")
        
        if 'Private video' in error_msg:
            return {'error': 'This video is private and cannot be accessed'}
        elif 'Members-only' in error_msg:
            return {'error': 'This is a members-only video'}
        elif 'Sign in' in error_msg or 'login' in error_msg.lower():
            return {'error': 'YouTube is requiring login. This server needs authentication cookies to access this video.'}
        elif 'Video unavailable' in error_msg:
            return {'error': 'This video is unavailable or has been removed'}
        elif 'Too Many Requests' in error_msg or '429' in error_msg:
            return {'error': 'YouTube is blocking requests due to rate limiting. Please try again later.'}
        elif 'Unsupported URL' in error_msg:
            return {'error': 'Unsupported URL or invalid YouTube link'}
        else:
            return {'error': f'YouTube error: {error_msg}'}
            
    except yt_dlp.utils.ExtractorError as e:
        error_msg = str(e)
        print(f"ExtractorError: {error_msg}")
        return {'error': 'Failed to extract video information. The video might be restricted.'}
        
    except Exception as e:
        error_msg = str(e)
        print(f"Unexpected error in get_video_info: {error_msg}")
        print(traceback.format_exc())
        return {'error': 'Failed to fetch video information. Please check the URL and try again.'}

def download_video(url, resolution):
    """Download video with specified resolution"""
    try:
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
    except Exception as e:
        print(f"Error in download_video: {e}")
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
        print(f"Error in download_audio: {e}")
        raise

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_formats', methods=['POST'])
def get_formats():
    url = request.form.get('url', '').strip()
    print(f"Received request for URL: {url}")
    
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    
    info = get_video_info(url)
    print(f"Returning info: {info}")
    
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
        print(traceback.format_exc())
        return f"Download failed: {str(e)}", 500

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy', 'message': 'Server is running'})

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"Starting server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
