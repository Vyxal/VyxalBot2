import random
import typing
import re

from itertools import chain, repeat

from sechat import EventType, MessageEvent, Room

if typing.TYPE_CHECKING:
    from vyxalbot2.chat import Chat
from vyxalbot2.types import EventInfo
from vyxalbot2.types import MessagesType
from vyxalbot2.util import RAPTOR

OK_TO_SELF_REPLY = ["sus"]
MESSAGE_REGEXES_IN: dict[tuple[str, ...], str] = {
    (r"(wh?[au]t( i[sz]|'s)? vyxal\??)", r"what vyxal i[sz]\??"): "info",
    (r"(!!/)?(pl(s|z|ease) )?make? meh? (a )?coo?kie?", r"cookie"): "cookie",
    (r"((please|pls|plz) )?(make|let|have) velociraptors maul (?P<user>.+)",): "maul",
    (r"(make?|brew)( a cup of|some)? coffee for (?P<user>.+)", r"(make?|brew) (?P<user>me)h?( a)? coffee",): "coffee",
    (r"(.* |^)(su+s(sy)?|amon?g ?us|suspicious)( .*|$)",): "sus",
    (
        r"(.* |^)([Ww]ho(mst)?|[Ww]hat) (did|done) (that|this|it).*",
        r".*whodunit",
    ): "blame",
    (
        r"(much |very |super |ultra |extremely )*(good|great|excellent|gaming) bot!*",
    ): "goodBot",
    (r"(hello|hey|hi|howdy|(good )?mornin['g]|(good )?evenin['g])( y'?all)?",): "hello",
    (r"((good)?bye|adios|(c|see) ?ya\!?|'night|(good|night )night|\\o)( y'?all)?",): "goodbye",
    (r".*[Mm]ojo.*", ".*🔥+.*",): "mojo"
}
MESSAGE_REGEXES: dict[str, str] = dict(
    chain.from_iterable(zip(k, repeat(v)) for k, v in MESSAGE_REGEXES_IN.items())
)

class Reactions:
    def __init__(self, room: Room, chat: "Chat", messages: MessagesType):
        self.room = room
        self.chat = chat
        self.messages = messages

        self.room.register(self.onMessage, EventType.MESSAGE)

    async def runCommand(self, name: str, event: MessageEvent, *args):
        async for line in self.chat.commands[name](EventInfo(event.user_name, event.user_id, event.message_id), *args):
            await self.room.send(line)

    async def onMessage(self, room: Room, event: MessageEvent):
        for regex, function in MESSAGE_REGEXES.items():
            reMatch = re.fullmatch(regex, event.content)
            if reMatch is not None:
                if event.user_id == self.room.userID and function not in OK_TO_SELF_REPLY:
                    continue
                await getattr(self, function)(event, reMatch)

    async def info(self, event: MessageEvent, reMatch: re.Match):
        await self.runCommand("info", event)

    async def cookie(self, event: MessageEvent, reMatch: re.Match):
        await self.runCommand("cookie", event)

    async def coffee(self, event: MessageEvent, reMatch: re.Match):
        await self.runCommand("coffee", event)

    async def maul(self, event: MessageEvent, reMatch: re.Match):
        await self.runCommand("maul", event, reMatch.group("user"))

    async def sus(self, event: MessageEvent, reMatch: re.Match):
        await self.runCommand("sus", event)

    async def blame(self, event: MessageEvent, reMatch: re.Match):
        await self.runCommand("blame", event)

    async def goodBot(self, event: MessageEvent, reMatch: re.Match):
        await self.room.send(":3")

    async def hello(self, event: MessageEvent, reMatch: re.Match):
        await self.room.send(random.choice(self.messages["hello"]))

    async def goodbye(self, event: MessageEvent, reMatch: re.Match):
        await self.room.send(random.choice(self.messages["goodbye"]))

    async def mojo(self, event: MessageEvent, reMatch: re.Match):
        emojis = [
            "".join(random.choices(("🤣", "😂"), weights=[12, 8], k=random.randint(3, 7))),
            "💯" * random.choice((1, 3, 5)),
            "🔥" * random.randint(1, 10),
        ]
        random.shuffle(emojis)
        emojis = "".join(emojis) + ("😳" * (random.randint(1, 10) == 1))
        await self.room.send(emojis)
