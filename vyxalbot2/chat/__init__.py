from time import time
from typing import Callable
from dataclasses import dataclass
from datetime import datetime
from string import ascii_letters

import re
import random
import codecs
import base64
import json
import subprocess

from gidgethub import HTTPException as GitHubHTTPException, ValidationError
from gidgethub.aiohttp import GitHubAPI as AsyncioGitHubAPI
from aiohttp import ClientSession
from tinydb.table import Document
from sechat.room import Room
from sechat.events import MessageEvent, EditEvent
from uwuivy import uwuipy

import yaml

from ..types import AppToken, PrivateConfigType, PublicConfigType, MessagesType
from .parser import CommandParser, ParseError
from ..userdb import UserDB
from ..util import RAPTOR

@dataclass
class EventInfo:
    userName: str
    userIdent: int
    messageIdent: int

class Chat:
    def __init__(self, room: Room, userDB: UserDB, gh: AsyncioGitHubAPI, publicConfig: PublicConfigType, privateConfig: PrivateConfigType, messages: MessagesType, statuses: list[str]):
        self.room = room
        self.userDB = userDB
        self.publicConfig = publicConfig
        self.privateConfig = privateConfig
        self.messages = messages
        self.statuses = statuses
        self.gh = gh
        self.session = gh._session

        self.editDB: dict[int, tuple[datetime, list[int]]] = {}
        self.commands: dict[str, Callable] = {a: b for a, b in self.getCommands()}
        self.parser = CommandParser(self.commands)
        self.errorsSinceStartup = 0
        self.startupTime = datetime.now()

    def getCommands(self):
        for attrName in self.__dir__():
            attr = getattr(self, attrName)
            if not callable(attr):
                continue
            if not attr.__name__.lower().endswith("command"):
                continue
            yield re.sub(r"([A-Z])", lambda match: " " + match.group(0).lower(), attr.__name__), attr

    async def onMessage(self, message: MessageEvent):
        if message.user_id == self.room.userID:
            return
        if not message.content.startswith("!!/"):
            return
        sentAt = datetime.now()
        response = [i async for i in self.processMessage(message.content.removeprefix("!!/"), EventInfo(message.user_name, message.user_id, message.message_id))]
        responseIDs = [await self.room.reply(message.message_id, response[0])]
        for line in response[1:]:
            responseIDs.append(await self.room.send(line))
        self.editDB[message.message_id] = (sentAt, responseIDs)

    async def onEdit(self, edit: EditEvent):
        if edit.user_id == self.room.userID:
            return
        if not edit.content.startswith("!!/"):
            return
        if edit.message_id not in self.editDB:
            await self.onMessage(edit)
        else:
            sentAt, idents = self.editDB[edit.message_id]
            if (datetime.now() - sentAt).seconds > (60 * 2): # margin of error
                await self.onMessage(edit)
                return
            response = [i async for i in self.processMessage(edit.content.removeprefix("!!/"), EventInfo(edit.user_name, edit.user_id, edit.message_id))]
            response[0] += f":{edit.message_id} "
            for x in range(min(len(idents), len(response))):
                await self.room.edit(idents.pop(0), response.pop(0))
            for leftover in response:
                await self.room.send(leftover)
            for leftover in idents:
                await self.room.delete(leftover)
            self.editDB.pop(edit.message_id)

    async def processMessage(self, message: str, event: EventInfo):
        try:
            commandName, impl, args = self.parser.parseCommand(message)
        except ParseError as e:
            yield e.message
            return
        userInfo = self.userDB.getUserInfo(event.userIdent)
        for groupName, group in self.publicConfig["groups"].items():
            if commandName in group.get("canRun", []):
                if userInfo is not None:
                    if groupName not in userInfo["groups"]:
                        yield f"Only members of group {groupName} can run !!/{commandName}"
                        return
                else:
                    yield f"Only members of group {groupName} can run !!/{commandName}"
                    return
        async for l in impl(event, *args):
            yield l

    async def dieCommand(self, event: EventInfo):
        exit(-42)

    async def helpCommand(self, event: EventInfo, command: str = ""):
        if command:
            if command == "me":
                yield "I'd love to, but I don't have any limbs."
            else:
                if command in self.messages["commandhelp"]:
                    yield self.messages["commandhelp"][command]
                else:
                    yield "No help is available for that command."
        else:
            yield self.messages["help"] + ", ".join(map(lambda i: i.split(" ")[0], self.commands.keys()))

    async def infoCommand(self, event: EventInfo):
        yield self.messages["info"]

    def status(self):
        return (
            f"Bot status: Online\n"
            f"Uptime: {datetime.now() - self.startupTime}\n"
            f"Running since: {self.startupTime.isoformat()}\n"
            f"Errors since startup: {self.errorsSinceStartup}"
        )

    async def statusCommand(self, event: EventInfo):
        status = random.choice(self.statuses)
        if not status.endswith(".") and status.endswith(ascii_letters):
            status += "."
        else:
            status = status.removesuffix(";")
        yield status

    async def statusBoringCommand(self, event: EventInfo):
        yield self.status()
    
    async def statusExcitingCommand(self, event: EventInfo):
        yield "\n".join(map(lambda line: line + ("!" * random.randint(2, 5)), self.status().upper().splitlines()))

    async def statusTinglyCommand(self, event: EventInfo):
        uwu = uwuipy(None, 0.3, 0.2, 0.2, 1)  # type: ignore Me when the developers of uwuipy don't annotate their types correctly
        yield uwu.uwuify(self.status())

    async def statusSleepyCommand(self, event: EventInfo):
        status = self.status()
        yield (
            "\n".join(status.splitlines())[:random.randint(1, len(status.splitlines()))]
            + " *yawn*\n"
            + "z" * random.randint(5, 10)
        )

    async def statusCrypticCommand(self, event: EventInfo):
        yield codecs.encode(self.status(), "rot13")

    async def statusGoofyCommand(self, event: EventInfo):
        yield "\n".join(map(lambda line: line + "🤓" * random.randint(1, 3), self.status().splitlines()))

    def getPermissionsTarget(self, event: EventInfo, name: str) -> Document | str:
        if name == "me":
            target = self.userDB.getUserInfo(event.userIdent)
            if target is None:
                return "You are not in my database. Please run !!/register."
        else:
            target = self.userDB.getUserInfoByName(name)
            if target is None:
                return "I don't know any user by that name."
        return target

    async def permissionsListCommand(self, event: EventInfo, name: str):
        if isinstance(target := self.getPermissionsTarget(event, name), str):
            yield target
            return
        yield f"User {target['name']} is a member of groups {', '.join(target['groups'])}."

    def permissionsModify(self, event: EventInfo, name: str, group: str, grant: bool):
        if isinstance(target := self.getPermissionsTarget(event, name), str):
            yield target
            return
        sender = self.userDB.getUserInfo(event.userIdent)
        if sender is None:
            yield "You are not in my database. Please run !!/register."
            return
        group = group.removesuffix("s")
        try:
            promotionRequires = self.publicConfig["groups"][group].get("promotionRequires", [])
        except KeyError:
            yield "That group does not exist."
            return
        if (not any([i in promotionRequires for i in sender["groups"]])) and len(promotionRequires):
            yield "Insufficient permissions."
            return
        if grant:
            if self.userDB.addUserToGroup(target, group):
                yield f"Added {target['name']} to {group}."
            else:
                yield f"{target['name']} is already a member of {group}."
        else:
            self.userDB.removeUserFromGroup(target, group)
            yield f"{target['name']} removed from {group}."

    async def permissionsGrantCommand(self, event: EventInfo, name: str, group: str):
        for line in self.permissionsModify(event, name, group, True):
            yield line
    async def permissionsRevokeCommand(self, event: EventInfo, name: str, group: str):
        for line in self.permissionsModify(event, name, group, False):
            yield line

    async def registerCommand(self, event: EventInfo):
        if self.userDB.getUserInfo(event.userIdent):
            yield "You are already registered. If your details are out of date, run !!/refresh."
            return
        self.userDB.addUserToDatabase(
            await (
                await self.session.get(
                    f"https://chat.stackexchange.com/users/thumbs/{event.userIdent}"
                )
            ).json()
        )
        yield "You have been registered! You don't have any permisssions yet."

    async def refreshCommand(self, event: EventInfo):
        if self.userDB.getUserInfo(event.userIdent) is None:
            yield "You are not in my database. Please run !!/register."
            return
        self.userDB.refreshUserData(
            await (
                await self.session.get(
                    f"https://chat.stackexchange.com/users/thumbs/{event.userIdent}"
                )
            ).json()
        )
        yield "Your details have been updated."

    async def groupsListCommand(self, event: EventInfo):
        yield "All groups: " + ", ".join(self.publicConfig['groups'].keys())
    async def groupsMembersCommand(self, event: EventInfo, group: str):
        group = group.removesuffix("s")
        yield f"Members of {group}: " + ', '.join(map(lambda i: i['name'], self.userDB.membersOfGroup(group)))

    async def pingCommand(self, event: EventInfo, group: str, message: str):
        group = group.removesuffix("s")
        pings = " ".join(["@" + target["name"] for target in self.userDB.membersOfGroup(group) if target["id"] != event.userIdent])
        if not len(pings):
            yield "Nobody to ping."
        else:
            yield pings + " ^"

    async def coffeeCommand(self, event: EventInfo, target: str = "me"):
        if target == "me":
            yield "☕"
        else:
            yield f"@{target} ☕"

    async def maulCommand(self, event: EventInfo, target: str):
        if target.lower().removesuffix("2") == "vyxalbot" or target == "me":
            yield RAPTOR.format(user=event.userName)
        else:
            yield RAPTOR.format(user=target)

    async def hugCommand(self, event: EventInfo):
        yield random.choice(self.messages["hugs"])

    async def susCommand(self, event: EventInfo):
        yield "ඞ" * random.randint(8, 64)

    async def amilyxalCommand(self, event: EventInfo):
        yield f"You are {'' if (event.userIdent == 354515) != (random.random() <= 0.1) else 'not '}lyxal."

    async def blameCommand(self, event: EventInfo):
        yield f"It was {random.choice(self.userDB.users())['name']}'s fault!",

    async def issueOpenCommand(self, user: EventInfo, repo: str, title: str, body: str, tags: list[str] = []):
        tagSet = set(tags)
        if repo in self.publicConfig["requiredLabels"]:
            requiredLabels = self.publicConfig["requiredLabels"][repo]
            for rule in requiredLabels["issues"]:
                labelSet = set(rule["tags"])
                if rule["exclusive"]:
                    if len(labelSet.intersection(tagSet)) != 1:
                        yield f"Must be tagged with exactly one of " + ", ".join(f"`{i}`" for i in labelSet)
                        return
                else:
                    if len(labelSet.intersection(tagSet)) < 1:
                        yield f"Must be tagged with one or more of " + ", ".join(f"`{i}`" for i in labelSet)
                        return
        body = body + (
            f"\n\n_Issue created by {user.userName} [here]"
            f'https://chat.stackexchange.com/transcript/{self.room.roomID}?m={user.messageIdent}#{user.messageIdent}'
            "_"
        )
        await self.gh.post(
            f"/repos/{self.privateConfig['account']}/{repo}/issues",
            data={
                "title": title,
                "body": body,
                "labels": tags
            },
            oauth_token = "" # TODO
        )

    async def prodCommand(self, event: EventInfo, repo: str):
        if repo not in self.publicConfig["production"]:
            yield "Repository not configured."
            return
        try:
            await self.gh.post(
                f"/repos/{self.privateConfig['account']}/{repo}/pulls",
                data={
                    "title": f"Update production ({datetime.now().strftime('%b %d %Y')})",
                    "head": self.publicConfig["production"][repo]["head"],
                    "base": self.publicConfig["production"][repo]["base"],
                    "body": f"Requested by {event.userName} [here]({f'https://chat.stackexchange.com/transcript/{self.room.roomID}?m={event.messageIdent}#{event.messageIdent})'}.",
                },
                oauth_token="" # TODO
            )
        except ValidationError as e:
            yield f"Unable to open PR: {e}"
        except GitHubHTTPException as e:
            yield f"Failed to create issue: {e.status_code.value} {e.status_code.description}",

    async def idiomAddCommand(self, event: EventInfo, title: str, code: str, description: str, keywords: list[str] = []):
        file = await self.gh.getitem(
            f"/repos/{self.privateConfig['account']}/vyxal.github.io/contents/src/data/idioms.yaml",
            oauth_token="" # TODO
        )
        idioms = yaml.safe_load(base64.b64decode(file["content"]))
        if not idioms:
            idioms = []
        idioms.append(
            {
                "name": title,
                "code": code,
                "description": description,
                "link": "#"
                + base64.b64encode(
                    json.dumps(["", "", "", code, ""]).encode(
                        "utf-8"
                    )
                ).decode("utf-8"),
                "keywords": keywords,
            }
        )
        await self.gh.put(
            f"/repos/{self.privateConfig['account']}/vyxal.github.io/contents/src/data/idioms.yaml",
            data={
                "message": f"Added \"{title}\" to the idiom list.\nRequested by {event.userName} here: {f'https://chat.stackexchange.com/transcript/{self.room.roomID}?m={event.messageIdent}#{event.messageIdent}'}",
                "content": base64.b64encode(
                    yaml.dump(
                        idioms, encoding="utf-8", allow_unicode=True
                    )
                ).decode("utf-8"),
                "sha": file["sha"],
            },
            oauth_token="" # TODO,
        )

    async def pullCommand(self, event: EventInfo):
        if subprocess.run(["git", "pull"]).returncode == 0:
            yield "Restarting..."
            exit(-43)
        else:
            yield "Failed to pull!"