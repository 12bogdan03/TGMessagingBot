import uuid
import datetime
import os

from telethon import TelegramClient
from telegram import ParseMode, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (CommandHandler, Updater, MessageHandler,
                          Filters, CallbackQueryHandler, ConversationHandler)

import config
from models import Token, User, TelegramSession, Task, TelegramGroup
from database import session
from telegram_svc import restricted, error_callback, build_menu, token_needed

updater = Updater(token=config.TELEGRAM_TOKEN)
dispatcher = updater.dispatcher

# Conversation states
LOGIN_CODE, SELECT_ACCOUNT, MESSAGE, INTERVAL, LIST_GROUPS, \
    SELECT_GROUPS, START_TASK, SELECT_TASK, TASK_MENU, EDIT_MESSAGE, \
    EDIT_INTERVAL, EDIT_GROUPS = range(12)


def start(bot, update):
    user = session.query(User).filter(
        User.tg_id == update.message.chat_id
    ).first()
    if not user:
        user = User(tg_id=update.message.chat_id)
        session.add(user)
        session.commit()
    update.message.reply_text("Hello, @{} "
                              "[<code>{}</code>]".format(update.message.from_user.username,
                                                         update.message.chat_id),
                              parse_mode=ParseMode.HTML)


@restricted
def generate_token(bot, update, args):
    if len(args) == 1:
        token_value = str(uuid.uuid4().hex)
        valid_until = datetime.datetime.now() + datetime.timedelta(days=int(args[0]))
        valid_until_f = valid_until.strftime('%m.%d.%Y')

        token = Token(value=token_value, valid_until=valid_until.date())
        session.add(token)
        session.commit()

        update.message.reply_text("Here is the new token: \n\n"
                                  "```{}```\n\n"
                                  "Valid until: `{}`".format(token_value, valid_until_f),
                                  parse_mode=ParseMode.MARKDOWN)
    else:
        update.message.reply_text("Please, send me the number of days "
                                  "the token will be valid.")\



@restricted
def list_valid_tokens(bot, update):
    tokens = session.query(Token).filter(
        Token.valid_until > datetime.date.today()
    ).all()
    if tokens:
        text = '*List of Tokens:*\n'
        for t in tokens:
            valid_until_f = t.valid_until.strftime('%m.%d.%Y')
            text += '`{}` - till {}\n'.format(t.value, valid_until_f)

        update.message.reply_text(text,
                                  parse_mode=ParseMode.MARKDOWN)
    else:
        update.message.reply_text("There are no active tokens yet.")


def activate_token(bot, update, args):
    if len(args) == 1:
        token_input = args[0]
        token = session.query(Token).filter(
            Token.value == token_input
        ).first()

        if token and token.valid_until > datetime.date.today():
            user = session.query(User).filter(
                User.tg_id == update.message.chat_id
            ).first()
            user.token = token
            session.commit()
            valid_until_f = token.valid_until.strftime('%m.%d.%Y')
            update.message.reply_text("Congratulations! Your token is active "
                                      "until: `{}`".format(valid_until_f),
                                      parse_mode=ParseMode.MARKDOWN)
        else:
            update.message.reply_text("Your token is invalid.",
                                      parse_mode=ParseMode.MARKDOWN)
    else:
        update.message.reply_text("Please, send me the token.")


def cancel(bot, update):
    update.message.reply_text("Action cancelled.")
    return ConversationHandler.END


@token_needed
def add_account(bot, update, args, user_data):
    if len(args) == 1:
        phone_number = args[0]
        user = session.query(User).filter(
            User.tg_id == update.message.chat_id
        ).first()
        client = TelegramClient(os.path.join(config.TELETHON_SESSIONS_DIR, phone_number),
                                config.TELEGRAM_API_ID,
                                config.TELEGRAM_API_HASH)
        client.connect()

        result = client.send_code_request(phone_number, force_sms=True)
        client.disconnect()
        tg_session = TelegramSession(phone_number=phone_number,
                                     phone_code_hash=result.phone_code_hash,
                                     user=user)
        session.add(tg_session)
        session.commit()
        user_data['session_id'] = tg_session.id
        update.message.reply_text("Please, send the login code to continue")

        return LOGIN_CODE
    else:
        update.message.reply_text("Please, include the phone number to this "
                                  "command.")
        return ConversationHandler.END


@token_needed
def confirm_tg_account(bot, update, user_data):
    code = update.message.text
    tg_session = session.query(TelegramSession).filter(
        TelegramSession.id == int(user_data['session_id'])
    ).first()
    client = TelegramClient(os.path.join(config.TELETHON_SESSIONS_DIR,
                                         tg_session.phone_number),
                            config.TELEGRAM_API_ID,
                            config.TELEGRAM_API_HASH)
    client.connect()

    try:
        client.sign_in(tg_session.phone_number, code,
                       phone_code_hash=tg_session.phone_code_hash)
        tg_session.active = True
        update.message.reply_text('Account added successfully.')
    except Exception as e:
        update.message.reply_text('Error: {}.'.format(e))

    session.commit()

    client.disconnect()

    return ConversationHandler.END


@token_needed
def start_posting(bot, update):
    active_sessions = session.query(TelegramSession).filter(
        TelegramSession.user_id == update.message.chat_id,
        bool(TelegramSession.active) is True
    ).order_by(TelegramSession.created_at).all()
    if active_sessions:
        buttons = [InlineKeyboardButton(s.phone_number, callback_data=s.id)
                   for s in active_sessions]
        if len(buttons) > 6:
            buttons = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]
            next_page_btn = InlineKeyboardButton('➡️', callback_data='next_page:1')
            buttons[0].append(next_page_btn)
            reply_markup = InlineKeyboardMarkup(build_menu(buttons[0], n_cols=2))
        else:
            reply_markup = InlineKeyboardMarkup(build_menu(buttons, n_cols=2))
        bot.send_message(chat_id=update.message.chat_id,
                         text='Please, choose the account or /cancel',
                         reply_markup=reply_markup,
                         timeout=30)
        return SELECT_ACCOUNT
    else:
        update.message.reply_text('You don\'t have any active accounts yet. '
                                  'Please, /add_account at first.')
        return ConversationHandler.END


@token_needed
def select_account(bot, update, user_data):
    query = update.callback_query

    if query.data.startswith('next_page') or query.data.startswith('prev_page'):
        active_sessions = session.query(TelegramSession).filter(
            TelegramSession.user_id == query.message.chat_id,
            bool(TelegramSession.active) is True
        ).order_by(TelegramSession.created_at).all()
        buttons = [InlineKeyboardButton(s.phone_number, callback_data=s.id)
                   for s in active_sessions]
        buttons = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]

        if query.data.startswith('next_page'):
            go_to_page = int(query.data.split(':')[1])

        else:
            go_to_page = int(query.data.split(':')[1])

        if go_to_page > 0:
            prev_page_btn = InlineKeyboardButton(
                '⬅️', callback_data='prev_page:{}'.format(go_to_page - 1)
            )
            buttons[go_to_page].append(prev_page_btn)
        if go_to_page < len(buttons) - 1:
            next_page_btn = InlineKeyboardButton(
                '➡️', callback_data='next_page:{}'.format(go_to_page + 1)
            )
            buttons[go_to_page].append(next_page_btn)

        reply_markup = InlineKeyboardMarkup(build_menu(buttons[go_to_page],
                                                       n_cols=2))

        bot.edit_message_reply_markup(chat_id=query.message.chat_id,
                                      message_id=query.message.message_id,
                                      reply_markup=reply_markup,
                                      timeout=30)

        return SELECT_ACCOUNT

    else:
        account = session.query(TelegramSession).filter(
            TelegramSession.id == int(query.data),
        ).first()

        task = Task(user=account.user, session=account)
        session.add(task)
        session.commit()
        user_data['task_id'] = task.id
        bot.edit_message_text(chat_id=query.message.chat_id,
                              message_id=query.message.message_id,
                              text='Great! Now send me the message text.',
                              timeout=30)
        return MESSAGE


@token_needed
def message(bot, update, user_data):
    text = update.message.text
    task = session.query(Task).filter(
        Task.id == user_data['task_id'],
    ).first()
    task.message = text
    session.commit()
    update.message.reply_text('Now send the interval to post the message '
                              '(in minutes).')
    return INTERVAL


@token_needed
def interval(bot, update, user_data):
    value = update.message.text
    if value.isdigit():
        task = session.query(Task).filter(
            Task.id == user_data['task_id'],
        ).first()
        task.interval = int(value)
        session.commit()

        client = TelegramClient(os.path.join(config.TELETHON_SESSIONS_DIR,
                                             task.session.phone_number),
                                config.TELEGRAM_API_ID,
                                config.TELEGRAM_API_HASH)
        client.connect()
        dialogs = client.get_dialogs()
        client.disconnect()
        groups = [{'id': i.id, 'title': i.title}
                  for i in dialogs if i.is_group]
        # groups = [{'id': i, 'title': 'Group ' + str(i)}
        #           for i in range(20)]
        user_data['groups'] = groups
        if groups:
            buttons = [InlineKeyboardButton(g['title'], callback_data=g['id'])
                       for g in groups]
            if len(buttons) > 6:
                buttons = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]
                next_page_btn = InlineKeyboardButton('➡️', callback_data='next_page:1')
                save_all_btn = InlineKeyboardButton('SAVE ALL ️', callback_data='save_all')
                buttons[0].append(save_all_btn)
                buttons[0].append(next_page_btn)
                reply_markup = InlineKeyboardMarkup(build_menu(buttons[0], n_cols=2))
            else:
                reply_markup = InlineKeyboardMarkup(build_menu(buttons, n_cols=2))
            user_data['page'] = 0
            bot.send_message(chat_id=update.message.chat_id,
                             text='Please, choose groups by clicking on them or '
                                  'just press `SAVE ALL` to select all.',
                             parse_mode=ParseMode.MARKDOWN,
                             reply_markup=reply_markup,
                             timeout=30)
            return SELECT_GROUPS
        else:
            update.message.reply_text('This account doesn\'t have any groups. '
                                      'Try using another account via /start_posting')
            task.delete()
            session.commit()
            return ConversationHandler.END
    else:
        update.message.reply_text('Oops! Interval has to be integer '
                                  'value (in minutes). Send me another '
                                  'interval.')
        return INTERVAL


@token_needed
def select_groups(bot, update, user_data):
    task = session.query(Task).filter(
        Task.id == user_data['task_id'],
    ).first()

    query = update.callback_query

    save_all_btn = InlineKeyboardButton('SAVE ALL️', callback_data='save_all')
    save_btn = InlineKeyboardButton('SAVE SELECTED️', callback_data='save')

    start_task_buttons = [[InlineKeyboardButton('YES️ ✅', callback_data=1),
                          InlineKeyboardButton('NO ❌', callback_data=0)]]
    start_task_markup = InlineKeyboardMarkup(start_task_buttons)

    if query.data == 'save_all':
        for g in user_data['groups']:
            tg_group = TelegramGroup(title=g['title'],
                                     tg_id=g['id'],
                                     task=task)
            session.add(tg_group)
        session.commit()
        bot.edit_message_text(chat_id=query.message.chat_id,
                              message_id=query.message.message_id,
                              text='Great! Should I start this task now?',
                              reply_markup=start_task_markup,
                              timeout=30)
        return START_TASK
    elif query.data == 'save':
        bot.edit_message_text(chat_id=query.message.chat_id,
                              message_id=query.message.message_id,
                              text='Great! Should I start this task now?',
                              reply_markup=start_task_markup,
                              timeout=30)
        return START_TASK
    elif query.data.startswith('next_page') or query.data.startswith('prev_page'):
        task_groups = session.query(TelegramGroup).filter(
            TelegramGroup.task == task
        ).all()
        task_groups_ids = [g.tg_id for g in task_groups]
        buttons = [InlineKeyboardButton('✔️ '+g['title'], callback_data=str(g['id'])+'+')
                   if g['id'] in task_groups_ids else
                   InlineKeyboardButton(g['title'], callback_data=g['id'])
                   for g in user_data['groups']]
        buttons = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]

        if query.data.startswith('next_page'):
            go_to_page = int(query.data.split(':')[1])
        else:
            go_to_page = int(query.data.split(':')[1])

        user_data['page'] = go_to_page

        if go_to_page > 0:
            prev_page_btn = InlineKeyboardButton(
                '⬅️', callback_data='prev_page:{}'.format(go_to_page - 1)
            )
            buttons[go_to_page].append(prev_page_btn)
        if go_to_page < len(buttons) - 1:
            next_page_btn = InlineKeyboardButton(
                '➡️', callback_data='next_page:{}'.format(go_to_page + 1)
            )
            buttons[go_to_page].append(next_page_btn)

        buttons[go_to_page].append(save_all_btn)
        if task_groups:
            buttons[go_to_page].append(save_btn)

        user_data['page'] = go_to_page

        reply_markup = InlineKeyboardMarkup(build_menu(buttons[go_to_page],
                                                       n_cols=2))

        bot.edit_message_reply_markup(chat_id=query.message.chat_id,
                                      message_id=query.message.message_id,
                                      reply_markup=reply_markup,
                                      timeout=30)
        return SELECT_GROUPS
    else:
        if query.data.endswith('+'):
            tg_group = session.query(TelegramGroup).filter(
                            TelegramGroup.task == task,
                            TelegramGroup.tg_id == int(query.data.strip('+'))
                        ).first()
            session.delete(tg_group )
            session.commit()
        else:
            title = next(i['title'] for i in user_data['groups']
                         if i['id'] == int(query.data))
            tg_group = TelegramGroup(title=title,
                                     tg_id=int(query.data),
                                     task=task)
            session.add(tg_group)
            session.commit()
        task_groups = session.query(TelegramGroup).filter(
            TelegramGroup.task == task
        ).all()
        task_groups_ids = [g.tg_id for g in task_groups]
        buttons = [InlineKeyboardButton('✔️ ' + g['title'], callback_data=str(g['id'])+'+')
                   if g['id'] in task_groups_ids else
                   InlineKeyboardButton(g['title'], callback_data=g['id'])
                   for g in user_data['groups']]
        buttons = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]

        current_page = user_data['page']

        if current_page > 0:
            prev_page_btn = InlineKeyboardButton(
                '⬅️', callback_data='prev_page:{}'.format(current_page - 1)
            )
            buttons[current_page].append(prev_page_btn)
        if current_page < len(buttons)-1:
            next_page_btn = InlineKeyboardButton(
                '➡️', callback_data='next_page:{}'.format(current_page + 1)
            )
            buttons[current_page].append(next_page_btn)

        buttons[current_page].append(save_all_btn)

        if task_groups:
            buttons[current_page].append(save_btn)

        reply_markup = InlineKeyboardMarkup(build_menu(buttons[current_page],
                                                       n_cols=2))

        bot.edit_message_reply_markup(chat_id=query.message.chat_id,
                                      message_id=query.message.message_id,
                                      reply_markup=reply_markup,
                                      timeout=30)
        return SELECT_GROUPS


@token_needed
def start_task(bot, update, user_data):
    task = session.query(Task).filter(
        Task.id == user_data['task_id'],
    ).first()

    query = update.callback_query

    if int(query.data):
        task.active = True
        session.commit()
        reply = 'Task is active now.'
    else:
        reply = 'Task is disabled.'
    bot.edit_message_text(chat_id=query.message.chat_id,
                          message_id=query.message.message_id,
                          text=reply,
                          reply_markup=None,
                          timeout=30)
    return ConversationHandler.END


def my_tasks(bot, update):
    tasks = session.query(Task).filter(
        Task.user_id == update.message.chat_id,
        Task.message != None,
        Task.interval != None,
        Task.session_id != None
    ).all()

    if tasks:
        active_emoji = '🔵'
        unactive_emoji = '🔴'
        buttons = [InlineKeyboardButton(
            'Task[{}..]{}'.format(t.session.phone_number[:5],
                                  active_emoji if t.active else unactive_emoji),
            callback_data=t.id) for t in tasks]
        # buttons = [InlineKeyboardButton('Task[{}..]'.format(t),
        #                                 callback_data=t)
        #            for t in range(20)]
        if len(buttons) > 6:
            buttons = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]
            next_page_btn = InlineKeyboardButton('➡️', callback_data='tasks_next_page:1')
            buttons[0].append(next_page_btn)
            reply_markup = InlineKeyboardMarkup(build_menu(buttons[0], n_cols=2))
        else:
            reply_markup = InlineKeyboardMarkup(build_menu(buttons, n_cols=2))
        bot.send_message(chat_id=update.message.chat_id,
                         text='Please, choose the task or /cancel',
                         reply_markup=reply_markup,
                         timeout=30)
        return SELECT_TASK
    else:
        update.message.reply_text('You don\'t have any tasks yet. '
                                  'Please, /start_posting at first.')
        return ConversationHandler.END


def select_task(bot, update, user_data):
    query = update.callback_query

    if query.data.startswith('tasks_next_page') or \
            query.data.startswith('tasks_prev_page'):
        tasks = session.query(Task).filter(
            Task.user_id == query.message.chat_id,
            Task.message != None,
            Task.interval != None,
            Task.session_id != None
        ).all()
        active_emoji = '🔵'
        unactive_emoji = '🔴'
        buttons = [InlineKeyboardButton(
            'Task[{}..]{}'.format(t.session.phone_number[:5],
                                  active_emoji if t.active else unactive_emoji),
            callback_data=t.id
        ) for t in tasks]
        # buttons = [InlineKeyboardButton('Task[{}..]'.format(t),
        #                                 callback_data=t)
        #            for t in range(20)]
        buttons = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]

        if query.data.startswith('tasks_next_page'):
            go_to_page = int(query.data.split(':')[1])

        else:
            go_to_page = int(query.data.split(':')[1])

        if go_to_page > 0:
            prev_page_btn = InlineKeyboardButton(
                '⬅️', callback_data='tasks_prev_page:{}'.format(go_to_page - 1)
            )
            buttons[go_to_page].append(prev_page_btn)
        if go_to_page < len(buttons) - 1:
            next_page_btn = InlineKeyboardButton(
                '➡️', callback_data='tasks_next_page:{}'.format(go_to_page + 1)
            )
            buttons[go_to_page].append(next_page_btn)

        reply_markup = InlineKeyboardMarkup(build_menu(buttons[go_to_page],
                                                       n_cols=2))

        bot.edit_message_reply_markup(chat_id=query.message.chat_id,
                                      message_id=query.message.message_id,
                                      reply_markup=reply_markup,
                                      timeout=30)

        return SELECT_TASK

    else:
        task = session.query(Task).filter(
            Task.id == int(query.data)
        ).first()
        user_data['task_id'] = task.id
        if bool(task.active):
            change_state_btn = InlineKeyboardButton('STOP', callback_data='stop_task')
        else:
            change_state_btn = InlineKeyboardButton('START', callback_data='start_task')
        edit_message_btn = InlineKeyboardButton('Edit message',
                                                callback_data='edit_message')
        edit_interval_btn = InlineKeyboardButton('Edit interval',
                                                 callback_data='edit_interval')
        edit_groups_btn = InlineKeyboardButton('Edit groups',
                                               callback_data='edit_groups')
        buttons = [change_state_btn, edit_message_btn,
                   edit_interval_btn, edit_groups_btn]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons,
                                                       n_cols=2))
        bot.edit_message_text(chat_id=query.message.chat_id,
                              message_id=query.message.message_id,
                              text='Task [{}]\n'
                                   'Please, choose action or '
                                   '/cancel'.format(task.session.phone_number),
                              reply_markup=reply_markup,
                              timeout=30)
        return TASK_MENU


@token_needed
def task_menu(bot, update, user_data):
    query = update.callback_query

    task = session.query(Task).filter(
        Task.id == user_data['task_id']
    ).first()

    if query.data == 'start_task':
        task.active = True
        session.commit()
        bot.edit_message_text(chat_id=query.message.chat_id,
                              message_id=query.message.message_id,
                              text='Task activated!',
                              reply_markup=None,
                              timeout=30)
        return ConversationHandler.END
    elif query.data == 'stop_task':
        task.active = False
        session.commit()
        bot.edit_message_text(chat_id=query.message.chat_id,
                              message_id=query.message.message_id,
                              text='Task deactivated!',
                              reply_markup=None,
                              timeout=30)
        return ConversationHandler.END
    elif query.data == 'edit_message':
        bot.edit_message_text(chat_id=query.message.chat_id,
                              message_id=query.message.message_id,
                              text='Please, send me new message or /cancel',
                              reply_markup=None,
                              timeout=30)
        return EDIT_MESSAGE
    elif query.data == 'edit_interval':
        bot.edit_message_text(chat_id=query.message.chat_id,
                              message_id=query.message.message_id,
                              text='Please, send me the new interval '
                                   '(in minutes) or /cancel',
                              reply_markup=None,
                              timeout=30)
        return EDIT_INTERVAL
    elif query.data == 'edit_groups':
        client = TelegramClient(os.path.join(config.TELETHON_SESSIONS_DIR,
                                             task.session.phone_number),
                                config.TELEGRAM_API_ID,
                                config.TELEGRAM_API_HASH)
        client.connect()
        dialogs = client.get_dialogs()
        client.disconnect()
        groups = [{'id': i.id, 'title': i.title}
                  for i in dialogs if i.is_group]
        # groups = [{'id': i, 'title': 'Group ' + str(i)}
        #           for i in range(20)]
        user_data['groups'] = groups
        task_groups = session.query(TelegramGroup).filter(
            TelegramGroup.task == task
        ).all()
        task_groups_ids = [g.tg_id for g in task_groups]
        buttons = [InlineKeyboardButton('✔️ ' + g['title'],
                                        callback_data=str(g['id'])+'+edit')
                   if g['id'] in task_groups_ids else
                   InlineKeyboardButton(g['title'], callback_data=g['id'])
                   for g in user_data['groups']]
        if len(buttons) > 6:
            buttons = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]
            next_page_btn = InlineKeyboardButton('➡️',
                                                 callback_data='edit_groups_next_page:1')
            save_all_btn = InlineKeyboardButton('SAVE ALL️', callback_data='edit_save_all')
            save_btn = InlineKeyboardButton('SAVE SELECTED️', callback_data='edit_save')
            buttons[0].append(save_all_btn)
            buttons[0].append(save_btn)
            buttons[0].append(next_page_btn)
            reply_markup = InlineKeyboardMarkup(build_menu(buttons[0], n_cols=2))
        else:
            reply_markup = InlineKeyboardMarkup(build_menu(buttons, n_cols=2))
        user_data['page'] = 0
        bot.edit_message_text(chat_id=query.message.chat_id,
                              message_id=query.message.message_id,
                              text='Please, choose groups you want to send '
                                   'messages to or /cancel',
                              reply_markup=reply_markup,
                              timeout=30)
        return EDIT_GROUPS


def edit_message(bot, update, user_data):
    text = update.message.text
    task = session.query(Task).filter(
        Task.id == user_data['task_id'],
    ).first()
    task.message = text
    session.commit()
    update.message.reply_text('New message saved.')
    return ConversationHandler.END


def edit_interval(bot, update, user_data):
    value = update.message.text
    if value.isdigit():
        task = session.query(Task).filter(
            Task.id == user_data['task_id'],
        ).first()
        task.interval = int(value)
        session.commit()
        update.message.reply_text('Interval changed.')
    else:
        update.message.reply_text('You entered wrong value.')

    return ConversationHandler.END


def edit_groups(bot, update, user_data):
    task = session.query(Task).filter(
        Task.id == user_data['task_id'],
    ).first()

    query = update.callback_query

    save_all_btn = InlineKeyboardButton('SAVE ALL️', callback_data='edit_save_all')
    save_btn = InlineKeyboardButton('SAVE SELECTED️', callback_data='edit_save')

    if query.data == 'edit_save_all':
        # delete current groups
        current_groups = session.query(TelegramGroup).filter(
            TelegramGroup.task == task
        ).all()
        for g in current_groups:
            session.delete(g)
        session.commit()
        # add all
        for g in user_data['groups']:
            tg_group = TelegramGroup(title=g['title'],
                                     tg_id=g['id'],
                                     task=task)
            session.add(tg_group)
        session.commit()
        bot.edit_message_text(chat_id=query.message.chat_id,
                              message_id=query.message.message_id,
                              text='New list of groups saved.',
                              reply_markup=None,
                              timeout=30)
        return ConversationHandler.END
    elif query.data == 'edit_save':
        bot.edit_message_text(chat_id=query.message.chat_id,
                              message_id=query.message.message_id,
                              text='New list of groups saved.',
                              reply_markup=None,
                              timeout=30)
        return ConversationHandler.END
    elif query.data.startswith('edit_groups_next_page') or \
            query.data.startswith('edit_groups_prev_page'):
        task_groups = session.query(TelegramGroup).filter(
            TelegramGroup.task == task
        ).all()
        task_groups_ids = [g.tg_id for g in task_groups]
        buttons = [InlineKeyboardButton('✔️ ' + g['title'],
                                        callback_data=str(g['id'])+'+edit')
                   if g['id'] in task_groups_ids else
                   InlineKeyboardButton(g['title'], callback_data=g['id'])
                   for g in user_data['groups']]
        buttons = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]

        if query.data.startswith('edit_groups_next_page'):
            go_to_page = int(query.data.split(':')[1])
        else:
            go_to_page = int(query.data.split(':')[1])

        user_data['page'] = go_to_page

        if go_to_page > 0:
            prev_page_btn = InlineKeyboardButton(
                '⬅️', callback_data='edit_groups_prev_page:{}'.format(go_to_page - 1)
            )
            buttons[go_to_page].append(prev_page_btn)
        if go_to_page < len(buttons) - 1:
            next_page_btn = InlineKeyboardButton(
                '➡️', callback_data='edit_groups_next_page:{}'.format(go_to_page + 1)
            )
            buttons[go_to_page].append(next_page_btn)

        buttons[go_to_page].append(save_all_btn)
        if task_groups:
            buttons[go_to_page].append(save_btn)

        user_data['page'] = go_to_page

        reply_markup = InlineKeyboardMarkup(build_menu(buttons[go_to_page],
                                                       n_cols=2))

        bot.edit_message_reply_markup(chat_id=query.message.chat_id,
                                      message_id=query.message.message_id,
                                      reply_markup=reply_markup,
                                      timeout=30)
        return EDIT_GROUPS
    else:
        if query.data.endswith('+edit'):
            tg_group = session.query(TelegramGroup).filter(
                TelegramGroup.task == task,
                TelegramGroup.tg_id == int(query.data.strip('+edit'))
            ).first()
            session.delete(tg_group)
            session.commit()
        else:
            title = next(i['title'] for i in user_data['groups']
                         if i['id'] == int(query.data))
            tg_group = TelegramGroup(title=title,
                                     tg_id=int(query.data),
                                     task=task)
            session.add(tg_group)
            session.commit()
        task_groups = session.query(TelegramGroup).filter(
            TelegramGroup.task == task
        ).all()
        task_groups_ids = [g.tg_id for g in task_groups]
        buttons = [InlineKeyboardButton('✔️ ' + g['title'],
                                        callback_data=str(g['id'])+'+edit')
                   if g['id'] in task_groups_ids else
                   InlineKeyboardButton(g['title'], callback_data=g['id'])
                   for g in user_data['groups']]
        buttons = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]

        current_page = user_data['page']

        if current_page > 0:
            prev_page_btn = InlineKeyboardButton(
                '⬅️', callback_data='edit_groups_prev_page:{}'.format(current_page - 1)
            )
            buttons[current_page].append(prev_page_btn)
        if current_page < len(buttons) - 1:
            next_page_btn = InlineKeyboardButton(
                '➡️', callback_data='edit_groups_next_page:{}'.format(current_page + 1)
            )
            buttons[current_page].append(next_page_btn)

        buttons[current_page].append(save_all_btn)

        if task_groups:
            buttons[current_page].append(save_btn)

        reply_markup = InlineKeyboardMarkup(build_menu(buttons[current_page],
                                                       n_cols=2))

        bot.edit_message_reply_markup(chat_id=query.message.chat_id,
                                      message_id=query.message.message_id,
                                      reply_markup=reply_markup,
                                      timeout=30)
        return EDIT_GROUPS


new_tg_account_handler = ConversationHandler(
    entry_points=[CommandHandler('add_account', add_account,
                                 pass_args=True, pass_user_data=True)],
    states={
        LOGIN_CODE: [MessageHandler(Filters.text, confirm_tg_account,
                                    pass_user_data=True)]
    },
    fallbacks=[CommandHandler('cancel', cancel)]
)

start_posting_handler = ConversationHandler(
    entry_points=[CommandHandler('start_posting', start_posting)],
    states={
        SELECT_ACCOUNT: [CallbackQueryHandler(select_account, pass_user_data=True)],
        MESSAGE: [MessageHandler(Filters.text, message, pass_user_data=True)],
        INTERVAL: [MessageHandler(Filters.text, interval, pass_user_data=True)],
        SELECT_GROUPS: [CallbackQueryHandler(select_groups, pass_user_data=True)],
        START_TASK: [CallbackQueryHandler(start_task, pass_user_data=True)],
    },
    fallbacks=[CommandHandler('cancel', cancel)]
)

edit_tasks_handler = ConversationHandler(
    entry_points=[CommandHandler('my_tasks', my_tasks)],
    states={
        SELECT_TASK: [CallbackQueryHandler(select_task, pass_user_data=True)],
        TASK_MENU: [CallbackQueryHandler(task_menu, pass_user_data=True)],
        EDIT_MESSAGE: [MessageHandler(Filters.text, edit_message, pass_user_data=True)],
        EDIT_INTERVAL: [MessageHandler(Filters.text, edit_interval, pass_user_data=True)],
        EDIT_GROUPS: [CallbackQueryHandler(edit_groups, pass_user_data=True)],
    },
    fallbacks=[CommandHandler('cancel', cancel)]
)

dispatcher.add_handler(CommandHandler('start', start))
dispatcher.add_handler(CommandHandler('list_tokens', list_valid_tokens))
dispatcher.add_handler(CommandHandler('token', generate_token,
                                      pass_args=True))
dispatcher.add_handler(CommandHandler('activate', activate_token,
                                      pass_args=True))
dispatcher.add_handler(new_tg_account_handler)
dispatcher.add_handler(start_posting_handler)
dispatcher.add_handler(edit_tasks_handler)
dispatcher.add_error_handler(error_callback)
