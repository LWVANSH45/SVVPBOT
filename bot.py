"""
Telegram Study Bot
-------------------
Features:
  - /start : Welcome message + subject buttons (Physics, Chemistry, Maths...)
  - Click subject -> shows chapter list
  - Click chapter -> bot sends all videos of that chapter, in order
  - Admin adds videos by simply FORWARDING the video to the bot (no link needed)

SETUP:
  1. pip install python-telegram-bot==21.4
  2. Get a bot token from @BotFather on Telegram
  3. Get your own numeric Telegram user id from @userinfobot
  4. Fill BOT_TOKEN and ADMIN_IDS below
  5. Run:  python study_bot.py

NOTE: If the original chat that you forward the video FROM has
"restrict saving content" turned ON, Telegram will not give the bot a
usable file_id for that video. Turn that restriction off in that chat
(or download+reupload the video to the bot) if forwarding doesn't work.
"""

import asyncio
import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, ConversationHandler, filters
)

# ========== CONFIG ==========
BOT_TOKEN = "8828462257:AAEFSZrmuf6s1lKCygOtJt3z7Buv0Rb_KDA"
ADMIN_IDS = [8375821446]  # <-- replace with your Telegram numeric user id(s)
DB_PATH = "study_bot.db"

logging.basicConfig(level=logging.INFO)

# ========== DATABASE ==========
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

import os

def init_db():
    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("SELECT name FROM sqlite_master LIMIT 1")
            conn.close()
        except sqlite3.DatabaseError:
            os.remove(DB_PATH)
            print("Corrupted database removed.")

    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    );

    CREATE TABLE IF NOT EXISTS chapters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id INTEGER,
        name TEXT,
        UNIQUE(subject_id, name),
        FOREIGN KEY(subject_id) REFERENCES subjects(id)
    );

    CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chapter_id INTEGER,
        file_id TEXT,
        title TEXT,
        position INTEGER,
        FOREIGN KEY(chapter_id) REFERENCES chapters(id)
    );
    """)
    conn.commit()
    conn.close()
    conn.close()

# ========== HELPERS ==========
def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_subjects():
    conn = db()
    rows = conn.execute("SELECT id, name FROM subjects ORDER BY name").fetchall()
    conn.close()
    return rows

def get_chapters(subject_id):
    conn = db()
    rows = conn.execute(
        "SELECT id, name FROM chapters WHERE subject_id=? ORDER BY id", (subject_id,)
    ).fetchall()
    conn.close()
    return rows

def get_videos(chapter_id):
    conn = db()
    rows = conn.execute(
        "SELECT file_id, title, position FROM videos WHERE chapter_id=? ORDER BY position",
        (chapter_id,)
    ).fetchall()
    conn.close()
    return rows

def get_or_create_subject(name):
    conn = db()
    conn.execute("INSERT OR IGNORE INTO subjects(name) VALUES (?)", (name,))
    conn.commit()
    row = conn.execute("SELECT id FROM subjects WHERE name=?", (name,)).fetchone()
    conn.close()
    return row[0]

def get_or_create_chapter(subject_id, name):
    conn = db()
    conn.execute(
        "INSERT OR IGNORE INTO chapters(subject_id, name) VALUES (?,?)",
        (subject_id, name)
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM chapters WHERE subject_id=? AND name=?", (subject_id, name)
    ).fetchone()
    conn.close()
    return row[0]

def add_video(chapter_id, file_id, title):
    conn = db()
    pos = conn.execute(
        "SELECT COALESCE(MAX(position),0)+1 FROM videos WHERE chapter_id=?", (chapter_id,)
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO videos(chapter_id, file_id, title, position) VALUES (?,?,?,?)",
        (chapter_id, file_id, title, pos)
    )
    conn.commit()
    conn.close()
    return pos

def delete_video(video_id):
    conn = db()
    conn.execute("DELETE FROM videos WHERE id=?", (video_id,))
    conn.commit()
    conn.close()

def get_videos_with_id(chapter_id):
    conn = db()
    rows = conn.execute(
        "SELECT id, title, position FROM videos WHERE chapter_id=? ORDER BY position",
        (chapter_id,)
    ).fetchall()
    conn.close()
    return rows

# ========== USER SIDE: /start, browse ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subjects = get_subjects()
    if not subjects:
        await update.message.reply_text(
            "Welcome! 👋 No subjects added yet. Admin needs to add content first."
        )
        return
    kb = [[InlineKeyboardButton(name, callback_data=f"subj:{sid}")] for sid, name in subjects]
    await update.message.reply_text(
        "Welcome to Study Bot! 📚\nChoose a subject:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "back:subjects":
        subjects = get_subjects()
        kb = [[InlineKeyboardButton(name, callback_data=f"subj:{sid}")] for sid, name in subjects]
        await query.edit_message_text("Choose a subject:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("subj:"):
        sid = int(data.split(":")[1])
        chapters = get_chapters(sid)
        if not chapters:
            await query.edit_message_text(
                "No chapters in this subject yet.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("« Back", callback_data="back:subjects")]]
                )
            )
            return
        kb = [[InlineKeyboardButton(name, callback_data=f"chap:{cid}")] for cid, name in chapters]
        kb.append([InlineKeyboardButton("« Back", callback_data="back:subjects")])
        await query.edit_message_text("Choose a chapter:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("chap:"):
        cid = int(data.split(":")[1])
        videos = get_videos(cid)
        if not videos:
            await query.edit_message_text("No videos in this chapter yet.")
            return
        await query.edit_message_text(f"Sending {len(videos)} lecture(s)...")
        for file_id, title, pos in videos:
            caption = title if title else f"Lecture {pos}"
            await context.bot.send_video(
                chat_id=query.message.chat_id, video=file_id, caption=caption
            )

# ========== ADMIN SIDE: /addvideo conversation ==========
CHOOSE_SUBJECT, TYPE_SUBJECT, CHOOSE_CHAPTER, TYPE_CHAPTER, RECEIVE_VIDEO = range(5)

async def addvideo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Only admin can add videos.")
        return ConversationHandler.END
    subjects = get_subjects()
    kb = [[InlineKeyboardButton(name, callback_data=f"a_subj:{sid}")] for sid, name in subjects]
    kb.append([InlineKeyboardButton("+ New Subject", callback_data="a_subj:new")])
    await update.message.reply_text("Choose subject (or add new):", reply_markup=InlineKeyboardMarkup(kb))
    return CHOOSE_SUBJECT

async def choose_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    val = query.data.split(":")[1]
    if val == "new":
        await query.edit_message_text("Send the new subject name (e.g. Physics):")
        return TYPE_SUBJECT
    context.user_data["subject_id"] = int(val)
    return await show_chapters(update, context)

async def type_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    sid = get_or_create_subject(name)
    context.user_data["subject_id"] = sid
    subjects_msg = await update.message.reply_text(f"Subject '{name}' ready.")
    return await show_chapters(update, context, use_message=True)

async def show_chapters(update, context, use_message=False):
    sid = context.user_data["subject_id"]
    chapters = get_chapters(sid)
    kb = [[InlineKeyboardButton(name, callback_data=f"a_chap:{cid}")] for cid, name in chapters]
    kb.append([InlineKeyboardButton("+ New Chapter", callback_data="a_chap:new")])
    text = "Choose chapter (or add new):"
    if use_message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    return CHOOSE_CHAPTER

async def choose_chapter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    val = query.data.split(":")[1]
    if val == "new":
        await query.edit_message_text("Send the new chapter name (e.g. Chapter 1 - Motion):")
        return TYPE_CHAPTER
    context.user_data["chapter_id"] = int(val)
    await query.edit_message_text(
        "Now forward or send the video(s) for this chapter.\n"
        "Send them one by one. Type /done when finished."
    )
    return RECEIVE_VIDEO

async def type_chapter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    sid = context.user_data["subject_id"]
    cid = get_or_create_chapter(sid, name)
    context.user_data["chapter_id"] = cid
    await update.message.reply_text(
        f"Chapter '{name}' ready.\nNow forward or send the video(s). Send /done when finished."
    )
    return RECEIVE_VIDEO

async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    file_id = None
    if msg.video:
        file_id = msg.video.file_id
    elif msg.document and (msg.document.mime_type or "").startswith("video"):
        file_id = msg.document.file_id
    if not file_id:
        await msg.reply_text("That's not a video. Please forward/send a video file, or /done to finish.")
        return RECEIVE_VIDEO
    cid = context.user_data["chapter_id"]
    title = msg.caption.strip() if msg.caption else None
    pos = add_video(cid, file_id, title)
    await msg.reply_text(f"Saved as Lecture {pos}. Send next video or /done to finish.")
    return RECEIVE_VIDEO

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Done adding videos. ✅")
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END

# ========== ADMIN SIDE: /delvideo (remove a mistakenly added video) ==========
async def delvideo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Only admin can delete videos.")
        return
    subjects = get_subjects()
    if not subjects:
        await update.message.reply_text("No subjects yet.")
        return
    kb = [[InlineKeyboardButton(name, callback_data=f"d_subj:{sid}")] for sid, name in subjects]
    await update.message.reply_text("Choose subject:", reply_markup=InlineKeyboardMarkup(kb))

async def del_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("d_subj:"):
        sid = int(data.split(":")[1])
        chapters = get_chapters(sid)
        if not chapters:
            await query.edit_message_text("No chapters in this subject.")
            return
        kb = [[InlineKeyboardButton(name, callback_data=f"d_chap:{cid}")] for cid, name in chapters]
        await query.edit_message_text("Choose chapter:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("d_chap:"):
        cid = int(data.split(":")[1])
        context.user_data["del_chapter_id"] = cid
        videos = get_videos_with_id(cid)
        if not videos:
            await query.edit_message_text("No videos in this chapter.")
            return
        kb = [
            [InlineKeyboardButton(f"❌ Lecture {pos}: {title or 'Untitled'}", callback_data=f"d_vid:{vid}")]
            for vid, title, pos in videos
        ]
        await query.edit_message_text("Tap a video to delete it:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("d_vid:"):
        vid = int(data.split(":")[1])
        delete_video(vid)
        cid = context.user_data.get("del_chapter_id")
        videos = get_videos_with_id(cid) if cid else []
        if not videos:
            await query.edit_message_text("Deleted. No videos left in this chapter.")
            return
        kb = [
            [InlineKeyboardButton(f"❌ Lecture {pos}: {title or 'Untitled'}", callback_data=f"d_vid:{vid}")]
            for vid, title, pos in videos
        ]
        await query.edit_message_text("Deleted ✅. Tap another to delete, or /start to go back.", reply_markup=InlineKeyboardMarkup(kb))
        return

# ========== MAIN ==========
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(subj:|chap:|back:)"))
    app.add_handler(CommandHandler("delvideo", delvideo_start))
    app.add_handler(CallbackQueryHandler(del_button_handler, pattern="^(d_subj:|d_chap:|d_vid:)"))

    conv = ConversationHandler(
        entry_points=[CommandHandler("addvideo", addvideo_start)],
        states={
            CHOOSE_SUBJECT: [CallbackQueryHandler(choose_subject, pattern="^a_subj:")],
            TYPE_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, type_subject)],
            CHOOSE_CHAPTER: [CallbackQueryHandler(choose_chapter, pattern="^a_chap:")],
            TYPE_CHAPTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, type_chapter)],
            RECEIVE_VIDEO: [
                MessageHandler(filters.VIDEO | filters.Document.ALL, receive_video),
                CommandHandler("done", done),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
