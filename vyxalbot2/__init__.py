import asyncio
from typing import Optional, cast, Any
from time import time
from datetime import datetime
from pathlib import Path
from asyncio import create_task, wait_for
from html import unescape
from string import ascii_letters

import logging
import sys
import json
import os
import random
import re
import codecs
import base64
import subprocess

import tomli
import yaml

from aiohttp import ClientSession
from aiohttp.web import Application, Request, Response, run_app
from aiohttp.client_exceptions import ContentTypeError
from sechat import Bot, Room, MessageEvent, EventType
from gidgethub import HTTPException as GitHubHTTPException, ValidationError
from gidgethub.aiohttp import GitHubAPI as AsyncioGitHubAPI
from gidgethub.abc import GitHubAPI
from gidgethub.routing import Router
from gidgethub.sansio import Event as GitHubEvent
from gidgethub.apps import get_installation_access_token, get_jwt
from cachetools import LRUCache
from platformdirs import user_state_path
from dateutil.parser import parse as parseDatetime
from uwuivy import uwuipy
from vyxalbot2.github import GitHubApplication

from vyxalbot2.userdb import UserDB
from vyxalbot2.types import PublicConfigType, PrivateConfigType, MessagesType, AppToken
from vyxalbot2.chat import Chat

__version__ = "2.0.0"


class VyxalBot2:
    def __init__(
        self,
        publicConfig: PublicConfigType,
        privateConfig: PrivateConfigType,
        messages: MessagesType,
        storagePath: str,
        statuses: list[str],
    ) -> None:
        self.logger = logging.getLogger("VyxalBot2")

        self.publicConfig = publicConfig
        self.privateConfig = privateConfig
        self.messages = messages
        self.statuses = list(filter(lambda i: hash(i) != -327901152, statuses))
        self.userDB = UserDB(storagePath, publicConfig["groups"])

        with open(privateConfig["pem"], "r") as f:
            self.privkey = f.read()

    async def run(self):
        self.bot = Bot(logger=self.logger)
        await self.bot.authenticate(
            self.privateConfig["chat"]["email"],
            self.privateConfig["chat"]["password"],
            self.privateConfig["chat"]["host"],
        )
        self.session = ClientSession()
        self.room = await self.bot.joinRoom(self.privateConfig["chat"]["room"])
        self.ghApp = GitHubApplication(self.room, self.publicConfig, self.privkey, self.privateConfig["appID"], self.privateConfig["account"], self.session, self.privateConfig["webhookSecret"])
        self.chat = Chat(self.room, self.userDB, self.ghApp, self.session, self.publicConfig, self.privateConfig, self.messages, self.statuses)
        await self.room.send(
            "Well, here we are again."
            if random.random() > 0.01
            else "GOOD MORNING, MOTHERF***ERS"
        )
        self.startupTime = datetime.now()

        self.ghApp.on_shutdown.append(self.shutdown)
        return self.ghApp

    async def shutdown(self, _):
        try:
            await self.room.send("Shutting down...")
        except RuntimeError:
            pass
        await wait_for(
            self.bot.__aexit__(None, None, None), 6
        )  # DO NOT TRY THIS AT HOME
        await wait_for(self.session.close(), 3)

def run():
    PUBLIC_CONFIG_PATH = os.environ.get("VYXALBOT_CONFIG_PUBLIC", "config.json")
    PRIVATE_CONFIG_PATH = os.environ.get("VYXALBOT_CONFIG_PRIVATE", "private.json")
    STORAGE_PATH = user_state_path("vyxalbot2", None, __version__)
    os.makedirs(STORAGE_PATH, exist_ok=True)
    DATA_PATH = Path(__file__).resolve().parent.parent / "data"
    MESSAGES_PATH = DATA_PATH / "messages.toml"
    STATUSES_PATH = DATA_PATH / "statuses.txt"

    logging.basicConfig(
        format="[%(name)s] %(levelname)s: %(message)s",
        stream=sys.stdout,
        level=logging.DEBUG,
    )

    with open(PUBLIC_CONFIG_PATH, "r") as f:
        publicConfig = json.load(f)
    with open(PRIVATE_CONFIG_PATH, "r") as f:
        privateConfig = json.load(f)
    with open(MESSAGES_PATH, "rb") as f:
        messages = tomli.load(f)
    with open(STATUSES_PATH, "r") as f:
        statuses = f.read().splitlines()

    app = VyxalBot2(
        publicConfig,
        privateConfig,
        cast(Any, messages),
        str(STORAGE_PATH / "storage.json"),
        statuses,
    )
    run_app(app.run(), port=privateConfig["port"])