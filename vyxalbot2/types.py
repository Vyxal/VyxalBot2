from typing import Optional, TypedDict
from datetime import datetime
from dataclasses import dataclass


class GroupType(TypedDict, total=False):
    promotionRequires: list[str]
    canRun: list[str]

class ProductionType(TypedDict):
    head: str
    base: str

class ConfigType(TypedDict):
    port: int

    account: str
    baseRepo: str
    appID: str
    pem: str
    webhookSecret: str

    SERoom: int
    SEEmail: str
    SEPassword: str
    SEHost: str

    importantRepositories: list[str]

    groups: dict[str, GroupType]

    production: dict[str, ProductionType]


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
