import schedule

from telegram_bot import updater
from thread_svc import start_schedule, run_threaded, posting_messages


# schedule.every().second.do(posting_messages)
# run_threaded(start_schedule)

updater.start_polling()
