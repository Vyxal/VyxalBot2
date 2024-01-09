from typing import cast, Any
from datetime import datetime
from pathlib import Path

import logging
import json
import os

from aiohttp.web import run_app
from discord.utils import setup_logging
from motor.motor_asyncio import AsyncIOMotorClient
from sechat import Bot

import tomli
from vyxalbot2.commands import CommonCommands

from vyxalbot2.github import GitHubApplication, VyGitHubAPI
from vyxalbot2.reactions import Reactions
from vyxalbot2.clients.discord import DiscordClient
from vyxalbot2.clients.se import SEClient
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
        common = CommonCommands(self.messages, self.statuses, userDB, self.privateConfig)
        gh = VyGitHubAPI(
            self.privateConfig["appID"],
            self.privkey,
            self.privateConfig["account"],
        )
        ghApp = GitHubApplication(
            self.publicConfig,
            gh,
            self.privateConfig["webhookSecret"],
        )
        reactions = Reactions(self.messages, common, self.privateConfig["chat"]["ignore"])

        self.seBot = Bot()
        await self.seBot.authenticate(
            self.privateConfig["chat"]["email"],
            self.privateConfig["chat"]["password"],
            self.privateConfig["chat"]["host"],
        )
        room = await self.seBot.joinRoom(self.privateConfig["chat"]["room"])
        self.se = SEClient(room, userDB, self.publicConfig, self.privateConfig, gh)
        self.discord = DiscordClient(self.privateConfig["discord"]["guild"], common, reactions, self.messages, self.statuses)

        ghApp.on_shutdown.append(self.shutdown)
        return ghApp

    async def shutdown(self, _):
        await self.seBot.closeAllRooms()
        await self.discord.close()


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
