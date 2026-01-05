import telebot
import requests
import yt_dlp
import os
import re
import urllib.parse
from telebot import types

# ================= CONFIG =================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEB_APP_URL = "https://lyrics-seeker.vercel.app"  # TANPA spasi di akhir!
# =========================================

bot = telebot.TeleBot(TELEGRAM_TOKEN)
user_data = {}

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(
        message,
        "Ketik judul lagu dan nama penyanyi yang ingin dicari.\n",
        parse_mode="HTML"
    )

@bot.message_handler(func=lambda m: True)
def handle_search(message):
    query = message.text.strip()
    if not query: return

    sent = bot.reply_to(message, f"🔎 Mencari <b>{query}</b>...", parse_mode="HTML")
    try:
        res = requests.get("https://lrclib.net/api/search", params={"q": query}, timeout=20)  # HAPUS SPASI
        res.raise_for_status()
        data = res.json()
        if not data:
            bot.edit_message_text("❌ Lagu tidak ditemukan.", message.chat.id, sent.message_id)
            return
        user_data[message.chat.id] = data
        show_results(message.chat.id, 0, sent.message_id)
    except Exception as e:
        print("❌ LRCLIB error:", e)
        bot.edit_message_text("⚠️ Gagal mencari lirik.", message.chat.id, sent.message_id)

def show_results(chat_id, page, msg_id):
    results = user_data.get(chat_id, [])
    batch = results[page*5 : page*5+5]
    if not batch: return

    markup = types.InlineKeyboardMarkup()
    for i, song in enumerate(batch):
        idx = page*5 + i
        txt = f"{song.get('trackName', 'Unknown')} - {song.get('artistName', 'Unknown')}"
        markup.add(types.InlineKeyboardButton(txt[:60], callback_data=f"send_{idx}"))
    
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"pg_{page-1}"))
    if len(results) > (page+1)*5: nav.append(types.InlineKeyboardButton("➡️", callback_data=f"pg_{page+1}"))
    if nav: markup.row(*nav)

    bot.edit_message_text(f"🎧 Pilih lagu (Hal {page+1}):", chat_id, msg_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    if call.data.startswith("pg_"):
        page = int(call.data.split("_")[1])
        show_results(chat_id, page, call.message.message_id)
    elif call.data.startswith("send_"):
        idx = int(call.data.split("_")[1])
        song = user_data[chat_id][idx]
        bot.edit_message_text("⏳ Mengunduh audio...", chat_id, call.message.message_id)
        send_audio_and_lyrics(chat_id, song)

def send_audio_and_lyrics(chat_id, song):
    track = song.get('trackName', 'Unknown')
    artist = song.get('artistName', 'Unknown')
    lyrics = song.get('plainLyrics', 'Lirik tidak tersedia.')
    clean = sanitize_filename(f"{track} - {artist}")
    mp3 = f"{clean}.mp3"

    # 🔍 LOGGING: Tampilkan info lagu
    print(f"📥 Memproses lagu: {track} - {artist}")

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': clean + '.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }],
        'quiet': True,
        'no_warnings': True,
        'source_address': '0.0.0.0'
    }

    audio_file = None
    try:
        print("🔄 Mulai download audio...")
        # HAPUS kata "audio" dari query → lebih andal
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"ytsearch1:{track} {artist}"])
        print("✅ Download selesai.")
    except Exception as e:
        print(f"❌ Gagal download: {e}")
        bot.send_message(chat_id, "⚠️ Gagal mengunduh audio.")
        return

    # Cek apakah file MP3 benar-benar ada
    print(f"📁 Mencari file: {mp3}")
    if os.path.exists(mp3):
        audio_file = mp3
        print("🔊 Mengirim audio ke Telegram...")
        with open(mp3, 'rb') as f:
            bot.send_audio(chat_id, f, title=track, performer=artist)
    else:
        print("❌ File MP3 TIDAK ditemukan setelah download!")
        bot.send_message(chat_id, "⚠️ Audio tidak ditemukan.")
        return

    # Kirim lirik
    for i in range(0, len(lyrics), 4000):
        bot.send_message(chat_id, lyrics[i:i+4000])

    # Siapkan URL Web App
    encoded_track = urllib.parse.quote(track)
    encoded_artist = urllib.parse.quote(artist)
    youtube_url = f"https://www.youtube.com/results?search_query={encoded_track}+{encoded_artist}"  # TANPA SPASI
    lyrics_url = f"{WEB_APP_URL}/?track={encoded_track}&artist={encoded_artist}"
    save_url = f"{WEB_APP_URL}/?action=save&track={encoded_track}&artist={encoded_artist}&youtube={urllib.parse.quote(youtube_url)}"

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✨ Lirik Synced", web_app=types.WebAppInfo(url=lyrics_url)),
        types.InlineKeyboardButton("➕ Simpan ke Playlist", web_app=types.WebAppInfo(url=save_url))
    )
    bot.send_message(chat_id, "Atau kelola di Web App:", reply_markup=markup)

    # Hapus file setelah kirim
    if audio_file and os.path.exists(audio_file):
        try:
            os.remove(audio_file)
            print(f"🗑️ File {audio_file} dihapus.")
        except Exception as e:
            print(f"⚠️ Gagal hapus file: {e}")

if __name__ == "__main__":
    print("🚀 Lyrics Seeker Bot aktif!")
    bot.polling(none_stop=True)
