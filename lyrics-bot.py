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
        # ✅ CEGAH KeyError jika data sudah kadaluarsa
        if chat_id not in user_data:
            bot.answer_callback_query(
                call.id,
                "🔍 Data pencarian sudah kadaluarsa.\nCoba cari lagu lagi.",
                show_alert=True
            )
            return
        idx = int(call.data.split("_")[1])
        song = user_data[chat_id][idx]
        bot.edit_message_text("⏳ Mengunduh audio...", chat_id, call.message.message_id)
        send_audio_and_lyrics(chat_id, song)

def send_audio_and_lyrics(chat_id, song):
    track = song.get('trackName', 'Unknown')
    artist = song.get('artistName', 'Unknown')
    lyrics = song.get('plainLyrics', 'Lirik tidak tersedia.')
    clean = sanitize_filename(f"{track} - {artist}")

    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio',  # Prioritaskan .m4a (kompatibel Telegram)
        'outtmpl': clean + '.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'source_address': '0.0.0.0'
    }

    audio_file = None
    try:
        print(f"📥 Memproses: {track} - {artist}")
        print("🔄 Mulai download audio...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"ytsearch1:{track} {artist}"])
        print("✅ Download selesai.")
    except Exception as e:
        print(f"❌ Gagal download: {e}")
        bot.send_message(chat_id, "⚠️ Gagal mengunduh audio.")
        return

    # Cari file dengan ekstensi apa pun yang dihasilkan
    for ext in ['.m4a', '.webm', '.mp3', '.ogg']:
        candidate = f"{clean}{ext}"
        if os.path.exists(candidate):
            audio_file = candidate
            break

    if audio_file:
        print(f"🔊 Mengirim: {audio_file}")
        try:
            with open(audio_file, 'rb') as f:
                bot.send_audio(chat_id, f, title=track, performer=artist)
        except Exception as e:
            print(f"❌ Gagal kirim audio ke Telegram: {e}")
            bot.send_message(chat_id, "⚠️ Gagal mengirim audio.")
            return
    else:
        print("❌ Tidak ada file audio yang dihasilkan!")
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

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✨ Lirik Synced", web_app=types.WebAppInfo(url=lyrics_url))
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

