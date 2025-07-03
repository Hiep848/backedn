import os
import json
from cachetools import TTLCache, cached
from flask import Flask, jsonify, Response, stream_with_context, request
from ytmusicapi import YTMusic
import yt_dlp
import logging
import requests
from flask_cors import CORS
from datetime import datetime, timedelta
import hashlib

# Thống nhất trong các object "songs" các thuộc tính (properties) là:
# "artist": "Alex Warren",
# "duration": "3:07",
# "thumbnail_url": "https://i.ytimg.com/vi/u2ah9tWTkmk/sddefault.jpg?sqp=-oaymwEWCJADEOEBIAQqCghqEJQEGHgg6AJIWg&rs=AMzJL3me2eNS4hDgHGyO2U9dQYnLc4wZjQ",
# "title": "Ordinary",
# "video_id": "u2ah9tWTkmk"
stream_cache = TTLCache(maxsize=1024, ttl=3600)
IMAGE_CACHE_DIR = os.path.join('static', 'images')
os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)
CACHE_FILENAME_TRENDING = "trending_cache.json"
CACHE_FILENAME_ARTISTS = 'popular_artists_cache.json'
ARTIST_DETAIL_CACHE_FOLDER = 'artist_details_cache'
CACHE_FILENAME_MADE_FOR_YOU = 'made_for_you_cache.json'
PLAYLIST_DETAIL_CACHE_FOLDER = 'playlist_details_cache'
CACHE_DURATION_HOURS = 1000 # 15 days
ARTIST_IMAGE_FOLDER = 'static/artists'
DOWNLOAD_FOLDER = 'temp_downloads'
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)
baseUrl = 'http://127.0.0.1:5000'

MADE_FOR_YOU_PLAYLISTS_IDS = [
    'PLpY7hx7jry7zc4zspi_fBhWQt8z5jrJ8z', # Top Vietnamese Hits
    'PLhNyfL3WbvS3RpbQm1eMWFLPEu6BcY166', # Top Most Streaming Songs
    'PLRhunSKoxxzZjPu8cvOUCgd-I3pP1M8A9', # Top US-UK Songs
    'PLO_1AmtK1TMRi01-V_tdHKDLBu7cNWIgf', # Top Classical Songs
    'PL15B1E77BB5708555'  # Most View Songs of All Time
]

yt = YTMusic('headers_auth.json')
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes
logging.basicConfig(level=logging.INFO)

# Store trending songs data in memory (since we can't use localStorage)
trending_songs_cache = []



# Hàm search
def _parse_search_result_item(item):
    """
    Hàm này nhận một mục từ kết quả tìm kiếm và định dạng lại nó.
    """
    result_type = item.get('resultType')
    parsed_item = None

    if result_type == 'song':
        # Logic parse bài hát từ kết quả tìm kiếm
        # Nó gần giống với hàm _parse_song_from_ytmusic nhưng độc lập
        original_thumbnail_url = item["thumbnails"][-1].get("url", "") if item.get("thumbnails") else ""
        local_thumbnail_path = download_and_save_image(original_thumbnail_url, item.get("videoId", ""))
        artists = item.get("artists", [])
        artist_names = ", ".join([artist.get("name", "") for artist in artists])

        parsed_item = {
            'type': 'song',
            'video_id': item.get("videoId", ""),
            'title': item.get("title", "Unknown Title"),
            'artist': artist_names or "Unknown Artist",
            'thumbnail_url': f"{baseUrl}{local_thumbnail_path}" if local_thumbnail_path else "",
            'duration': item.get("duration", "N/A")
        }

    elif result_type == 'artist':
        channel_id = item.get('browseId')
        
        # 2. CHỈ xử lý nếu channelId tồn tại và không rỗng
        if channel_id:
            original_thumbnail_url = item['thumbnails'][-1]['url'] if item.get('thumbnails') else ''
            local_thumbnail_path = download_and_save_image(original_thumbnail_url, channel_id)
            parsed_item = {
                'type': 'artist',
                'artistName': item.get('artist'),
                'channelId': channel_id, # Đảm bảo không bao giờ là null
                'thumbnailUrl': f"{baseUrl}{local_thumbnail_path}" if local_thumbnail_path else ""
            }

    elif result_type == 'playlist':
        original_thumbnail_url = item['thumbnails'][-1]['url'] if item.get('thumbnails') else ''
        local_thumbnail_path = download_and_save_image(original_thumbnail_url, item.get('browseId', ''))
        parsed_item = {
            'type': 'playlist',
            'playlistName': item.get('title'),
            'playlistId': item.get('browseId'),
            'author': item.get('author'),
            'itemCount': item.get('itemCount'),
            'thumbnailUrl': f"{baseUrl}{local_thumbnail_path}" if local_thumbnail_path else ""
        }
    
    return parsed_item

@app.route('/api/search', methods=['GET'])
def search_all():
    query = request.args.get('q', '')
    if not query or not yt:
        return jsonify({'results': []})

    try:
        print(f"\nĐang thực hiện tìm kiếm thông minh cho: '{query}'")
        # Thực hiện 3 tìm kiếm riêng biệt
        artist_results = yt.search(query, filter='artists', limit=3)
        song_results = yt.search(query, filter='songs', limit=5)
        playlist_results = yt.search(query, filter='playlists', limit=3)

        final_results = []

        # Ưu tiên kết quả nghệ sĩ
        if artist_results:
            print(f"-> Tìm thấy {len(artist_results)} kết quả nghệ sĩ.")
            for item in artist_results:
                parsed_item = _parse_search_result_item(item)
                if parsed_item: final_results.append(parsed_item)

        # Thêm kết quả bài hát
        if song_results:
            print(f"-> Tìm thấy {len(song_results)} kết quả bài hát.")
            for item in song_results:
                parsed_item = _parse_search_result_item(item)
                if parsed_item: final_results.append(parsed_item)
        
        # Thêm kết quả playlist
        if playlist_results:
            print(f"-> Tìm thấy {len(playlist_results)} kết quả playlist.")
            for item in playlist_results:
                parsed_item = _parse_search_result_item(item)
                if parsed_item: final_results.append(parsed_item)
        
        print("--- Tìm kiếm hoàn tất ---")
        return Response(json.dumps({'results': final_results}, ensure_ascii=False), mimetype='application/json')

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f"Lỗi khi tìm kiếm: {str(e)}"}), 500


# Các hàm tạo playlist 
@app.route('/api/made_for_you', methods=['GET'])
def get_made_for_you_playlists():
    """
    Lấy danh sách các playlist "Made for You", sử dụng cache.
    """
    # 1. Kiểm tra file cache
    if os.path.exists(CACHE_FILENAME_MADE_FOR_YOU):
        last_modified_time = datetime.fromtimestamp(os.path.getmtime(CACHE_FILENAME_MADE_FOR_YOU))
        if datetime.now() - last_modified_time < timedelta(hours=CACHE_DURATION_HOURS):
            print("Đang trả về playlist 'Made for You' từ CACHE.")
            try:
                with open(CACHE_FILENAME_MADE_FOR_YOU, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                    return Response(json.dumps(cached_data, ensure_ascii=False), mimetype='application/json')
            except (IOError, json.JSONDecodeError) as e:
                print(f"Lỗi khi đọc file cache 'Made for You': {e}")

    # 2. Nếu cache không hợp lệ, lấy dữ liệu mới
    print("Cache 'Made for You' không hợp lệ. Đang lấy dữ liệu mới từ API...")
    try:
        playlists_details = []
        for playlist_id in MADE_FOR_YOU_PLAYLISTS_IDS:
            try:
                # Lấy thông tin chi tiết của từng playlist
                playlist_data = yt.get_playlist(playlistId=playlist_id, limit=5) # chỉ cần limit=1 để lấy thông tin playlist
                
                thumbnail_url = ""
                if playlist_data.get('thumbnails'):
                    thumbnail_url = playlist_data['thumbnails'][-1]['url']
                
                playlists_details.append({
                    'id': playlist_data.get('id'),
                    'title': playlist_data.get('title'),
                    'description': playlist_data.get('description'),
                    'thumbnail_url': thumbnail_url,
                    'trackCount': playlist_data.get('trackCount')
                })
                print(f"-> Lấy thành công thông tin playlist: {playlist_data.get('title')}")
            except Exception as e:
                print(f"Lỗi khi lấy playlist ID {playlist_id}: {e}")
                continue # Bỏ qua playlist này nếu có lỗi

        result = {'playlists': playlists_details}

        # 3. Lưu dữ liệu mới vào file cache
        try:
            with open(CACHE_FILENAME_MADE_FOR_YOU, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=4)
            print(f"Saved new 'Made for You' cache to '{CACHE_FILENAME_MADE_FOR_YOU}'.")
        except IOError as e:
            print(f"Error writing to 'Made for You' cache file: {e}")

        return Response(json.dumps(result, ensure_ascii=False), mimetype='application/json')

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f"An error occurred while fetching 'Made for You' playlists: {str(e)}"}), 500

@app.route('/api/playlist/<playlist_id>', methods=['GET'])
def get_playlist_details(playlist_id):
    """
    Lấy thông tin chi tiết của một playlist, bao gồm danh sách bài hát.
    Sử dụng cơ chế cache.
    """
    os.makedirs(PLAYLIST_DETAIL_CACHE_FOLDER, exist_ok=True)
    cache_filepath = os.path.join(PLAYLIST_DETAIL_CACHE_FOLDER, f"{playlist_id}.json")

    # 1. Kiểm tra cache
    if os.path.exists(cache_filepath):
        last_modified_time = datetime.fromtimestamp(os.path.getmtime(cache_filepath))
        if datetime.now() - last_modified_time < timedelta(hours=CACHE_DURATION_HOURS):
            print(f"Trả về chi tiết playlist '{playlist_id}' từ CACHE.")
            try:
                with open(cache_filepath, 'r', encoding='utf-8') as f:
                    return Response(f.read(), mimetype='application/json')
            except Exception as e:
                print(f"Lỗi đọc file cache playlist: {e}")

    print(f"Cache cho playlist '{playlist_id}' không hợp lệ. Lấy dữ liệu mới...")
    try:
        # 2. Lấy dữ liệu từ API, không giới hạn số bài hát (hoặc mặc định 100)
        playlist_data = yt.get_playlist(playlistId=playlist_id, limit = 30)

        # Trích xuất thông tin playlist
        thumbnail_url = playlist_data.get('thumbnails', [])[-1]['url'] if playlist_data.get('thumbnails') else ""

        # Trích xuất và định dạng lại danh sách bài hát
        songs = []
        for track in playlist_data.get('tracks', []):
            artists = track.get("artists", [])
            artist_names = ", ".join(artist.get("name", "Unknown") for artist in artists) if artists else "Unknown Artist"
            track_thumbnail = track.get('thumbnails', [])[-1]['url'] if track.get('thumbnails') else ""
            
            songs.append({
                "title": track.get("title", "Unknown Title"),
                "artist": artist_names,
                "duration": track.get("duration", "N/A"),
                "video_id": track.get("videoId", ""),
                "thumbnail_url": track_thumbnail
            })

        result = {
            'id': playlist_data.get('id'),
            'title': playlist_data.get('title'),
            'description': playlist_data.get('description'),
            'thumbnail_url': thumbnail_url,
            'songs': songs
        }

        # 3. Lưu vào cache
        with open(cache_filepath, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=4)
        
        return Response(json.dumps(result, ensure_ascii=False), mimetype='application/json')

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f"Lỗi khi lấy chi tiết playlist: {str(e)}"}), 500


# Hàm lấy thông tin nghệ sĩ từ Channel ID
# trong file app.py
# Hàm phụ để xử lý định dạng bài hát từ ytmusicapi
def _parse_song_from_ytmusic(song_data, artist_name):
    """Hàm này lấy dữ liệu thô từ ytmusicapi và chuyển thành định dạng JSON quen thuộc của chúng ta."""
    if not song_data:
        return None
    
    # Lấy thumbnail chất lượng cao nhất
    thumbnail_url = None
    if song_data.get('thumbnails'):
        thumbnail_url = song_data['thumbnails'][-1]['url']
        
    return {
        'video_id': song_data.get("videoId", ""),
        'title': song_data.get("title", "Unknown Title"),
        'artist': ', '.join([artist['name'] for artist in song_data.get('artists', [])]) or artist_name,
        'thumbnail_url': thumbnail_url,
        'duration': song_data.get("duration", "N/A")
    }
@app.route('/image-proxy')
def image_proxy():
    """
    Lấy URL của ảnh từ tham số 'url', tải nó về,
    và trả lại dữ liệu ảnh cho client.
    """
    # Lấy URL ảnh từ query parameter, ví dụ: /image-proxy?url=http://...
    image_url = request.args.get('url')

    if not image_url:
        return jsonify({'error': 'Missing image URL'}), 400

    try:
        # Gửi yêu cầu đến URL ảnh với stream=True để xử lý hiệu quả
        # Thêm header User-Agent để giả dạng một trình duyệt thông thường
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }
        response = requests.get(image_url, stream=True, headers=headers)

        # Kiểm tra xem yêu cầu có thành công không
        if response.status_code == 200:
            # Lấy content-type của ảnh gốc (ví dụ: 'image/jpeg')
            content_type = response.headers.get('content-type')
            # Trả về dữ liệu ảnh thô với đúng content-type
            return Response(response.raw, content_type=content_type)
        else:
            return jsonify({'error': 'Failed to fetch image'}), response.status_code

    except Exception as e:
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500

@app.route('/api/artist/<channel_id>', methods=['GET'])
def get_artist_details(channel_id):
    """
    Lấy thông tin nghệ sĩ và các bài hát hàng đầu bằng ytmusicapi.
    SỬ DỤNG CƠ CHẾ CACHE ĐỂ TỐI ƯU HIỆU NĂNG.
    """
    # Tạo đường dẫn file cache cho nghệ sĩ này
    os.makedirs(ARTIST_DETAIL_CACHE_FOLDER, exist_ok=True)
    cache_filepath = os.path.join(ARTIST_DETAIL_CACHE_FOLDER, f"{channel_id}.json")

    # 1. Kiểm tra xem cache có hợp lệ không
    if os.path.exists(cache_filepath):
        last_modified_time = datetime.fromtimestamp(os.path.getmtime(cache_filepath))
        # Sử dụng cùng CACHE_DURATION_HOURS
        if datetime.now() - last_modified_time < timedelta(hours=CACHE_DURATION_HOURS):
            print(f"Đang trả về chi tiết nghệ sĩ '{channel_id}' từ CACHE.")
            try:
                with open(cache_filepath, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                    return Response(json.dumps(cached_data, ensure_ascii=False), mimetype='application/json')
            except (IOError, json.JSONDecodeError) as e:
                print(f"Lỗi khi đọc file cache của nghệ sĩ, sẽ lấy dữ liệu mới. Lỗi: {e}")

    # 2. Nếu cache không hợp lệ hoặc không tồn tại, lấy dữ liệu mới
    print(f"Cache cho '{channel_id}' không hợp lệ. Đang lấy dữ liệu mới từ API...")
    try:
        ytmusic = YTMusic()
        artist_data = ytmusic.get_artist(channelId=channel_id)

        artist_name = artist_data.get('name')
        artist_thumbnail = artist_data['thumbnails'][-1]['url'] if artist_data.get('thumbnails') else ""
        description = artist_data.get('description')

        songs = []
        if artist_data.get('songs') and artist_data['songs'].get('results'):
            top_songs_data = artist_data['songs']['results']
            for song_item in top_songs_data:
                original_song_thumbnail = song_item["thumbnails"][-1].get("url", "") if song_item.get("thumbnails") else ""
                local_song_thumbnail_path = download_and_save_image(original_song_thumbnail, song_item.get("videoId", ""))

                parsed_song = _parse_song_from_ytmusic(song_item, artist_name=artist_name)
                if parsed_song:
                    parsed_song['thumbnail_url'] = f"{baseUrl}{local_song_thumbnail_path}" if local_song_thumbnail_path else ""
                    songs.append(parsed_song)

        result = {
            'artistName': artist_name,
            'artistThumbnail': artist_thumbnail,
            'description': description,
            'songs': songs
        }

        # 3. Lưu kết quả mới vào file cache
        try:
            with open(cache_filepath, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=4)
            print(f"Đã lưu cache mới cho nghệ sĩ '{channel_id}' vào file.")
        except IOError as e:
            print(f"Lỗi khi ghi file cache cho nghệ sĩ: {e}")

        return Response(json.dumps(result, ensure_ascii=False), mimetype='application/json')

    except Exception as e:
        return jsonify({'error': f"Đã có lỗi xảy ra khi lấy thông tin nghệ sĩ: {str(e)}"}), 500

def download_and_save_image(image_url, artist_name):
    if not image_url:
        return ""

    try:
        # Tạo tên file từ artist name (slug + hash tránh trùng)
        safe_name = "".join(c for c in artist_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        hash_code = hashlib.md5(image_url.encode()).hexdigest()[:8]
        filename = f"{safe_name}_{hash_code}.jpg"
        filepath = os.path.join(ARTIST_IMAGE_FOLDER, filename)

        # Nếu file đã tồn tại, không tải lại
        if os.path.exists(filepath):
            return f"/static/artists/{filename}"

        # Tải ảnh
        response = requests.get(image_url, stream=True, timeout=5)
        if response.status_code == 200:
            os.makedirs(ARTIST_IMAGE_FOLDER, exist_ok=True)
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            print(f"Tải ảnh thành công: {filename}")
            return f"/static/artists/{filename}"
        else:
            print(f"Lỗi khi tải ảnh ({image_url}): {response.status_code}")
            return ""
    except Exception as e:
        print(f"Lỗi khi lưu ảnh cho {artist_name}: {e}")
        return ""

       
@app.route('/api/popular_artists', methods=['GET'])
def get_popular_artists():
    """
    Lấy danh sách nghệ sĩ nổi bật, sử dụng cơ chế cache để tối ưu hiệu năng.
    """
    if not yt:
        return jsonify({'error': 'YTMusic service is not available.'}), 503

    cache_is_valid = False
    
    # 1. Kiểm tra file cache có tồn tại và còn mới không
    if os.path.exists(CACHE_FILENAME_ARTISTS):
        last_modified_time = datetime.fromtimestamp(os.path.getmtime(CACHE_FILENAME_ARTISTS))
        if datetime.now() - last_modified_time < timedelta(hours=CACHE_DURATION_HOURS):
            cache_is_valid = True
            
    # 2. Nếu cache hợp lệ, đọc dữ liệu từ file và trả về
    if cache_is_valid:
        print("Đang trả về dữ liệu từ CACHE...")
        try:
            with open(CACHE_FILENAME_ARTISTS, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
                return Response(json.dumps(cached_data, ensure_ascii=False), mimetype='application/json')
        except (IOError, json.JSONDecodeError) as e:
            print(f"Lỗi khi đọc file cache, sẽ lấy dữ liệu mới. Lỗi: {e}")

    # 3. Nếu không có cache hoặc cache đã cũ, tiến hành gọi API mới
    print("Cache không hợp lệ hoặc không tồn tại. Đang lấy dữ liệu mới từ API...")
    try:
        playlist_id = 'PLXl9q53Jut6nT4VBv_fbd-HLiYmTkih8_'
        playlist_data = yt.get_playlist(playlist_id, limit=50)
        tracks = playlist_data.get('tracks', [])
        
        unique_artist_ids = []
        seen_artist_ids = set()
        for track in tracks:
            if track and 'artists' in track:
                for artist_data in track['artists']:
                    channel_id = artist_data.get('id')
                    if channel_id and channel_id not in seen_artist_ids:
                        seen_artist_ids.add(channel_id)
                        unique_artist_ids.append(channel_id)
                        if len(unique_artist_ids) >= 10:
                            break
            if len(unique_artist_ids) >= 10:
                break
        
        print(f"Found {len(unique_artist_ids)} unique artists. Fetching full details...")

        # Lấy thông tin chi tiết cho từng nghệ sĩ
        popular_artists = []
        for artist_id in unique_artist_ids:
            try:
                artist_details = yt.get_artist(channelId=artist_id)
                
                thumbnail_url = ""
                if artist_details.get('thumbnails'):
                    original_url = artist_details['thumbnails'][-1]['url']
                    thumbnail_url = download_and_save_image(original_url, artist_details.get('name'))
                    print(f"DEBUGGING URL: Artist: {artist_details.get('name')} -- URL: {thumbnail_url}")
                    
                popular_artists.append({
                    'artistName': artist_details.get('name'),
                    'channelId': artist_id,
                    'thumbnailUrl': baseUrl +'/' + thumbnail_url
                })
                print(f"-> Successfully fetched details for artist: {artist_details.get('name')}")
            except Exception as artist_e:
                print(f"Could not fetch full details for artist ID {artist_id}. Skipping. Error: {artist_e}")
                continue # Bỏ qua nghệ sĩ này nếu có lỗi

        result = {'artists': popular_artists}

        # 4. Lưu dữ liệu mới vào file cache để dùng cho lần sau
        try:
            with open(CACHE_FILENAME_ARTISTS, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=4)
            print(f"Saved new artist cache to '{CACHE_FILENAME_ARTISTS}'.")
        except IOError as e:
            print(f"Error writing to cache file: {e}")

        return Response(json.dumps(result, ensure_ascii=False), mimetype='application/json')

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f"An error occurred while fetching the artist list: {str(e)}"}), 500

# Hàm này sẽ được gọi khi người dùng yêu cầu tải một bài hát cụ thể
@app.route('/download/<string:video_id>')

# Sử dụng yt-dlp để lấy URL stream của video YouTube
# Hàm này sẽ được gọi khi người dùng yêu cầu stream một bài hát cụ thể
@cached(stream_cache)
def get_streaming_url(video_id):
    logging.info(f"Fetching stream URL for {video_id}")
    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'extractor_args': {
        'youtube': ['player_client=web']
        },
        'quiet': True,
        'noplaylist': True,
        'forceurl': True,
        'forcejson': True,
        'skip_download': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('ext')  
    except Exception as e:
        logging.error(f"yt-dlp failed: {e}")
        return None, None

@app.route('/proxy/<string:video_id>')
def proxy_stream(video_id):
    stream_url, ext = get_streaming_url(video_id)
    if not stream_url:
        return jsonify({"error": "Could not get streaming URL"}), 404

    range_header = request.headers.get('Range')
    headers = {
        'User-Agent': 'Mozilla/5.0',
    }
    if range_header:
        headers['Range'] = range_header

    try:
        r = requests.get(stream_url, headers=headers, stream=True)

        if r.status_code not in (200, 206):
            logging.error(f"Stream request failed with status {r.status_code}")
            return jsonify({"error": f"Upstream returned {r.status_code}"}), 502

        content_type = r.headers.get('Content-Type', f'audio/{ext or "mp4"}')

        response_headers = {
            "Content-Type": content_type,
            "Content-Length": r.headers.get("Content-Length"),
            "Accept-Ranges": r.headers.get("Accept-Ranges", "bytes"),
        }

        if r.headers.get("Content-Range"):
            response_headers["Content-Range"] = r.headers["Content-Range"]

        return Response(
            stream_with_context(r.iter_content(chunk_size=4096)),
            status=r.status_code,
            headers={k: v for k, v in response_headers.items() if v is not None}
        )

    except Exception as e:
        logging.exception("Proxy stream error:")
        return jsonify({"error": "Failed to stream"}), 500

# --- ROUTE MỚI ĐỂ LẤY CHI TIẾT MỘT BÀI HÁT ---
@app.route('/api/song/<video_id>', methods=['GET'])
def get_song_details(video_id):
    """
    Lấy thông tin chi tiết cho một videoId cụ thể.
    """
    if not yt:
        return jsonify({'error': 'YTMusic service is not available.'}), 503
        
    try:
        # Dùng get_song để có dữ liệu video chính xác nhất
        song_data = yt.get_song(videoId=video_id)
        
        # Dữ liệu trả về từ get_song có cấu trúc hơi khác, chúng ta cần xử lý nó
        video_details = song_data.get('videoDetails', {})
        thumbnails = video_details.get('thumbnail', {}).get('thumbnails', [])
        thumbnail_url = thumbnails[-1]['url'] if thumbnails else ''
        
        # Tải ảnh về và tạo link proxy
        local_thumbnail_path = download_and_save_image(thumbnail_url, video_id)
        
        # Nối tên các nghệ sĩ lại
        artists = video_details.get('author', '').split(',')
        artist_names = ', '.join(artist.strip() for artist in artists)

        parsed_song = {
            'video_id': video_id,
            'title': video_details.get('title', 'Unknown Title'),
            'artist': artist_names or 'Unknown Artist',
            'thumbnail_url': f"{baseUrl}{local_thumbnail_path}" if local_thumbnail_path else "",
            # Chuyển đổi giây thành định dạng MM:SS
            'duration': _format_duration(video_details.get('lengthSeconds'))
        }
        
        return Response(json.dumps(parsed_song, ensure_ascii=False), mimetype='application/json')

    except Exception as e:
        return jsonify({'error': f"Lỗi khi lấy chi tiết bài hát: {str(e)}"}), 500

def _format_duration(seconds):
    """Hàm phụ để định dạng thời lượng từ giây sang MM:SS nếu có."""
    if seconds is None:
        return "N/A"
    try:
        # Chuyển đổi sang số nguyên để tính toán
        total_seconds = int(seconds)
        # divmod trả về một cặp giá trị (thương, số dư)
        minutes, seconds = divmod(total_seconds, 60)
        # f-string với :02d để đảm bảo luôn có 2 chữ số (vd: 03:09)
        return f"{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError):
        # Trả về N/A nếu đầu vào không phải là số
        return "N/A"


# hàm lấy ra một đống bài hát trending và ghi vào file json
def get_trending_songs(limit=10):
    try:

        playlist_id = 'PLgzTt0k8mXzEk586ze4BjvDXR7c-TUSnx'
        
        print(f"Đang lấy {limit} bài hát từ playlist thịnh hành: {playlist_id}")
        # Lấy danh sách bài hát từ search
        playlist_data = yt.get_playlist(playlist_id, limit=limit)
        results = playlist_data.get('tracks', []) 
        print(f"Tìm thấy {len(results)} bài hát từ playlist.")
        
    except Exception as e:
        print(f"Lỗi khi tìm kiếm bài hát: {e}")
        import traceback
        traceback.print_exc()
        return []

    songs = []
    for song in results:
        try:
            title = song.get("title", "Unknown Title")
            artists = song.get("artists", [])
            artist_names = ", ".join(artist.get("name", "Unknown") for artist in artists) if artists else "Unknown Artist"
            duration = song.get("duration", "N/A")
            video_id = song.get("videoId", "")
            thumbnails = song.get("thumbnails", [])
            thumbnail_url = thumbnails[-1].get("url", "") if thumbnails else ""

            songs.append({
                "title": title,
                "artist": artist_names,
                "duration": duration,
                "video_id": video_id,
                "thumbnail_url": thumbnail_url
            })
        except Exception as song_e:
            print(f"Lỗi khi xử lý bài hát: {song_e}")
            continue

    # Lưu cache nếu cần
    global trending_songs_cache
    trending_songs_cache = songs
    print(f"Đã lưu {len(songs)} bài hát vào cache")

    try:
        with open(CACHE_FILENAME_TRENDING, 'w', encoding='utf-8') as f:
            json.dump(songs, f, indent=4, ensure_ascii=False)
            print(f"Đã lưu cache vào file '{CACHE_FILENAME_TRENDING}'.")
    except IOError as e:
        print(f"Lỗi khi ghi cache vào file: {e}")

    return songs

# ROUTE MỚI ĐỂ XÓA CACHE VÀ REDIRECT
@app.route('/refresh-artists-cache')
def refresh_artists_cache():
    """Xóa file cache và chuyển hướng người dùng trở lại trang danh sách nghệ sĩ."""
    try:
        if os.path.exists(CACHE_FILENAME_ARTISTS):
            os.remove(CACHE_FILENAME_ARTISTS)
            print("Cache nghệ sĩ đã được xóa thành công.")
    except Exception as e:
        print(f"Lỗi khi xóa cache: {e}")
    
# dùng cho server: bấm để refresh cache (trending_songs_cache)
@app.route('/api/fetch_trending', methods=['POST'])
def fetch_trending_data():
    """
    Endpoint này được gọi bởi nút bấm "Cập nhật" để lấy dữ liệu mới nhất
    và lưu vào cache.
    """
    print("Yêu cầu làm mới dữ liệu trending...")
    # Hàm get_trending_songs của bạn đã tự động cập nhật cache rồi
    songs = get_trending_songs() 
    
    if songs:
        return jsonify({
            "status": "success", 
            "message": f"Đã cập nhật thành công {len(songs)} bài hát."
        }), 200
    else:
        return jsonify({
            "status": "error", 
            "message": "Không thể lấy dữ liệu mới từ API."
        }), 500




# UIUIUIUIUIUIUIUIUI
# UIUIUIUIUIUIUIUIUI
# UIUIUIUIUIUIUIUIUI
# UIUIUIUIUIUIUIUIUI

# Route hiển thị trang artists nổi bật
@app.route('/popular_artists')
def show_popular_artists_page():
    html = """
    <html>
    <head>
        <title>Popular Artists</title>
        <style>
            body { font-family: Arial, sans-serif; padding: 20px; background-color: #f5f5f5; }
            .container { max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
            h1 { color: #333; }
            .refresh-btn { display: inline-block; margin-bottom: 20px; padding: 10px 20px; background: #dc3545; color: white; text-decoration: none; border-radius: 5px; }
            .artist-list {{ list-style: none; padding: 0; }}
            .artist-item {{ display: flex; align-items: center; margin-bottom: 15px; border-bottom: 1px solid #eee; padding-bottom: 15px; }}
            .artist-item img {{ width: 50px; height: 50px; border-radius: 50%; margin-right: 15px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>👨‍🎤 Danh sách nghệ sĩ nổi bật</h1>
            <a href="/refresh-artists-cache" class="refresh-btn">Cập nhật danh sách (Xóa Cache)</a>
            <ul class="artist-list">
    """
    html += """
            </ul>
        </div>
    </body>
    </html>
    """
    return html

# MODIFY: Route hiển thị trang Trending
@app.route('/trending')
def show_trending():
    songs = trending_songs_cache 
    
    # Giữ nguyên logic xử lý lỗi nếu cache rỗng
    if not songs:
        initial_message = """
        <h1>Cache đang trống</h1>
        <p>Vui lòng bấm nút "Cập nhật dữ liệu" để lấy danh sách bài hát thịnh hành lần đầu tiên.</p>
        """
    else:
        initial_message = ""

    html = f"""
    <html>
    <head>
        <title>Bài hát đang thịnh hành</title>
        <style>
            /* CSS của bạn giữ nguyên, tôi thêm style cho nút bấm và status */
            body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
            h1 {{ color: #333; text-align: center; }}
            .controls {{ text-align: center; margin-bottom: 20px; }}
            #fetch-button {{ 
                padding: 10px 20px; 
                font-size: 16px; 
                cursor: pointer; 
                background-color: #28a745; 
                color: white; 
                border: none; 
                border-radius: 5px; 
            }}
            #fetch-button:hover {{ background-color: #218838; }}
            #fetch-button:disabled {{ background-color: #ccc; cursor: not-allowed; }}
            #status-message {{ text-align: center; margin-top: 10px; font-weight: bold; }}
            .song-container {{ display: flex; flex-wrap: wrap; gap: 20px; justify-content: center; }}
            /* ... (các style .song-card, v.v. của bạn giữ nguyên) ... */
            .song-card {{ background: white; border-radius: 10px; padding: 15px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); max-width: 300px; text-align: center; }}
            .song-thumbnail {{ width: 100%; height: 180px; object-fit: cover; border-radius: 8px; margin-bottom: 10px; }}
            .song-title {{ font-weight: bold; font-size: 16px; margin-bottom: 5px; color: #333; }}
            .song-artist {{ color: #666; margin-bottom: 5px; }}
            .song-info {{ font-size: 12px; color: #888; }}
            .video-link {{ display: inline-block; margin-top: 10px; padding: 8px 16px; background-color: #ff0000; color: white; text-decoration: none; border-radius: 5px; font-size: 12px; }}
            .video-link:hover {{ background-color: #cc0000; }}
            .song-detail-link {{ display: inline-block; margin-top: 5px; padding: 6px 12px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px; font-size: 11px; }}
            .song-detail-link:hover {{ background-color: #0056b3; }}
        </style>
    </head>
    <body>
        <h1>🎵 Bài hát đang thịnh hành</h1>
        
        <div class="controls">
            <button id="fetch-button">Cập nhật dữ liệu</button>
            <div id="status-message"></div>
        </div>

        {initial_message}

        <div class="song-container">
    """
    
    # Vòng lặp for để tạo các card bài hát giữ nguyên
    for i, song in enumerate(songs, 1):
        html += f"""
        <div class="song-card">
            <img src="{song['thumbnail_url']}" alt="{song['title']}" class="song-thumbnail" onerror="this.src='https://via.placeholder.com/300x180?text=No+Image'">
            <div class="song-title">#{i} {song['title']}</div>
            <div class="song-artist">👤 {song['artist']}</div>
            <div class="song-info">
                🆔 Video ID: {song['video_id']}<br>
            """
        if song['duration'] != "N/A":
            html += f"⏱️ Duration: {song['duration']}<br>"
        html += f"""
            </div>
            <a href="https://music.youtube.com/watch?v={song['video_id']}" target="_blank" class="video-link">
                ▶️ Nghe trên YouTube Music
            </a>
            <br>
            <a href="/song/{song['video_id']}" class="song-detail-link">
                📄 Chi tiết bài hát
            </a>
        </div>
        """
    
    html += """
        </div>
        
        <script>
            const fetchButton = document.getElementById('fetch-button');
            const statusMessage = document.getElementById('status-message');

            fetchButton.addEventListener('click', async () => {
                // Vô hiệu hóa nút và hiển thị thông báo đang tải
                fetchButton.disabled = true;
                statusMessage.style.color = 'blue';
                statusMessage.innerText = 'Đang lấy dữ liệu mới, vui lòng chờ...';

                try {
                    const response = await fetch('/api/fetch_trending', {
                        method: 'POST',
                    });

                    const data = await response.json();

                    if (response.ok) {
                        statusMessage.style.color = 'green';
                        statusMessage.innerText = data.message + ' Trang sẽ tự động tải lại...';
                        
                        // Đợi 2 giây rồi tải lại trang để hiển thị dữ liệu mới
                        setTimeout(() => {
                            window.location.reload();
                        }, 2000);

                    } else {
                        throw new Error(data.message || 'Lỗi không xác định.');
                    }
                } catch (error) {
                    statusMessage.style.color = 'red';
                    statusMessage.innerText = 'Lỗi: ' + error.message;
                    // Bật lại nút nếu có lỗi
                    fetchButton.disabled = false;
                }
            });
        </script>
        
    </body>
    </html>
    """
    return html
# New route to get raw JSON data
@app.route('/api/trending')
def api_trending():
    global trending_songs_cache
    return jsonify({
        "total_songs": len(trending_songs_cache),
        "songs": trending_songs_cache
    })
# Root route
@app.route('/')
def home():
    return """
    <html>
    <head>
        <title>YouTube Music Trending API</title>
        <style>
            body { font-family: Arial, sans-serif; padding: 20px; background-color: #f5f5f5; }
            .container { max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
            h1 { color: #333; text-align: center; }
            .feature-list { background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 20px 0; }
            .nav-link { display: inline-block; margin: 10px; padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px; }
            .nav-link:hover { background: #0056b3; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎵 YouTube Music Trending API</h1>
            
            <h3>📍 Điều hướng:</h3>
            <a href="/trending" class="nav-link">🎵 Xem bài hát trending</a>
            <a href="/api/trending" class="nav-link">📊 API JSON data</a>
            <a href="/debug" class="nav-link">🔧 Debug API structure</a>
            <a href="/search" class="nav-link">🔍 Tìm kiếm bài hát</a>
            <a href="/popular_artists" class="nav-link">🌟 Nghệ sĩ nổi bật</a>
        </div>
    </body>
    </html>
    """

# Load thử xem có cache (file json) không
# Nếu có thì load vào biến trending_songs_cache
def load_cache():
    """Hàm này sẽ được gọi một lần khi server bắt đầu."""
    global trending_songs_cache
    if os.path.exists(CACHE_FILENAME_TRENDING):
        try:
            with open(CACHE_FILENAME_TRENDING, 'r', encoding='utf-8') as f:
                trending_songs_cache = json.load(f)
                print(f"Đã tải thành công {len(trending_songs_cache)} bài hát từ file cache.")
        except (json.JSONDecodeError, IOError) as e:
            print(f"Lỗi khi đọc file cache: {e}. Bắt đầu với cache rỗng.")
            trending_songs_cache = []
    else:
        print("Không tìm thấy file cache. Bắt đầu với cache rỗng.")

# Run the application
if __name__ == '__main__':
    load_cache()
    app.run(host='0.0.0.0', port=5000, debug=True)