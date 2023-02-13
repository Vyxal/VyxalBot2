import json
import logging
import sys
import asyncio

from aiohttp.web import run_app

from vyxalbot2 import VyxalBot2

CONFIG_PATH = "config.json"

logging.basicConfig(
    format="[%(name)s] %(levelname)s: %(message)s",
    stream=sys.stdout,
    level=logging.DEBUG,
)


with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

async def makeApp():
    return VyxalBot2(config)

run_app(makeApp(), port=config["port"])