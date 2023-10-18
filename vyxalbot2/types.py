from typing import Optional, TypedDict
from datetime import datetime
from dataclasses import dataclass


class GroupType(TypedDict, total=False):
    promotionRequires: list[str]
    canRun: list[str]


class ProductionType(TypedDict):
    head: str
    base: str


class ChatConfigType(TypedDict):
    host: str
    room: int
    email: str
    password: str


class PrivateConfigType(TypedDict):
    port: int

    account: str
    baseRepo: str
    appID: str
    pem: str
    webhookSecret: str

    chat: ChatConfigType

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
    groups: dict[str, GroupType]
    production: dict[str, ProductionType]
    autotag: dict[str, AutotagType]
    requiredLabels: dict[str, RequiredLabelsType]


class MessagesType(TypedDict):
    help: str
    info: str
    hello: str
    goodbye: str
    hugs: list[str]
    commandhelp: dict[str, str]


@dataclass
class AppToken:
    token: str
    expires: datetime


@dataclass
class EventInfo:
    userName: str
    userIdent: int
    messageIdent: int
