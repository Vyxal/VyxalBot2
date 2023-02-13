import json

from aiohttp.web import run_app

from vyxalbot2 import VyxalBot2

CONFIG_PATH = ""

with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

app = VyxalBot2(config)
run_app(app, port=config["port"])