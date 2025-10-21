from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import time
import traceback
from urllib.parse import urlparse

app = Flask(__name__)

# Use Render's ephemeral storage
DOWNLOAD_FOLDER = "/tmp/downloads"

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
            'Accept-Language': 'en-us,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        },
        'outtmpl': f'{DOWNLOAD_FOLDER}/%(title).100s.%(ext)s',
    }
    
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
        # Use minimal options to avoid encoding issues
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'ignoreerrors': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                return {'error': 'No video information found'}
            
            # Get available formats
            formats = info.get("formats", [])
            resolutions = []
            
            for fmt in formats:
                height = fmt.get('height')
                if height and height >= 144:
                    resolutions.append(height)
            
            resolutions = sorted(set(resolutions), reverse=True)
            
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
        print(f"YouTube DownloadError: {error_msg}")
        
        if 'Private video' in error_msg:
            return {'error': 'This video is private and cannot be accessed'}
        elif 'Members-only' in error_msg:
            return {'error': 'This is a members-only video'}
        elif 'Sign in' in error_msg or 'login' in error_msg.lower():
            return {'error': 'YouTube is requiring login. Try a different video.'}
        elif 'Video unavailable' in error_msg:
            return {'error': 'This video is unavailable or has been removed'}
        elif 'Too Many Requests' in error_msg or '429' in error_msg:
            return {'error': 'YouTube is blocking requests due to rate limiting. Please try again later.'}
        elif 'Unsupported URL' in error_msg:
            return {'error': 'Unsupported URL or invalid YouTube link'}
        else:
            return {'error': 'Could not access this video. Please try a different one.'}
            
    except Exception as e:
        error_msg = str(e)
        print(f"Unexpected error in get_video_info: {error_msg}")
        return {'error': 'Failed to fetch video information. Please try again.'}

def get_video_info_with_retry(url, max_retries=2):
    """Get video info with retry logic"""
    for attempt in range(max_retries):
        try:
            result = get_video_info(url)
            if 'error' not in result:
                return result
            print(f"Attempt {attempt + 1} failed: {result.get('error')}")
        except Exception as e:
            print(f"Attempt {attempt + 1} failed with exception: {e}")
        
        if attempt < max_retries - 1:
            time.sleep(1)
    
    return {'error': 'Could not fetch video information. Please try a different video.'}

def download_video(url, resolution):
    """Download video with specified resolution"""
    try:
        ydl_opts = build_ydl_opts({
            'format': f'best[height<={resolution}]/best',
            'merge_output_format': 'mp4'
        })
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if not filename.endswith('.mp4'):
                filename = os.path.splitext(filename)[0] + '.mp4'
            print(f"Video downloaded to: {filename}")
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
            mp3_path = os.path.splitext(base_path)[0] + '.mp3'
            print(f"Audio downloaded to: {mp3_path}")
            return mp3_path
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
    
    info = get_video_info_with_retry(url)
    print(f"Returning info: {'Success' if 'error' not in info else 'Error'}")
    
    return jsonify(info), 200

@app.route('/download', methods=['POST'])
def download():
    url = request.form.get('url', '').strip()
    quality = request.form.get('quality', '').strip()
    
    print(f"Download request - URL: {url}, Quality: {quality}")
    
    if not url or not quality:
        return "Missing URL or quality", 400
    
    try:
        if quality == 'mp3':
            file_path = download_audio(url)
        else:
            file_path = download_video(url, quality)
        
        safe_filename = os.path.basename(file_path)
        print(f"Sending file: {safe_filename}")
        
        return send_file(
            file_path, 
            as_attachment=True,
            download_name=safe_filename
        )
        
    except Exception as e:
        print(f"Download error: {e}")
        return f"Download failed: {str(e)}", 500

@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy', 
        'message': 'Server is running',
        'timestamp': time.time()
    })

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"Starting server on port {port}")
    print(f"Download folder: {DOWNLOAD_FOLDER}")
    app.run(host="0.0.0.0", port=port, debug=False)
