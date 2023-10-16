from typing import Callable
from dataclasses import dataclass
from datetime import datetime

import re

from sechat.room import Room
from sechat.events import MessageEvent, EditEvent

from .parser import CommandParser, ParseError
from ..userdb import UserDB

@dataclass
class User:
    name: str
    ident: int

class Chat(Room):
    def __init__(self, room: Room, userDB: UserDB):
        self.room = room
        self.userDB = userDB
        self.editDB: dict[int, tuple[datetime, list[int]]] = {}
        self.commands: dict[str, Callable] = {a: b async for a, b in self.getCommands()}
        self.parser = CommandParser(self.commands)

    async def getCommands(self):
        for attrName in self.__dir__():
            attr = getattr(self, attrName)
            if not callable(attr):
                continue
            if not attr.__name__.lower().endswith("command"):
                continue
            yield re.sub(r"([A-Z])", lambda match: " " + match.group(0).lower(), attr.__name__), attr

    async def onMessage(self, message: MessageEvent):
        if not message.content.startswith("!!/"):
            return
        sentAt = datetime.now()
        response = [i async for i in self.processMessage(message.content.removeprefix("!!/"), User(message.user_name, message.user_id))]
        responseIDs = [await self.room.reply(message.message_id, response[0])]
        for line in response[1:]:
            responseIDs.append(await self.room.send(line))
        self.editDB[message.message_id] = (sentAt, responseIDs)

    async def onEdit(self, edit: EditEvent):
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
            impl, args = self.parser.parseCommand(message)
        except ParseError as e:
            yield e.message
            return
        async for l in impl(user, *args):
            yield l
