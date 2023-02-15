from typing import Optional, TypedDict
from datetime import datetime
from dataclasses import dataclass
from re import fullmatch
from itertools import chain, repeat

COMMAND_REGEXES_IN: dict[tuple[str, ...], str] = {
    (
        r"status( (?P<boring>boring))?",
        r"((lol )?(yo)?u good( (there )?(my )?(epic )? (bro|dude|sis|buddy|mate|m8|gamer)?)?\??)",
    ): "status",
    (r"info",): "info",
    (r"help( (?P<command>.+))?",): "help",
    (
        r"coffee (?P<user>.+)",
        r"(make|brew)( a cup of)? coffee for (?P<user>.+)",
    ): "coffee",
    (r"maul (?P<user>.+)",): "maul",
    (r"die",): "die",
    (
        r"permissions (?P<action>list|grant|revoke) (?P<user>(\d+)|me)( (?P<permission>.+))?",
    ): "permissions",
    (r"groups (?P<action>list)", r"groups (?P<action>members) (?P<group>.+)"): "groups",
    (r"register",): "register",
    (r"ping (?P<group>.+)(?P<message>.*)",): "ping",
}
MESSAGE_REGEXES_IN: dict[tuple[str, ...], str] = {
    (r"(wh?at( i[sz]|'s)? vyxal\??)", r"what vyxal i[sz]\??"): "info",
    (r"((please|pls|plz) )?(make|let|have) velociraptors maul (?P<user>.+)",): "maul",
}
COMMAND_REGEXES: dict[str, str] = dict(
    chain.from_iterable(zip(k, repeat(v)) for k, v in COMMAND_REGEXES_IN.items())
)
MESSAGE_REGEXES: dict[str, str] = dict(
    chain.from_iterable(zip(k, repeat(v)) for k, v in MESSAGE_REGEXES_IN.items())
)

TAG_MAP = {
    "bug": "PR: Bug Fix",
    "documentation": "PR: Documentation Fix",
    "request: element": "PR: Element Implementation",
    "enhancement": "PR: Enhancement",
    "difficulty: very hard": "PR: Careful Review Required",
    "priority: high": "PR: Urgent Review Required",
    "online interpreter": "PR: Online Interpreter",
    "version-3": "PR: Version 3 Related",
    "difficulty: easy": "PR: Light and Easy",
    "good first issue": "PR: Light and Easy"
}

class GroupType(TypedDict, total=False):
    promotionRequires: list[str]
    canRun: list[str]


class ConfigType(TypedDict):
    port: int

    accountID: int
    appID: str
    pem: str
    webhookSecret: str

    SERoom: int
    SEEmail: str
    SEPassword: str
    SEHost: str

    importantRepositories: list[str]

    groups: dict[str, GroupType]


class MessagesType(TypedDict):
    help: str
    info: str
    commandhelp: dict[str, str]


@dataclass
class AppToken:
    token: str
    expires: datetime


def formatUser(user: dict) -> str:
    return f'[{user["login"]}]({user["html_url"]})'


def formatRepo(repo: dict) -> str:
    return f'[{repo["full_name"]}]({repo["html_url"]})'


def formatIssue(issue: dict) -> str:
    return f'[#{issue["number"]}]({issue["html_url"]}) ({issue["title"]})'


def msgify(text):
    return (
        text.split("\n")[0]
        .split("\r")[0]
        .split("\f")[0]
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("`", "\\`")
    )


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
