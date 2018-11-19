## Telegram Messaging Bot

 - All the bot command hadlers are located in `telegram_bot.py`
 - Telethon sessions' files are saved to the `telethon_sessions/` folder in the base directory.
 - `telegram_svc.py`:
		 - def *restricted* - allows to use admins commands only by admins;
		 - def *token_needed* - allows only users with valid tokens to use the bot.
*Example of usage can be found at* `telegram_bot.py`.

To add new commands to the bot you can check `telegram_bot.py`  functions and simply write your command handlers and add them to dispatcher - `dispatcher.add_handler(your handler)`

## Installing bot on new server

1. Create virtual environment with Python 3.
2. Clone project code from Bitbucket.
3. Create .env file with all necessary configs (you can check `.env.example` for an example).
4.  Install supervisor and create `/etc/supervisor/conf.d/bot.conf` file with the following content:
		

        [program:bot]
        command=/home/user/TGMessagingBot/.venv/bin/python /home/user/TGMessagingBot/run.py
        directory=/home/user/TGMessagingBot
        autostart=true
        autorestart=false
        stderr_logfile=/home/user/TGMessagingBot/errors.log
        stdout_logfile=/home/user/TGMessagingBot/bot.log
        user=user
You should only replace pathes with the ones that you used at step 2 and 3.
Then execute `sudo supervisorctl reread`, `sudo supervisorctl update`, `sudo supervisorctl restart bot`. That's all.

**The next step is creating database.**
1. `sudo apt-get update`
2. `sudo apt-get install libpq-dev postgresql postgresql-contrib`
3. `sudo -u postgres psql`
4. `CREATE DATABASE telegram_bot;`
5. `CREATE USER myprojectuser WITH PASSWORD 'password';`
6. `ALTER ROLE myprojectuser SET client_encoding TO 'utf8';`
7. `ALTER ROLE myprojectuser SET default_transaction_isolation TO 'read committed';`
8. `ALTER ROLE myprojectuser SET timezone TO 'UTC';`
9. `GRANT ALL PRIVILEGES ON DATABASE telegram_bot TO myprojectuser;`
10. `\q`

Edit `.env` file:
```DATABASE_URI=postgresql://myprojectuser:password@localhost:5432/telegram_bot```


After this you need to activate virtual environment, that you've created before (`source /path/to/env/bin/activate`)
Change your working directory to the one, where the code is located, then execute `python`. Python console will launch.
    
`>> from database import Base, engine`

`>> from models import *`

`>> Base.metadata.create_all(engine)`

After these commands all the tables should exist in the database.

## Pushing updates
1. Push your changes to https://bitbucket.org/12bogdan03/tgmessagingbot/src/master/
2. Login to the server and move to the directory, where bot is located.
3. Execute `git pull bitbucket master`
4. Execute `sudo supervisorctl restart bot`

Done :)
