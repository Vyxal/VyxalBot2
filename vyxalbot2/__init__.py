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
from dateutil.parser import parse as parseDatetime
from uwuivy import uwuipy
from discord.utils import setup_logging
from motor.motor_asyncio import AsyncIOMotorClient
from vyxalbot2.commands.common import CommonCommands

from vyxalbot2.github import GitHubApplication
from vyxalbot2.reactions import Reactions
from vyxalbot2.services.discord import DiscordService, VBClient
from vyxalbot2.services.se import SEService
from vyxalbot2.userdb import UserDB
from vyxalbot2.types import CommonData, PublicConfigType, PrivateConfigType, MessagesType, AppToken

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

        with open(privateConfig["pem"], "r") as f:
            self.privkey = f.read()

    async def run(self):
        userDB = UserDB(AsyncIOMotorClient(self.privateConfig["mongoUrl"]), self.privateConfig["database"])

        ghApp = GitHubApplication(self.publicConfig, self.privkey, self.privateConfig["appID"], self.privateConfig["account"], self.privateConfig["webhookSecret"])

        common = CommonData(
            self.statuses,
            self.messages,
            self.publicConfig,
            self.privateConfig,
            0,
            datetime.now(),
            userDB,
            ghApp
        )
        reactions = Reactions(self.messages)
        self.se = await SEService.create(reactions, common)
        self.discord = await DiscordService.create(reactions, common)

        ghApp.on_shutdown.append(self.shutdown)
        return ghApp

    async def shutdown(self, _):
        await self.se.shutdown()
        await self.discord.shutdown()
        

def run():
    PUBLIC_CONFIG_PATH = os.environ.get("VYXALBOT_CONFIG_PUBLIC", "config.json")
    PRIVATE_CONFIG_PATH = os.environ.get("VYXALBOT_CONFIG_PRIVATE", "private.json")
    STORAGE_PATH = os.environ.get("STORAGE_PATH", "storage.json")
    DATA_PATH = Path(__file__).resolve().parent.parent / "data"
    MESSAGES_PATH = DATA_PATH / "messages.toml"
    STATUSES_PATH = DATA_PATH / "statuses.txt"

    setup_logging()

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
        STORAGE_PATH,
        statuses,
    )
    run_app(app.run(), port=privateConfig["port"])