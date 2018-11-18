import datetime
from functools import wraps

from telegram.error import TelegramError

import config
from models import User
from database import session


def error_callback(bot, update, error):
    try:
        raise error
    except TelegramError as e:
        config.logger.exception(e)


def restricted(func):
    @wraps(func)
    def wrapped(bot, update, *args, **kwargs):
        user_id = update.effective_user.id
        admins = session.query(User).filter(
            User.is_admin == True
        ).all()
        admin_ids = [i.tg_id for i in admins]
        if user_id not in admin_ids:
            config.logger.warning("Unauthorized access denied "
                                  "for {}.".format(user_id))
            return
        return func(bot, update, *args, **kwargs)
    return wrapped


def token_needed(func):
    @wraps(func)
    def wrapped(bot, update, *args, **kwargs):
        user_id = update.effective_user.id
        user = session.query(User).filter(
            User.tg_id == user_id
        ).first()
        if user.token and user.token.valid_until > datetime.date.today():
            return func(bot, update, *args, **kwargs)
        else:
            update.message.reply_text('Your token is invalid. Please, /activate '
                                      'a new one.')
            config.logger.warning("User {} with invalid token "
                                  "denied.".format(user_id))
            return

    return wrapped


def build_menu(buttons, n_cols, header_buttons=None, footer_buttons=None):
    menu = [buttons[i:i + n_cols] for i in range(0, len(buttons), n_cols)]
    if header_buttons:
        menu.insert(0, header_buttons)
    if footer_buttons:
        menu.append(footer_buttons)
    return menu
