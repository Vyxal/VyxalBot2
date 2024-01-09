from datetime import datetime
from enum import Enum
import inspect
import re
from string import ascii_letters

import codecs
import random
import subprocess
from typing import Any, AsyncGenerator, Callable, Self

from aiohttp import ClientSession
from uwuipy import uwuipy

from vyxalbot2.types import CommonData, EventInfo, MessagesType, PrivateConfigType
from vyxalbot2.userdb import UserDB
from vyxalbot2.util import RAPTOR


class StatusMood(Enum):
    MESSAGE = "message"
    BORING = "boring"
    EXCITING = "exciting"
    TINGLY = "tingly"
    SLEEPY = "sleepy"
    CRYPTIC = "cryptic"
    GOOFY = "goofy"


class CommonCommand(dict[str, Self]):
    def __init__(
        self, name: str, description: str, impl: Callable[..., AsyncGenerator[Any, None]]
    ):
        super().__init__()
        self.name = name
        self.description = description
        self.impl = impl

    def __hash__(self):
        return hash(self.name)

    @property
    def help(self):
        parameters = []
        for parameter in inspect.signature(self.impl).parameters.values():
            if parameter.name in ("event", "self"):
                continue
            if issubclass(parameter.annotation, Enum):
                typeString = "|".join(member.value for member in parameter.annotation)
                if parameter.default is not parameter.empty:
                    assert isinstance(parameter.default, parameter.annotation)
                    typeString += " = " + parameter.default.value
            else:
                typeString = parameter.annotation.__name__
            if parameter.default is not parameter.empty:
                parameters.append(f"[{parameter.name}: {typeString}]")
            else:
                parameters.append(f"<{parameter.name}: {typeString}>")
        return (
            (f"`!!/{self.name} " + " ".join(parameters)).strip() + "`: " + self.description
        )

class CommonCommands:
    def __init__(self, messages: MessagesType, statuses: list[str], userDB: UserDB, privateConfig: PrivateConfigType):
        self.messages = messages
        self.statuses = statuses
        self.userDB = userDB
        self.privateConfig = privateConfig
        self.startupTime = datetime.now()
        self.commands: dict[str, CommonCommand] = {}
        for attrName in self.__dir__():
            attr = getattr(self, attrName)
            if not (callable(attr) and hasattr(attr, "__name__")):
                continue
            if not attr.__name__.lower().endswith("command"):
                continue
            if attr.__doc__ is None:
                doc = "…"
            else:
                doc = attr.__doc__
            name = re.sub(
                r"([A-Z])",
                lambda match: " " + match.group(0).lower(),
                attr.__name__.removesuffix("Command"),
            )
            self.commands[name] = CommonCommand(name, doc, attr)

    async def dieCommand(self, event: EventInfo):
        exit(-42)

    async def infoCommand(self, event: EventInfo):
        yield self.messages["info"]

    def status(self):
        return (
            f"Bot status: Online\n"
            f"Uptime: {datetime.now() - self.startupTime}\n"
            f"Running since: {self.startupTime.isoformat()}\n"
            f"Errors since startup: ¯\\_(ツ)_/¯"
        )

    async def statusCommand(
        self, event: EventInfo, mood: StatusMood = StatusMood.MESSAGE
    ):
        """I will tell you what I'm doing (maybe)."""
        match mood:
            case StatusMood.MESSAGE:
                status = random.choice(self.statuses)
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
        yield random.choice(self.messages["hugs"])

    async def susCommand(self, event: EventInfo):
        """STOP POSTING ABOUT AMONG US"""
        yield "ඞ" * random.randint(8, 64)

    async def amilyxalCommand(self, event: EventInfo):
        yield f"You are {'' if (event.userIdent == 354515) != (random.random() <= 0.1) else 'not '}lyxal."

    async def blameCommand(self, event: EventInfo):
        yield f"It was {random.choice(await self.userDB.getUsers(event.service)).name}'s fault!"

    async def cookieCommand(self, event: EventInfo):
        """Bake a cookie. Maybe. You have to be worthy."""
        if info := (await self.userDB.getUser(event.service, event.userIdent)):
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
                self.privateConfig["tyxalInstance"] + "/deliterateify", data=code
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
