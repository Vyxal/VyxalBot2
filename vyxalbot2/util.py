from typing import TypedDict
from datetime import datetime
from dataclasses import dataclass

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

@dataclass
class AppToken:
    token: str
    expires: datetime