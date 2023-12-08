from typing import cast, Any
from datetime import datetime
from pathlib import Path

import logging
import json
import os

from aiohttp.web import run_app
from discord.utils import setup_logging
from motor.motor_asyncio import AsyncIOMotorClient

import tomli

from vyxalbot2.github import GitHubApplication
from vyxalbot2.reactions import Reactions
from vyxalbot2.services.discord import DiscordService
from vyxalbot2.services.se import SEService
from vyxalbot2.userdb import UserDB
from vyxalbot2.types import (
    CommonData,
    PublicConfigType,
    PrivateConfigType,
    MessagesType,
)

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
        userDB = UserDB(
            AsyncIOMotorClient(self.privateConfig["mongoUrl"]),
            self.privateConfig["database"],
        )

        ghApp = GitHubApplication(
            self.publicConfig,
            self.privkey,
            self.privateConfig["appID"],
            self.privateConfig["account"],
            self.privateConfig["webhookSecret"],
        )
        reactions = Reactions(self.messages, self.privateConfig["chat"]["ignore"])

        common = CommonData(
            self.statuses,
            self.messages,
            self.publicConfig,
            self.privateConfig,
            0,
            datetime.now(),
            userDB,
            ghApp,
        )
        self.se = await SEService.create(reactions, common)
        self.discord = await DiscordService.create(reactions, common)
        ghApp.services.append(self.se)
        ghApp.services.append(self.discord)

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
