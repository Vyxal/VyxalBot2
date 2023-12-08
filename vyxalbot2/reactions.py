from itertools import chain, repeat

import random
import re

from vyxalbot2.services import Service
from vyxalbot2.types import EventInfo
from vyxalbot2.types import MessagesType

OK_TO_SELF_REPLY = ["sus"]
DO_NOT_IGNORE_COMMAND_PREFIX = ["sus"]
MESSAGE_REGEXES_IN: dict[tuple[str, ...], str] = {
    (r"(wh?[au]t( i[sz]|'s)? vyxal\??)", r"what vyxal i[sz]\??"): "info",
    (r"(!!/)?(pl(s|z|ease) )?make? meh? (a )?coo?kie?", r"cookie"): "cookie",
    (r"((please|pls|plz) )?(make|let|have) velociraptors maul (?P<user>.+)",): "maul",
    (
        r"(make?|brew)( a cup of|some)? coffee for (?P<user>.+)",
        r"(make?|brew) (?P<user>me)h?( a)? coffee",
    ): "coffee",
    (r"(.* |^)(su+s(sy)?|amon?g ?us|suspicious)( .*|$)",): "sus",
    (
        r"(.* |^)([Ww]ho(mst)?|[Ww]hat) (did|done) (that|this|it).*",
        r".*whodunit",
    ): "blame",
    (
        r"(much |very |super |ultra |extremely )*(good|great|excellent|gaming) bot!*",
    ): "goodBot",
    (r"(hello|hey|hi|howdy|(good )?mornin['g]|(good )?evenin['g])( y'?all)?",): "hello",
    (
        r"((good)?bye|adios|(c|see) ?ya\!?|'night|(good|night )night|\\o)( y'?all)?",
    ): "goodbye",
    (
        r".*mojo.*",
        ".*🔥+.*",
    ): "mojo",
}
MESSAGE_REGEXES: dict[str, str] = dict(
    chain.from_iterable(zip(k, repeat(v)) for k, v in MESSAGE_REGEXES_IN.items())
)


class Reactions:
    def __init__(self, messages: MessagesType, ignore: list[int]):
        self.messages = messages
        self.ignore = ignore

    async def runCommand(self, service: Service, name: str, event: EventInfo, *args):
        async for line in service.invokeCommand(name, event, *args):
            yield line

    async def onMessage(self, service: Service, event: EventInfo):
        for regex, function in MESSAGE_REGEXES.items():
            if function not in DO_NOT_IGNORE_COMMAND_PREFIX:
                reMatch = re.fullmatch(regex, event.content.lower().removeprefix("!!/"))
            else:
                reMatch = re.fullmatch(regex, event.content.lower())
            if reMatch is not None:
                if (
                    event.userIdent == event.service.clientIdent
                    and function not in OK_TO_SELF_REPLY
                ):
                    continue
                if event.userIdent in self.ignore:
                    continue
                async for line in getattr(self, function)(service, event, reMatch):
                    yield line

    async def info(self, service: Service, event: EventInfo, reMatch: re.Match):
        async for line in self.runCommand(service, "info", event):
            yield line

    async def cookie(self, service: Service, event: EventInfo, reMatch: re.Match):
        async for line in self.runCommand(service, "cookie", event):
            yield line

    async def coffee(self, service: Service, event: EventInfo, reMatch: re.Match):
        async for line in self.runCommand(service, "coffee", event):
            yield line

    async def maul(self, service: Service, event: EventInfo, reMatch: re.Match):
        async for line in self.runCommand(service, "maul", event):
            yield line

    async def sus(self, service: Service, event: EventInfo, reMatch: re.Match):
        async for line in self.runCommand(service, "sus", event):
            yield line

    async def blame(self, service: Service, event: EventInfo, reMatch: re.Match):
        async for line in self.runCommand(service, "blame", event):
            yield line

    async def goodBot(self, service: Service, event: EventInfo, reMatch: re.Match):
        yield ":3"

    async def hello(self, service: Service, event: EventInfo, reMatch: re.Match):
        yield random.choice(self.messages["hello"])

    async def goodbye(self, service: Service, event: EventInfo, reMatch: re.Match):
        yield random.choice(self.messages["goodbye"])

    async def mojo(self, service: Service, event: EventInfo, reMatch: re.Match):
        emojis = [
            "".join(
                random.choices(("🤣", "😂"), weights=[12, 8], k=random.randint(3, 7))
            ),
            "💯" * random.choice((1, 3, 5)),
            "🔥" * random.randint(1, 10),
        ]
        random.shuffle(emojis)
        yield "".join(emojis) + ("😳" * (random.randint(1, 10) == 1))
