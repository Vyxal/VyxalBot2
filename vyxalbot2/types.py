from typing import Any, AsyncGenerator, Callable, Optional, TypedDict, TYPE_CHECKING
from enum import Enum, auto
from datetime import datetime
from dataclasses import dataclass

if TYPE_CHECKING:
    from vyxalbot2.services import Service
    from vyxalbot2.github import GitHubApplication
    from vyxalbot2.userdb import UserDB

CommandImpl = Callable[..., AsyncGenerator[Any, None]]

class GroupType(TypedDict, total=False):
    promotionRequires: list[str]
    canRun: list[str]
    protected: dict[str, list[int]]
    linkedRole: int


class ProductionType(TypedDict):
    head: str
    base: str


class ChatConfigType(TypedDict):
    host: str
    room: int
    email: str
    password: str
    ignore: list[int]

class DiscordConfigType(TypedDict):
    token: str
    guild: int
    eventChannel: int
    bridgeChannel: int

class PrivateConfigType(TypedDict):
    port: int

    account: str
    baseRepo: str
    appID: str
    pem: str
    webhookSecret: str
    tyxalInstance: str

    mongoUrl: str
    database: str

    chat: ChatConfigType
    discord: DiscordConfigType

class AutotagType(TypedDict):
    issue2pr: dict[str, str]
    prregex: dict[str, str]

class RequiredLabelType(TypedDict):
    tags: list[str]
    exclusive: bool

class RequiredLabelsType(TypedDict):
    issues: list[RequiredLabelType]
    prs: list[RequiredLabelType]

class PublicConfigType(TypedDict):
    importantRepositories: list[str]
    ignoredRepositories: list[str]
    groups: dict[str, GroupType]
    production: dict[str, ProductionType]
    autotag: dict[str, AutotagType]
    requiredLabels: dict[str, RequiredLabelsType]


class MessagesType(TypedDict):
    help: str
    info: str
    syntaxhelp: str
    hello: str
    goodbye: str
    hugs: list[str]
    commandhelp: dict[str, str]


@dataclass
class AppToken:
    token: str
    expires: datetime

@dataclass
class CommonData:
    statuses: list[str]
    messages: MessagesType
    publicConfig: PublicConfigType
    privateConfig: PrivateConfigType
    errorsSinceStartup: int
    startupTime: datetime
    userDB: "UserDB"
    ghClient: "GitHubApplication"

@dataclass
class EventInfo:
    content: str
    userName: str
    pfp: str
    roomIdent: int
    userIdent: int
    messageIdent: int
    service: "Service"