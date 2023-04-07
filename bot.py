import asyncio
import logging
import os
import sqlite3
import sys
import textwrap
import uuid

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    InlineQueryHandler,
)
from email_validator import validate_email, EmailNotValidError


logging.basicConfig(
    filename="mailbot.log",
    filemode="a",
    level=logging.INFO,
    format="%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s",
    datefmt="%m/%d/%Y %I:%M:%S %p",
)
_logger = logging.getLogger(__name__)
_logger.addHandler(logging.StreamHandler())


class DB:
    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._conn = sqlite3.connect("mailbot.db")
        self._cursor = self._conn.cursor()
        self._cursor.execute(
            "CREATE TABLE IF NOT EXISTS user (id INTEGER PRIMARY KEY, email TEXT)")
        self._cursor.execute(
            "CREATE TABLE IF NOT EXISTS list (id INTEGER PRIMARY KEY, list TEXT)")
        self._logger.info("DB connected")

    def insert_user(self, user_id: int, email: str) -> None:
        self._cursor.execute("INSERT OR REPLACE INTO user VALUES (?, ?)", (user_id, email))
        self._conn.commit()
        self._logger.info("User %s added", (user_id, email))

    def insert_list(self, list_: str) -> int:
        self._cursor.execute("INSERT INTO list(list) VALUES (?)", (list_,))
        self._conn.commit()
        id_ = self._cursor.lastrowid
        self._logger.info("List '%s' added with id %s", list_, id_)
        return id_

    def update_list(self, list_id: int, new_list: str) -> None:
        self._cursor.execute("UPDATE list SET list=? WHERE id=?", (new_list, list_id))
        self._conn.commit()
        self._logger.info("List '%s' updated", (list_id, new_list))

    def get_email(self, user_id: int) -> str | None:
        res = self._cursor.execute(
            "SELECT email FROM user WHERE id=?", (user_id,))

        email = res.fetchone()
        if email is None:
            self._logger.info("User %s not found", user_id)
            return None

        self._logger.info("User %s fetched", (user_id, email[0]))
        return email[0]

    def get_list(self, list_id: int) -> str:
        res = self._cursor.execute(
            "SELECT list FROM list WHERE id=?", (list_id,))

        list_ = res.fetchone()
        if list_ is None:
            raise ValueError(f"List with id {list_id} not found")

        self._logger.info("List %s fetched", (list_id, list_[0]))
        return list_[0]


_db = DB(_logger)


async def start(update: Update, _: CallbackContext) -> None:
    await update.message.reply_text(textwrap.dedent("""
        بات ایمیل جمع کن
        دستور زیر را بزنید تا ایمیل شما ثبت شود:
        /register youremailhere

        بعد از ثبت ایمیل میتوانید در هر چتی از دستور زیر استفاده کنید تا یک لیست جدید در چت فرستاده شود:
        @autemailbot your list name here
    """))


async def register_email(update: Update, context: CallbackContext) -> None:
    if len(context.args) != 1:
        await update.message.reply_text(textwrap.dedent("""
            ایمیل خود را با یک فاصله بعد از دستور register وارد کنید:
            /register youremailhere
        """))
        return

    try:
        validation = validate_email(email=context.args[0], check_deliverability=True)
    except EmailNotValidError as e:
        await update.message.reply_text("ایمیل معتبر نیست.")
        _logger.exception("Email not valid", exc_info=e)
        return

    # if validation.domain != "aut.ac.ir":
    #     await update.message.reply_text("ایمیل متعلق به دانشگاه امیرکبیر نیست.")
    #     return

    _db.insert_user(update.effective_user.id, validation.email)
    await update.message.reply_text("ایمیل با موفقیت ثبت شد.")


def get_keyboard(list_id: int) -> InlineKeyboardMarkup:
    btn = InlineKeyboardButton(
        text="بیفزون‌ام",
        callback_data=f"add_mail_{list_id}",
    )
    return InlineKeyboardMarkup([[btn]])


async def create_list(update: Update, _: CallbackContext) -> None:
    list_title = update.inline_query.query
    if not list_title:
        return

    list_id = _db.insert_list(list_title)

    article = InlineQueryResultArticle(
        id=str(uuid.uuid4()),
        title=list_title,
        input_message_content=InputTextMessageContent(list_title),
        reply_markup=get_keyboard(list_id),
    )
    await update.inline_query.answer(
        results=[article],
        cache_time=0,
        switch_pm_text="help ❓",
        switch_pm_parameter="inline_help",
        auto_pagination=True,
    )


async def add_mail(update: Update, _: CallbackContext) -> None:
    query = update.callback_query
    user_id = query.from_user.id

    email = _db.get_email(user_id)
    if email is None:
        await query.answer("اول باید ایمیل را در بات @autemailbot ثبت کنید.", show_alert=True)
        _logger.info("User %s email not found", user_id)
        return

    list_id = int(query.data.removeprefix("add_mail_"))
    list_ = _db.get_list(list_id)

    if email in list_.splitlines():
        await query.answer("ایمیل شما قبلا اضافه شده است.", show_alert=True)
        return

    new_list = f"{list_}\n{email}"

    _db.update_list(list_id, new_list)

    await query.edit_message_text(
        text=new_list,
        reply_markup=get_keyboard(list_id),
    )
    await query.answer()


def main():
    token = os.getenv("MAIL_BOT_TOKEN")
    if not token:
        _logger.error("Token not found. Set MAIL_BOT_TOKEN environment variable.")
        sys.exit(1)

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register_email))
    app.add_handler(InlineQueryHandler(create_list))
    app.add_handler(CallbackQueryHandler(add_mail, pattern=r"^add_mail_\d+$"))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(app.bot.set_my_commands(
        [
            ("start", "راهنما"),
            ("register", "ثبت ایمیل"),
        ]
    ))

    app.run_polling()


if __name__ == "__main__":
    main()
