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

    importantRepositories: list[str]

    admins: list[int]

@dataclass
class AppToken:
    token: str
    expires: datetime

def formatUser(user: dict) -> str:
    return f'[{user["login"]}]({user["html_url"]})'
def formatRepo(repo: dict) -> str:
    return f'[{repo["full_name"]}]({repo["html_url"]})'
def formatIssue(issue: dict) -> str:
    return f'[#{issue["number"]}]({issue["url"]}) ({issue["title"]})'

def msgify(text):
    return (
        text.split("\n")[0]
        .split("\r")[0]
        .split("\f")[0]
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("`", "\\`")
    )