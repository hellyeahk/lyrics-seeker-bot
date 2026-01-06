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

# 1. PAKSA IPV4 UNTUK STABILITAS DI RAILWAY
def allowed_gai_family():
    return socket.AF_INET
urllib3_cn.allowed_gai_family = allowed_gai_family

# 2. KONFIGURASI
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEB_APP_URL = "https://lyrics-seeker.vercel.app"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
user_data = {}

# 3. FUNGSI UTILITY (Diletakkan di atas agar tidak NameError)
def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)

# 4. SETTING REQUESTS DENGAN RETRY (Untuk atasi SSL Error)
session = requests.Session()
retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
session.mount('https://', HTTPAdapter(max_retries=retries))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, "Ketik judul lagu dan penyanyi yang ingin dicari.")

@bot.message_handler(func=lambda m: True)
def handle_search(message):
    query = message.text.strip()
    if not query: return

    sent = bot.reply_to(message, f"🔎 Mencari <b>{query}</b>...", parse_mode="HTML")
    try:
        # Gunakan session yang sudah disetting retry
        res = session.get(
            "https://lrclib.net/api/search", 
            params={"q": query}, 
            headers=HEADERS, 
            timeout=15
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
        bot.edit_message_text("⚠️ Gagal mengambil lirik. Coba lagi dalam beberapa saat.", message.chat.id, sent.message_id)

def show_results(chat_id, page, msg_id):
    results = user_data.get(chat_id, [])
    batch = results[page*10 : page*10+10]
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
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"pg_{page-1}"))
    nav.append(types.InlineKeyboardButton("❌", callback_data="cancel"))
    if page < (len(results) + 9) // 10 - 1: nav.append(types.InlineKeyboardButton("➡️", callback_data=f"pg_{page+1}"))
    markup.row(*nav)

    bot.edit_message_text("\n".join(text_lines), chat_id, msg_id, reply_markup=markup)

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
        sent = bot.edit_message_text("⏳ Mengunduh audio...", chat_id, call.message.message_id)
        send_audio_and_lyrics(chat_id, song, sent.message_id)

def send_audio_and_lyrics(chat_id, song, download_msg_id):
    track = song.get('trackName', 'Unknown')
    artist = song.get('artistName', 'Unknown')
    lyrics = song.get('plainLyrics', 'Lirik tidak tersedia.')
    clean = sanitize_filename(f"{track} - {artist}")

    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': f'{clean}.%(ext)s',
        'quiet': True, 'noplaylist': True,
        'http_headers': HEADERS
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"ytsearch1:{track} {artist}"])
        
        audio_file = glob.glob(f"{clean}.*")[0]
        with open(audio_file, 'rb') as f:
            bot.send_audio(chat_id, f, title=track, performer=artist)
        
        bot.delete_message(chat_id, download_msg_id)
        
        # Kirim Lirik
        for i in range(0, len(lyrics), 4000):
            bot.send_message(chat_id, lyrics[i:i+4000])

        # Web App
        markup = types.InlineKeyboardMarkup()
        l_url = f"{WEB_APP_URL}/?track={urllib.parse.quote(track)}&artist={urllib.parse.quote(artist)}"
        markup.add(types.InlineKeyboardButton("Synced Lyrics", web_app=types.WebAppInfo(url=l_url)))
        bot.send_message(chat_id, "Kelola di Web App:", reply_markup=markup)
        
        os.remove(audio_file)
    except Exception as e:
        print(f"❌ Error: {e}")
        bot.send_message(chat_id, "⚠️ Terjadi kesalahan saat memproses audio.")

if __name__ == "__main__":
    print("🚀 Bot running...")
    # Menghapus webhook lama agar tidak Conflict 409
    bot.remove_webhook()
    time.sleep(1)
    bot.polling(none_stop=True)