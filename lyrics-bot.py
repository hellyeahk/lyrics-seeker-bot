import telebot
import requests
import yt_dlp
import os
import re
import urllib.parse
import glob
from telebot import types

# ================= CONFIG =================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEB_APP_URL = "https://lyrics-seeker.vercel.app"
LRCLIB_BASE = "https://lrclib.net"
HEADERS = {
    "User-Agent": "LyricsSeekerBot/1.0 (https://t.me/lyricseekerbot)"
}
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
    if not query:
        return

    sent = bot.reply_to(
        message,
        f"🔎 Mencari <b>{query}</b>...",
        parse_mode="HTML"
    )
    try:
        # Pencarian awal dengan /api/search
        res = requests.get(
            f"{LRCLIB_BASE}/api/search",
            params={"q": query},
            headers=HEADERS,
            timeout=20
        )
        res.raise_for_status()
        data = res.json()
        if not data:
            bot.edit_message_text(
                "❌ Lagu tidak ditemukan.",
                message.chat.id,
                sent.message_id
            )
            return

        user_data[message.chat.id] = data
        show_results(message.chat.id, 0, sent.message_id)
    except Exception as e:
        print("❌ LRCLIB error:", e)
        bot.edit_message_text(
            "⚠️ Gagal mencari lirik.",
            message.chat.id,
            sent.message_id
        )


def show_results(chat_id, page, msg_id):
    results = user_data.get(chat_id, [])
    batch = results[page * 10: page * 10 + 10]  # 10 lagu/halaman
    if not batch:
        return

    # Teks: nomor global (1, 2, 3, ..., N)
    text_lines = []
    for i, song in enumerate(batch):
        global_num = page * 10 + i + 1  # 1, 2, ..., 11, 12, ...
        title = song.get('trackName', 'Unknown')
        artist = song.get('artistName', 'Unknown')
        text_lines.append(f"{global_num}. {title} - {artist}")
    text = "\n".join(text_lines)

    # Tombol: gunakan NOMOR GLOBAL di teks tombol
    markup = types.InlineKeyboardMarkup()
    num_buttons = []
    for i in range(len(batch)):
        global_idx = page * 10 + i        # indeks untuk callback
        global_num = global_idx + 1       # nomor yang ditampilkan
        num_buttons.append(
            types.InlineKeyboardButton(
                str(global_num),
                callback_data=f"send_{global_idx}"
            )
        )
        if len(num_buttons) == 5 or i == len(batch) - 1:
            markup.row(*num_buttons)
            num_buttons = []

    # Navigasi
    nav = []
    total_pages = (len(results) + 9) // 10
    if page > 0:
        nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"pg_{page - 1}"))
    nav.append(types.InlineKeyboardButton("❌", callback_data="cancel"))
    if page < total_pages - 1:
        nav.append(types.InlineKeyboardButton("➡️", callback_data=f"pg_{page + 1}"))
    markup.row(*nav)

    start_idx = page * 10 + 1
    end_idx = min((page + 1) * 10, len(results))
    header = f"🎧 Pencarian {start_idx}-{end_idx} dari {len(results)}\n\n"
    bot.edit_message_text(header + text, chat_id, msg_id, reply_markup=markup)


@bot.callback_query_handler(func=lambda c: True)
def handle_callback(call):
    chat_id = call.message.chat.id

    if call.data == "cancel":
        bot.edit_message_text(
            "✖️ Pencarian dibatalkan.",
            chat_id,
            call.message.message_id
        )

    elif call.data.startswith("pg_"):
        page = int(call.data.split("_")[1])
        show_results(chat_id, page, call.message.message_id)

    elif call.data.startswith("send_"):
        idx = int(call.data.split("_")[1])

        if chat_id not in user_data:
            bot.answer_callback_query(
                call.id,
                "🔍 Data pencarian sudah kadaluarsa.\nCoba cari lagu lagi.",
                show_alert=True
            )
            return

        all_results = user_data[chat_id]
        if idx >= len(all_results):
            bot.answer_callback_query(
                call.id,
                "❌ Lagu tidak ditemukan.",
                show_alert=True
            )
            return

        song = all_results[idx]
        sent = bot.edit_message_text(
            "⏳ Mengunduh audio...",
            chat_id,
            call.message.message_id
        )
        send_audio_and_lyrics(chat_id, song, sent.message_id)


def fetch_full_song_info(song):
    """
    Ambil detail lirik via /api/get-cached berdasarkan signature:
    track_name, artist_name, album_name, duration.
    Jika gagal, fallback ke data awal dari /api/search.
    """
    try:
        params = {
            "track_name": song.get("trackName", ""),
            "artist_name": song.get("artistName", ""),
            "album_name": song.get("albumName", ""),
            "duration": song.get("duration", 0),
        }
        res = requests.get(
            f"{LRCLIB_BASE}/api/get-cached",
            params=params,
            headers=HEADERS,
            timeout=25
        )
        if res.status_code == 200:
            return res.json()
        else:
            print("⚠️ get-cached status:", res.status_code, res.text)
    except Exception as e:
        print("⚠️ Gagal memanggil /api/get-cached:", e)

    return song


def send_audio_and_lyrics(chat_id, song, download_msg_id):
    # Perkaya info lagu dengan /api/get-cached
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
        'source_address': '0.0.0.0',
        'geo_bypass': True,
        'geo_bypass_country': 'US',
        'http_headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            )
        }
    }

    # Download audio
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

    candidates = glob.glob(f"{clean}.*")
    if not candidates:
        print("❌ Tidak ada file audio yang dihasilkan!")
        bot.send_message(chat_id, "⚠️ Audio tidak ditemukan.")
        return

    audio_file = candidates[0]
    print(f"🔊 File ditemukan: {audio_file}")

    # Kirim audio
    try:
        with open(audio_file, 'rb') as f:
            bot.send_audio(chat_id, f, title=track, performer=artist)
        # Hapus pesan "Mengunduh audio..."
        bot.delete_message(chat_id, download_msg_id)
    except Exception as e:
        print(f"❌ Gagal kirim/hapus: {e}")
        bot.send_message(chat_id, "⚠️ Gagal mengirim audio.")

    # Kirim lirik (dipotong 4000 karakter per pesan)
    for i in range(0, len(lyrics), 4000):
        bot.send_message(chat_id, lyrics[i:i + 4000])

    # Kirim Web App
    encoded_track = urllib.parse.quote(track)
    encoded_artist = urllib.parse.quote(artist)
    youtube_url = (
        f"https://www.youtube.com/results?"
        f"search_query={encoded_track}+{encoded_artist}"
    )
    lyrics_url = f"{WEB_APP_URL}/?track={encoded_track}&artist={encoded_artist}"

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(
            "✨ Lirik Synced",
            web_app=types.WebAppInfo(url=lyrics_url)
        )
    )
    bot.send_message(chat_id, "Atau kelola di Web App:", reply_markup=markup)

    # Hapus file lokal
    try:
        os.remove(audio_file)
        print(f"🗑️ File {audio_file} dihapus.")
    except Exception as e:
        print(f"⚠️ Gagal hapus file: {e}")


if __name__ == "__main__":
    print("🚀 Lyrics Seeker Bot aktif!")
    bot.polling(none_stop=True)
