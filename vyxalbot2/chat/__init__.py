from typing import Callable
from dataclasses import dataclass
from datetime import datetime
from string import ascii_letters

import re
import random
import codecs

from aiohttp import ClientSession
from tinydb.table import Document
from sechat.room import Room
from sechat.events import MessageEvent, EditEvent
from uwuivy import uwuipy

from ..types import PublicConfigType, MessagesType
from .parser import CommandParser, ParseError
from ..userdb import UserDB

@dataclass
class User:
    name: str
    ident: int

class Chat:
    def __init__(self, room: Room, userDB: UserDB, config: PublicConfigType, messages: MessagesType, statuses: list[str]):
        self.room = room
        self.userDB = userDB
        self.config = config
        self.messages = messages
        self.statuses = statuses

        self.session = ClientSession()

        self.editDB: dict[int, tuple[datetime, list[int]]] = {}
        self.commands: dict[str, Callable] = {a: b async for a, b in self.getCommands()}
        self.parser = CommandParser(self.commands)
        self.errorsSinceStartup = 0
        self.startupTime = datetime.now()

    async def getCommands(self):
        for attrName in self.__dir__():
            attr = getattr(self, attrName)
            if not callable(attr):
                continue
            if not attr.__name__.lower().endswith("command"):
                continue
            yield re.sub(r"([A-Z])", lambda match: " " + match.group(0).lower(), attr.__name__), attr

    async def onMessage(self, message: MessageEvent):
        if message.user_id == self.room.userID:
            return
        if not message.content.startswith("!!/"):
            return
        sentAt = datetime.now()
        response = [i async for i in self.processMessage(message.content.removeprefix("!!/"), User(message.user_name, message.user_id))]
        responseIDs = [await self.room.reply(message.message_id, response[0])]
        for line in response[1:]:
            responseIDs.append(await self.room.send(line))
        self.editDB[message.message_id] = (sentAt, responseIDs)

    async def onEdit(self, edit: EditEvent):
        if edit.user_id == self.room.userID:
            return
        if not edit.content.startswith("!!/"):
            return
        if edit.message_id not in self.editDB:
            await self.onMessage(edit)
        else:
            sentAt, idents = self.editDB[edit.message_id]
            if (datetime.now() - sentAt).seconds > (60 * 2): # margin of error
                await self.onMessage(edit)
                return
            response = [i async for i in self.processMessage(edit.content.removeprefix("!!/"), User(edit.user_name, edit.user_id))]
            response[0] += f":{edit.message_id} "
            for x in range(min(len(idents), len(response))):
                await self.room.edit(idents.pop(0), response.pop(0))
            for leftover in response:
                await self.room.send(leftover)
            for leftover in idents:
                await self.room.delete(leftover)
            self.editDB.pop(edit.message_id)

    async def processMessage(self, message: str, user: User):
        try:
            commandName, impl, args = self.parser.parseCommand(message)
        except ParseError as e:
            yield e.message
            return
        userInfo = self.userDB.getUserInfo(user.ident)
        for groupName, group in self.config["groups"].items():
            if commandName in group.get("canRun", []):
                if userInfo is not None:
                    if groupName not in userInfo["groups"]:
                        yield f"Only members of group {groupName} can run !!/{commandName}"
                        return
                else:
                    yield f"Only members of group {groupName} can run !!/{commandName}"
                    return
        async for l in impl(user, *args):
            yield l

    async def dieCommand(self, user: User):
        exit(-42)

    async def helpCommand(self, user: User, command: str = ""):
        if command:
            if command == "me":
                yield "I'd love to, but I don't have any limbs."
            else:
                if command in self.messages["commandhelp"]:
                    yield self.messages["commandhelp"][command]
                else:
                    yield "No help is available for that command."
        else:
            yield self.messages["help"] + ", ".join(map(lambda i: i.split(" ")[0], self.commands.keys()))

    async def infoCommand(self, user: User):
        yield self.messages["info"]

    def status(self):
        return (
            f"Bot status: Online\n"
            f"Uptime: {datetime.now() - self.startupTime}\n"
            f"Running since: {self.startupTime.isoformat()}\n"
            f"Errors since startup: {self.errorsSinceStartup}"
        )

    async def statusCommand(self, user: User):
        status = random.choice(self.statuses)
        if not status.endswith(".") and status.endswith(ascii_letters):
            status += "."
        else:
            status = status.removesuffix(";")
        yield status

    async def statusBoringCommand(self, user: User):
        yield self.status()
    
    async def statusExcitingCommand(self, user: User):
        yield "\n".join(map(lambda line: line + ("!" * random.randint(2, 5)), self.status().upper().splitlines()))

    async def statusTinglyCommand(self, user: User):
        uwu = uwuipy(None, 0.3, 0.2, 0.2, 1)  # type: ignore Me when the developers of uwuipy don't annotate their types correctly
        yield uwu.uwuify(self.status())

    async def statusSleepyCommand(self, user: User):
        status = self.status()
        yield (
            "\n".join(status.splitlines())[:random.randint(1, len(status.splitlines()))]
            + " *yawn*\n"
            + "z" * random.randint(5, 10)
        )

    async def statusCrypticCommand(self, user: User):
        yield codecs.encode(self.status(), "rot13")

    async def statusGoofyCommand(self, user: User):
        yield "\n".join(map(lambda line: line + "🤓" * random.randint(1, 3), self.status().splitlines()))

    def getPermissionsTarget(self, sender: User, name: str) -> Document | str:
        if name == "me":
            target = self.userDB.getUserInfo(sender.ident)
            if target is None:
                return "You are not in my database. Please run !!/register."
        else:
            target = self.userDB.getUserInfoByName(name)
            if target is None:
                return "I don't know any user by that name."
        return target

    async def permissionsListCommand(self, user: User, name: str):
        if isinstance(target := self.getPermissionsTarget(user, name), str):
            yield target
            return
        yield f"User {target['name']} is a member of groups {', '.join(target['groups'])}."

    def permissionsModify(self, user: User, name: str, group: str, grant: bool):
        if isinstance(target := self.getPermissionsTarget(user, name), str):
            yield target
            return
        sender = self.userDB.getUserInfo(user.ident)
        if sender is None:
            yield "You are not in my database. Please run !!/register."
            return
        group = group.removesuffix("s")
        try:
            promotionRequires = self.config["groups"][group].get("promotionRequires", [])
        except KeyError:
            yield "That group does not exist."
            return
        if (not any([i in promotionRequires for i in sender["groups"]])) and len(promotionRequires):
            yield "Insufficient permissions."
            return
        if grant:
            if self.userDB.addUserToGroup(target, group):
                yield f"Added {target['name']} to {group}."
            else:
                yield f"{target['name']} is already a member of {group}."
        else:
            self.userDB.removeUserFromGroup(target, group)
            yield f"{target['name']} removed from {group}."

    async def permissionsGrantCommand(self, user: User, name: str, group: str):
        for line in self.permissionsModify(user, name, group, True):
            yield line
    async def permissionsRevokeCommand(self, user: User, name: str, group: str):
        for line in self.permissionsModify(user, name, group, False):
            yield line

    async def registerCommand(self, user: User):
        if self.userDB.getUserInfo(user.ident):
            yield "You are already registered. If your details are out of date, run !!/refresh."
            return
        self.userDB.addUserToDatabase(
            await (
                await self.session.get(
                    f"https://chat.stackexchange.com/users/thumbs/{user.ident}"
                )
            ).json()
        )
        yield "You have been registered! You don't have any permisssions yet."

    async def refreshCommand(self, user: User):
        if self.userDB.getUserInfo(user.ident) is None:
            yield "You are not in my database. Please run !!/register."
            return
        self.userDB.refreshUserData(
            await (
                await self.session.get(
                    f"https://chat.stackexchange.com/users/thumbs/{user.ident}"
                )
            ).json()
        )
        yield "Your details have been updated."

    async def groupsListCommand(self, user: User):
        yield "All groups: " + ", ".join(self.config['groups'].keys())
    async def groupsMembersCommand(self, user: User, group: str):
        group = group.removesuffix("s")
        yield f"Members of {group}: " + ', '.join(map(lambda i: i['name'], self.userDB.membersOfGroup(group)))

    async def pingCommand(self, user: User, group: str, message: str):
        group = group.removesuffix("s")
        pings = " ".join(["@" + target["name"] for target in self.userDB.membersOfGroup(group) if target["id"] != user.ident])
        if not len(pings):
            yield "Nobody to ping."
        else:
            yield pings + " ^"