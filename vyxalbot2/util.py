from urllib.parse import urlparse, urlunparse

import re

from aiohttp import ClientSession

import bs4


GITHUB_MERGE_QUEUE = "github-merge-queue[bot]"
TRASH = 82806

LINK_REGEX = (
    r"https?://chat.stackexchange.com/transcript(/message)?/(?P<ident>\d+)(#.*)?"
)

STACK_IMGUR = "i.stack.imgur.com"
DEFAULT_PFP = "https://cdn-chat.sstatic.net/chat/img/anon.png"


def resolveChatPFP(pfp: str):
    if pfp.startswith("!"):
        pfp = pfp.removeprefix("!")
        url = urlparse(pfp)
        if url.netloc == STACK_IMGUR:
            return urlunparse(("https", STACK_IMGUR, url.path, "", "s=256", ""))
        return pfp
    return f"https://www.gravatar.com/avatar/{pfp}?s=256&d=identicon&r=PG"


def extractMessageIdent(ident: str):
    if ident.isdigit():
        return int(ident)
    elif (match := re.fullmatch(LINK_REGEX, ident)) is not None:
        return int(match.groupdict()["ident"])
    else:
        return None


async def getRoomOfMessage(session: ClientSession, ident: int):
    async with session.get(
        f"https://chat.stackexchange.com/transcript/message/{ident}"
    ) as response:
        if response.status != 200:
            return None
        # may the lord have mercy on my soul
        soup = bs4.BeautifulSoup((await response.content.read()))
        assert isinstance(nameSpan := soup.find(class_="room-name"), bs4.Tag)
        assert isinstance(link := nameSpan.find("a"), bs4.Tag)
        assert isinstance(href := link.get("href"), str)
        return int(href.removeprefix("/").removesuffix("/").split("/")[1])


async def getMessageRange(session: ClientSession, room: int, start: int, end: int):
    before = end
    yield end
    while True:
        async with session.post(
            f"https://chat.stackexchange.com/chats/{room}/events",
            data={"before": str(before), "mode": "Messages", "msgCount": 500},
        ) as response:
            data = await response.json()
            events = data["events"]
            idents: list[int] = [event["message_id"] for event in events]
            if start in idents:
                for ident in reversed(idents[idents.index(start) :]):
                    yield ident
                break
            for ident in reversed(idents):
                yield ident
            before = idents[0]


RAPTOR = r"""
                                                                   YOU CAN RUN, BUT YOU CAN'T HIDE, {user}
                                                         ___._
                                                       .'  <0>'-.._
                                                      /  /.--.____")
                                                     |   \   __.-'~
                                                     |  :  -'/
                                                    /:.  :.-'
    __________                                     | : '. |
    '--.____  '--------.______       _.----.-----./      :/
            '--.__            `'----/       '-.      __ :/
                  '-.___           :           \   .'  )/
                        '---._           _.-'   ] /  _/
                             '-._      _/     _/ / _/
                                 \_ .-'____.-'__< |  \___
                                   <_______.\    \_\_---.7
                                  |   /'=r_.-'     _\\ =/
                              .--'   /            ._/'>
                            .'   _.-'
       snd                 / .--'
                          /,/
                          |/`)
                          'c=,
"""
