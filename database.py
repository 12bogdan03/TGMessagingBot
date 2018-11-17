from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

import config

engine = create_engine(config.DATABASE_URI, connect_args={'check_same_thread': False})

Base = declarative_base()

Session = sessionmaker(bind=engine)
session = Session()
