import telebot
import requests
import yt_dlp
import os
import re
import urllib.parse
import glob
import socket
import time
from telebot import types
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import requests.packages.urllib3.util.connection as urllib3_cn

# ================= 1. FIX KONEKSI (SOLUSI SSLEOFError) =================
# Memaksa koneksi menggunakan IPv4 agar tidak terjadi error SSL di Railway
def allowed_gai_family():
    return socket.AF_INET

urllib3_cn.allowed_gai_family = allowed_gai_family

# Membuat Session dengan sistem Retry agar lebih tangguh
session = requests.Session()
retries = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    raise_on_status=False
)
session.mount('https://', HTTPAdapter(max_retries=retries))

# ================= 2. CONFIG =================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEB_APP_URL = "https://lyrics-seeker.vercel.app"
LRCLIB_BASE = "https://lrclib.net"
HEADERS = {
    "User-Agent": "LyricsSeekerBot/1.0 (https://t.me/lyricseekerbot)"
}

bot = telebot.TeleBot(TELEGRAM_TOKEN)
user_data = {}

# ================= 3. UTILS =================
def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)

def fetch_full_song_info(song):
    """Ambil detail lirik via /api/get-cached dengan session yang sudah dioptimasi"""
    try:
        params = {
            "track_name": song.get("trackName", ""),
            "artist_name": song.get("artistName", ""),
            "album_name": song.get("albumName", ""),
            "duration": song.get("duration", 0),
        }
        # Gunakan session.get (bukan requests.get)
        res = session.get(
            f"{LRCLIB_BASE}/api/get-cached",
            params=params,
            headers=HEADERS,
            timeout=25
        )
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"⚠️ Gagal memanggil get-cached: {e}")
    return song

# ================= 4. HANDLERS =================

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, "Ketik judul lagu dan nama penyanyi yang ingin dicari.")

@bot.message_handler(func=lambda m: True)
def handle_search(message):
    query = message.text.strip()
    if not query: return

    sent = bot.reply_to(message, f"🔎 Mencari <b>{query}</b>...", parse_mode="HTML")
    try:
        # Gunakan session.get untuk pencarian
        res = session.get(
            f"{LRCLIB_BASE}/api/search",
            params={"q": query},
            headers=HEADERS,
            timeout=20
        )
        res.raise_for_status()
        data = res.json()
        
        if not data:
            bot.edit_message_text("❌ Lagu tidak ditemukan.", message.chat.id, sent.message_id)
            return

        user_data[message.chat.id] = data
        show_results(message.chat.id, 0, sent.message_id)
    except Exception as e:
        print(f"❌ LRCLIB error: {e}")
        bot.edit_message_text("⚠️ Gangguan koneksi ke server lirik. Coba lagi.", message.chat.id, sent.message_id)

def show_results(chat_id, page, msg_id):
    results = user_data.get(chat_id, [])
    batch = results[page * 10: page * 10 + 10]
    if not batch: return

    text_lines = []
    for i, song in enumerate(batch):
        global_num = page * 10 + i + 1
        text_lines.append(f"{global_num}. {song.get('trackName')} - {song.get('artistName')}")
    
    markup = types.InlineKeyboardMarkup()
    num_buttons = []
    for i in range(len(batch)):
        global_idx = page * 10 + i
        num_buttons.append(types.InlineKeyboardButton(str(global_idx + 1), callback_data=f"send_{global_idx}"))
        if len(num_buttons) == 5 or i == len(batch) - 1:
            markup.row(*num_buttons)
            num_buttons = []

    nav = []
    total_pages = (len(results) + 9) // 10
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"pg_{page - 1}"))
    nav.append(types.InlineKeyboardButton("❌", callback_data="cancel"))
    if page < total_pages - 1: nav.append(types.InlineKeyboardButton("➡️", callback_data=f"pg_{page + 1}"))
    markup.row(*nav)

    bot.edit_message_text(f"🎧 Hasil pencarian:\n\n" + "\n".join(text_lines), chat_id, msg_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    if call.data == "cancel":
        bot.edit_message_text("✖️ Batal.", chat_id, call.message.message_id)
    elif call.data.startswith("pg_"):
        show_results(chat_id, int(call.data.split("_")[1]), call.message.message_id)
    elif call.data.startswith("send_"):
        idx = int(call.data.split("_")[1])
        song = user_data[chat_id][idx]
        sent = bot.edit_message_text("⏳ Memproses...", chat_id, call.message.message_id)
        send_audio_and_lyrics(chat_id, song, sent.message_id)

def send_audio_and_lyrics(chat_id, song, download_msg_id):
    song = fetch_full_song_info(song)
    track = song.get('trackName', 'Unknown')
    artist = song.get('artistName', 'Unknown')
    lyrics = song.get('plainLyrics', 'Lirik tidak tersedia.')
    clean = sanitize_filename(f"{track} - {artist}")

    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': clean + '.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'http_headers': {'User-Agent': 'Mozilla/5.0'}
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"ytsearch1:{track} {artist}"])
        
        audio_file = glob.glob(f"{clean}.*")[0]
        with open(audio_file, 'rb') as f:
            bot.send_audio(chat_id, f, title=track, performer=artist)
        
        bot.delete_message(chat_id, download_msg_id)
        
        # Kirim lirik
        for i in range(0, len(lyrics), 4000):
            bot.send_message(chat_id, lyrics[i:i + 4000])

        # Web App
        markup = types.InlineKeyboardMarkup()
        l_url = f"{WEB_APP_URL}/?track={urllib.parse.quote(track)}&artist={urllib.parse.quote(artist)}"
        markup.add(types.InlineKeyboardButton("✨ Lirik Synced", web_app=types.WebAppInfo(url=l_url)))
        bot.send_message(chat_id, "Kelola di Web App:", reply_markup=markup)
        
        os.remove(audio_file)
    except Exception as e:
        print(f"❌ Error: {e}")
        bot.send_message(chat_id, "⚠️ Gagal memproses lagu.")

# ================= 5. MAIN ENTRY (SOLUSI Conflict 409) =================
if __name__ == "__main__":
    print("🚀 Membersihkan sesi lama...")
    bot.remove_webhook() # Hapus webhook jika ada
    time.sleep(1)        # Beri jeda agar Telegram reset koneksi
    print("✅ Bot Lyrics Seeker aktif!")
    # skip_pending=True agar bot tidak membalas pesan lama saat mati
    bot.polling(none_stop=True, skip_pending=True)