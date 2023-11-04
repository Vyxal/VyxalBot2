from datetime import datetime
from typing import cast
from urllib.parse import urlparse, urlunparse

import random
import logging

from aiohttp import ClientSession
from bs4 import BeautifulSoup, Tag
from sechat import Bot, EventType
from sechat.room import Room
from sechat.events import MessageEvent, EditEvent
from markdownify import MarkdownConverter

from vyxalbot2.commands.se import SECommands

from vyxalbot2.reactions import Reactions
from vyxalbot2.services import PinThat, Service
from vyxalbot2.services.se.parser import CommandParser, ParseError
from vyxalbot2.types import CommonData, EventInfo
from vyxalbot2.util import resolveChatPFP

class SEService(Service):
    @classmethod
    async def create(cls, reactions: Reactions, common: CommonData):
        bot = Bot()
        await bot.authenticate(
            common.privateConfig["chat"]["email"],
            common.privateConfig["chat"]["password"],
            common.privateConfig["chat"]["host"],
        )
        room = await bot.joinRoom(common.privateConfig["chat"]["room"])
        instance = cls(bot, room, reactions, common)
        await instance.startup()
        return instance

    def __init__(self, bot: Bot, room: Room, reactions: Reactions, common: CommonData):
        super().__init__("se", room.userID, SECommands(room, common, self))
        self.bot = bot
        self.room = room
        self.common = common
        self.reactions = reactions
        self.converter = MarkdownConverter(autolinks=False)

        self.pfpCache: dict[int, str] = {}

        self.logger = logging.getLogger("SEService")
        self.logger.info(f"Connected to chat as user {room.userID}")
        self.editDB: dict[int, tuple[datetime, list[int]]] = {}
        self.parser = CommandParser(self.commands.commands)

        self.common.ghClient.services.append(self)
        self.room.register(self.onMessage, EventType.MESSAGE)
        self.room.register(self.onEdit, EventType.EDIT)

    async def startup(self):
        await self.room.send(
            "Well, here we are again."
            if random.random() > 0.01
            else "GOOD MORNING, MOTHERF***ERS"
        )

    async def shutdown(self):
        await self.bot.shutdown()

    async def send(self, message: str, **kwargs):
        return await self.room.send(message)

    async def pin(self, message: int):
        await self.room.pin(message)

    async def getPFP(self, user: int):
        if user not in self.pfpCache:
            async with ClientSession() as session:
                async with session.get(
                    f"https://chat.stackexchange.com/users/thumbs/{user}"
                ) as response:
                    self.pfpCache[user] = resolveChatPFP((await response.json())["email_hash"])
        return self.pfpCache[user]

    def preprocessMessage(self, message: str):
        soup = BeautifulSoup(message)
        for tag in soup.find_all("a"):
            if not isinstance(tag, Tag):
                continue
            url = urlparse(tag.attrs["href"])
            if not url.netloc:
                tag.attrs["href"] = urlunparse(("https", "chat.stackexchange.com", url.path, url.params, url.query, url.fragment))
            elif not url.scheme:
                tag.attrs["href"] = urlunparse(("https", url.netloc, url.path, url.params, url.query, url.fragment))
        for tag in soup.find_all("img"):
            if not isinstance(tag, Tag):
                continue
            tag.replace_with(f"""<a href="{tag.attrs['src']}">{tag.attrs['src']}</a>""")
        return cast(str, self.converter.convert_soup(soup))

    async def onMessage(self, room: Room, message: MessageEvent):
        event = EventInfo(
            content=self.preprocessMessage(message.content),
            userName=message.user_name,
            pfp=await self.getPFP(message.user_id),
            userIdent=message.user_id,
            roomIdent=message.room_id,
            messageIdent=message.message_id,
            service=self
        )
        if message.user_id == self.room.userID:
            return
        reactions = [i async for i in self.reactions.onMessage(self, event)]
        if len(reactions):
            await self.commandRequestSignal.send_async(self, event=event)
            for line in reactions:
                await self.send(line)
                await self.commandResponseSignal.send_async(self, line=line)
            return
        await self.messageSignal.send_async(self, event=event, directedAtUs=message.content.startswith("!!/"))
        if not message.content.startswith("!!/"):
            return
        await self.commandRequestSignal.send_async(self, event=event)
        sentAt = datetime.now()
        response = [i async for i in self.processMessage(message.content.removeprefix("!!/"), event)]
        if not len(response):
            return
        responseIDs = [await self.room.reply(message.message_id, response[0])]
        for line in response[1:]:
            if line == PinThat:
                await self.room.pin(responseIDs[-1])
                continue
            responseIDs.append(await self.room.send(line))
        self.editDB[message.message_id] = (sentAt, responseIDs)
        for line in response:
            await self.commandResponseSignal.send_async(self, line=line)

    async def onEdit(self, room: Room, edit: EditEvent):
        event = EventInfo(
            content=edit.content,
            userName=edit.user_name,
            pfp=await self.getPFP(edit.user_id),
            userIdent=edit.user_id,
            roomIdent=edit.room_id,
            messageIdent=edit.message_id,
            service=self
        )
        if edit.user_id == self.room.userID:
            return
        await self.editSignal.send_async(self, event=event, directedAtUs=edit.content.startswith("!!/"))
        if not edit.content.startswith("!!/"):
            return
        await self.commandRequestSignal.send_async(self, event=event)
        if edit.message_id not in self.editDB:
            with self.messageSignal.muted(), self.commandRequestSignal.muted():
                await self.onMessage(room, edit)
        else:
            sentAt, idents = self.editDB[edit.message_id]
            if (datetime.now() - sentAt).seconds > (60 * 2): # margin of error
                with self.messageSignal.muted(), self.commandRequestSignal.muted():
                    await self.onMessage(room, edit)
            else:
                response = [i async for i in self.processMessage(self.preprocessMessage(edit.content.removeprefix("!!/")), event)]
                for line in response:
                    await self.commandResponseSignal.send_async(line=line)
                if len(response):
                    response[0] = f":{edit.message_id} " + response[0]
                for x in range(min(len(idents), len(response))):
                    await self.room.edit(idents.pop(0), response.pop(0))
                for leftover in response:
                    await self.room.send(leftover)
                for leftover in idents:
                    await self.room.delete(leftover)
                self.editDB.pop(edit.message_id)
        # we always check the DB regardless of how we responded
        for key, value in self.editDB.copy().items():
            if (datetime.now() - value[0]).seconds > (60 * 2):
                self.editDB.pop(key)

    async def processMessage(self, message: str, event: EventInfo):
        try:
            commandName, impl, args = self.parser.parseCommand(message)
        except ParseError as e:
            yield "Command error: " + e.message
            return
        userInfo = await self.common.userDB.getUser(self, event.userIdent)
        for groupName, group in self.common.publicConfig["groups"].items():
            if commandName in group.get("canRun", []):
                if userInfo is not None:
                    if groupName not in userInfo.groups:
                        yield f"Only members of group {groupName} can run !!/{commandName}."
                        return
                else:
                    yield f"Only members of group {groupName} can run !!/{commandName}."
                    return
        try:
            async for l in impl(event, *args):
                yield l
        except Exception as e:
            yield f"@Ginger An exception occured whilst processing this message!"
            self.logger.exception(f"An exception occured whilst processing message {event.messageIdent}:")