from aiohttp import web
from .app import create_app
from .config import Config

config = Config()
web.run_app(create_app(config), host=config.host, port=config.port, access_log=None, print=None)
