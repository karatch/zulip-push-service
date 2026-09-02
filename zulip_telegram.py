import asyncio
import os
import configparser
import logging
from datetime import datetime
import aiohttp
import zulip

ZULIPRC_PATH = "zuliprc"

BOT_EMAIL = None
STREAM_NAME = None
client = None  # клиент Zulip

TELEGRAM_BOT_TOKEN = None