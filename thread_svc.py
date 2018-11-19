import time
import os
import threading
import datetime

import schedule
from telethon import TelegramClient
from telegram import Bot

from models import Token, User, TelegramSession, Task, TelegramGroup
from database import session
import config

bot = Bot(config.TELEGRAM_TOKEN)


def run_threaded(job_func, args=None):
    if args is None:
        job_thread = threading.Thread(target=job_func)
    else:
        job_thread = threading.Thread(target=job_func, args=args)
    job_thread.start()


def start_schedule():
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except Exception as e:
            config.logger.exception(e)


def send_message_to_group(client, message, group):
    client.send_message(group.tg_id, message)


def perform_task(task):
    groups = session.query(TelegramGroup).filter(
        TelegramGroup.task == task
    ).all()

    client = TelegramClient(os.path.join(config.TELETHON_SESSIONS_DIR, task.session.phone_number),
                            task.user.api_id if task.user.api_id else config.TELEGRAM_API_ID,
                            task.user.api_hash if task.user.api_hash else config.TELEGRAM_API_HASH)
    client.connect()
    try:
        for group in groups:
            send_message_to_group(client, task.message, group)
    except Exception as e:
        config.logger.exception(e)
        bot.send_message(task.user.tg_id,
                         'It seems like your account {0} is broken. Try '
                         'to /remove {0} it and /add_account '
                         '{0} again.'.format(task.session.phone_number))
        task.active = False

    task.last_message_date = datetime.datetime.now()
    session.commit()

    client.disconnect()


def posting_messages():
    active_tasks = session.query(Task).filter(
                       Task.active == True
                   ).all()
    deactivated_users = []
    if active_tasks:
        for task in active_tasks:

            if task.user in deactivated_users:
                continue

            token = task.user.token

            if token and token.valid_until >= datetime.date.today():
                if task.last_message_date != None:
                    delta = datetime.datetime.now() - task.last_message_date
                    seconds_passed = delta.total_seconds()
                    if seconds_passed > task.interval * 60:
                        perform_task(task)
                        groups = session.query(TelegramGroup).filter(
                            TelegramGroup.task == task
                        ).all()
                        bot.send_message(config.LOGS_GROUP_ID,
                                         'User [{}] task completed. Message sent to '
                                         '{} groups.'.format(task.user.tg_id,
                                                             len(groups)))
                    else:
                        continue
                else:
                    perform_task(task)
                    groups = session.query(TelegramGroup).filter(
                        TelegramGroup.task == task
                    ).all()
                    bot.send_message(config.LOGS_GROUP_ID,
                                     'User [{}] task completed. Message sent to '
                                     '{} groups.'.format(task.user.tg_id,
                                                         len(groups)))
            else:
                deactivated_users.append(task.user)
                session.query(Task).filter(
                    Task.user == task.user
                ).update({Task.active: False})
                session.commit()
                bot.send_message(chat_id=task.user.tg_id,
                                 text='Seems like your token is out of date.'
                                      'All tasks are deactivated.')
                bot.send_message(config.LOGS_GROUP_ID,
                                 'User [{}] token is invalid. All tasks '
                                 'deactivated.'.format(task.user.tg_id))
