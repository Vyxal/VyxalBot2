from datetime import datetime
from enum import Enum
from string import ascii_letters

import codecs
import random
import subprocess

from aiohttp import ClientSession
from uwuipy import uwuipy

from vyxalbot2.commands import CommandSupplier
from vyxalbot2.types import CommonData, EventInfo
from vyxalbot2.util import RAPTOR


class StatusMood(Enum):
    MESSAGE = "message"
    BORING = "boring"
    EXCITING = "exciting"
    TINGLY = "tingly"
    SLEEPY = "sleepy"
    CRYPTIC = "cryptic"
    GOOFY = "goofy"


class CommonCommands(CommandSupplier):
    def __init__(self, common: CommonData):
        super().__init__()
        self.common = common

    async def dieCommand(self, event: EventInfo):
        exit(-42)

    async def infoCommand(self, event: EventInfo):
        yield self.common.messages["info"]

    def status(self):
        return (
            f"Bot status: Online\n"
            f"Uptime: {datetime.now() - self.common.startupTime}\n"
            f"Running since: {self.common.startupTime.isoformat()}\n"
            f"Errors since startup: {self.common.errorsSinceStartup}"
        )

    async def statusCommand(
        self, event: EventInfo, mood: StatusMood = StatusMood.MESSAGE
    ):
        """I will tell you what I'm doing (maybe)."""
        match mood:
            case StatusMood.MESSAGE:
                status = random.choice(self.common.statuses)
                if not status.endswith(".") and status.endswith(tuple(ascii_letters)):
                    status += "."
                else:
                    status = status.removesuffix(";")
                yield status
            case StatusMood.BORING:
                yield self.status()
            case StatusMood.EXCITING:
                yield "\n".join(
                    map(
                        lambda line: line + ("!" * random.randint(2, 5)),
                        self.status().upper().splitlines(),
                    )
                )
            case StatusMood.TINGLY:
                uwu = uwuipy(None, 0.3, 0.2, 0.2, 1)  # type: ignore Me when the developers of uwuipy don't annotate their types correctly
                yield uwu.uwuify(self.status())
            case StatusMood.SLEEPY:
                status = self.status()
                yield (
                    "\n".join(status.splitlines())[
                        : random.randint(1, len(status.splitlines()))
                    ]
                    + " *yawn*\n"
                    + "z" * random.randint(5, 10)
                )
            case StatusMood.CRYPTIC:
                yield codecs.encode(self.status(), "rot13")
            case StatusMood.GOOFY:
                yield "\n".join(
                    map(
                        lambda line: line + "🤓" * random.randint(1, 3),
                        self.status().splitlines(),
                    )
                )

    async def coffeeCommand(self, event: EventInfo, target: str = "me"):
        """Brew some coffee."""
        if target == "me" or not len(target):
            yield "☕"
        else:
            yield f"@{target} ☕"

    async def maulCommand(self, event: EventInfo, target: str):
        """Summon the raptors."""
        if target.lower().removesuffix("2") == "vyxalbot" or target == "me":
            yield RAPTOR.format(user=event.userName)
        else:
            yield RAPTOR.format(user=target)

    async def hugCommand(self, event: EventInfo):
        """<3"""
        yield random.choice(self.common.messages["hugs"])

    async def susCommand(self, event: EventInfo):
        """STOP POSTING ABOUT AMONG US"""
        yield "ඞ" * random.randint(8, 64)

    async def amilyxalCommand(self, event: EventInfo):
        yield f"You are {'' if (event.userIdent == 354515) != (random.random() <= 0.1) else 'not '}lyxal."

    async def blameCommand(self, event: EventInfo):
        yield f"It was {random.choice(await self.common.userDB.getUsers(event.service)).name}'s fault!"

    async def cookieCommand(self, event: EventInfo):
        """Bake a cookie. Maybe. You have to be worthy."""
        if info := (await self.common.userDB.getUser(event.service, event.userIdent)):
            if "admin" in info.groups:
                yield "Here you go: 🍪"
        else:
            if random.random() <= 0.75:
                yield "Here you go: 🍪"
            else:
                yield "No."

    async def deliterateifyCommand(self, event: EventInfo, code: str):
        """Convert literate code to sbcs"""
        async with ClientSession() as session:
            async with session.post(
                self.common.privateConfig["tyxalInstance"] + "/deliterateify", data=code
            ) as response:
                if response.status == 400:
                    yield f"Failed to deliterateify: {await response.text()}"
                elif response.status == 200:
                    yield f"`{await response.text()}`"
                else:
                    yield f"Tyxal sent back an error response! ({response.status})"

    # Add an alias
    async def delitCommand(self, event: EventInfo, code: str):
        async for line in self.deliterateifyCommand(event, code):
            yield line

    async def pullCommand(self, event: EventInfo):
        """Pull changes and restart."""
        if subprocess.run(["git", "pull"]).returncode == 0:
            yield "Restarting..."
            exit(-43)
        else:
            yield "Failed to pull!"

    async def commitCommand(self, event: EventInfo):
        """Check the commit the bot is running off of"""
        result = subprocess.run(
            ["git", "show", "--oneline", "-s", "--no-color"], capture_output=True
        )
        if result.returncode != 0:
            yield "Failed to get commit info!"
        else:
            yield f"Commit: {result.stdout.decode('utf-8').strip()}"
