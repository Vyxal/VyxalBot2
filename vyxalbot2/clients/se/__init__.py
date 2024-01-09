import base64
from datetime import datetime
from enum import Enum
import inspect
import json
from logging import getLogger
import re
from typing import Any, AsyncGenerator, Callable
from aiohttp import ClientSession
from gidgethub import BadRequest, ValidationError, HTTPException as GitHubHTTPException
from sechat import Bot, EditEvent, MessageEvent, Room
import yaml
from vyxalbot2.github import VyGitHubAPI

from vyxalbot2.clients.se.parser import CommandParser, ParseError
from vyxalbot2.types import GroupType, PrivateConfigType, PublicConfigType
from vyxalbot2.userdb import User, UserDB
from vyxalbot2.util import TRASH, extractMessageIdent, getMessageRange, getRoomOfMessage, resolveChatPFP


class SEClient:
    SERVICE = "se"

    def __init__(self, room: Room, userDB: UserDB, publicConfig: PublicConfigType, privateConfig: PrivateConfigType, gh: VyGitHubAPI):
        self.room = room
        self.userDB = userDB
        self.editDB: dict[int, tuple[datetime, list[int]]] = {}
        self.pfpCache: dict[int, str] = {}
        self.groups = publicConfig["groups"]
        self.publicConfig = publicConfig
        self.privateConfig = privateConfig
        self.gh = gh
        self.logger = getLogger("SEService")

        self.commands: dict[str, Callable[..., AsyncGenerator[Any, None]]] = {}
        for attrName in self.__dir__():
            attr = getattr(self, attrName)
            if not (callable(attr) and hasattr(attr, "__name__")):
                continue
            if not attr.__name__.lower().endswith("command"):
                continue
            name = re.sub(
                r"([A-Z])",
                lambda match: " " + match.group(0).lower(),
                attr.__name__.removesuffix("Command"),
            )
            self.commands[name] = attr
        self.parser = CommandParser(self.commands)

    async def onMessage(self, room: Room, message: MessageEvent):
        if message.user_id == self.room.userID:
            return
        if not message.content.startswith("!!/"):
            return
        sentAt = datetime.now()
        response = [i async for i in self.processMessage(message)]
        responseIDs = [await self.room.reply(message.message_id, response[0])]
        for line in response[1:]:
            responseIDs.append(await self.room.send(line))
        self.editDB[message.message_id] = (sentAt, responseIDs)

    async def onEdit(self, room: Room, edit: EditEvent):
        if edit.user_id == self.room.userID:
            return
        if not edit.content.startswith("!!/"):
            return
        if edit.message_id not in self.editDB:
            await self.onMessage(room, edit)
        else:
            sentAt, idents = self.editDB[edit.message_id]
            if (datetime.now() - sentAt).seconds > (60 * 2):  # margin of error
                await self.onMessage(room, edit)
                return
            response = [i async for i in self.processMessage(edit)]
            response[0] = f":{edit.message_id} " + response[0]
            for x in range(min(len(idents), len(response))):
                await self.room.edit(idents.pop(0), response.pop(0))
            for leftover in response:
                await self.room.send(leftover)
            for leftover in idents:
                await self.room.delete(leftover)
            self.editDB.pop(edit.message_id)
        for key, value in self.editDB.copy().items():
            if (datetime.now() - value[0]).seconds > (60 * 2):
                self.editDB.pop(key)

    async def processMessage(self, event: MessageEvent):
        try:
            commandName, impl, args = self.parser.parseCommand(
                event.content.removeprefix("!!/")
            )
        except ParseError as e:
            yield "Command error: " + e.message
            return
        if not await self.userDB.checkAuthentication("se", event.user_id, commandName):
            yield f"You cannnot run !!/{commandName}."
            return
        try:
            async for l in impl(event, *args):
                yield l
        except Exception as e:
            yield f"@Ginger An exception occured whilst processing this message!"
            self.logger.exception(
                f"An exception occured whilst processing message {event.message_id}:"
            )

    async def getPFP(self, user: int):
        if user not in self.pfpCache:
            async with ClientSession() as session:
                async with session.get(
                    f"https://chat.stackexchange.com/users/thumbs/{user}"
                ) as response:
                    self.pfpCache[user] = resolveChatPFP(
                        (await response.json())["email_hash"]
                    )
        return self.pfpCache[user]

    async def helpCommand(self, event: MessageEvent, command: str = ""):
        if len(command):
            if command == "me":
                yield "I'd love to, but I don't have any limbs."
            else:
                if command not in self.commands:
                    yield "That command does not exist."
                else:
                    parameters = []
                    impl = self.commands[command]
                    for parameter in inspect.signature(impl).parameters.values():
                        if parameter.name in ("event", "self"):
                            continue
                        if issubclass(parameter.annotation, Enum):
                            typeString = "|".join(
                                member.value for member in parameter.annotation
                            )
                            if parameter.default is not parameter.empty:
                                assert isinstance(
                                    parameter.default, parameter.annotation
                                )
                                typeString += " = " + parameter.default.value
                        else:
                            typeString = parameter.annotation.__name__
                        if parameter.default is not parameter.empty:
                            parameters.append(f"[{parameter.name}: {typeString}]")
                        else:
                            parameters.append(f"<{parameter.name}: {typeString}>")
                    description = inspect.getdoc(impl)
                    if description is None:
                        description = "no description provided"
                    yield (
                        (f"`!!/{command} " + " ".join(parameters)).strip()
                        + "`: "
                        + description
                    )

    async def getPermissionsTarget(self, event: MessageEvent, name: str) -> User | str:
        if name == "me":
            target = await self.userDB.getUser("se", event.user_id)
            if target is None:
                return "You are not in my database. Please run !!/register."
        else:
            target = await self.userDB.getUserByName(self.SERVICE, name)
            if target is None:
                return "I don't know any user by that name."
        return target

    async def permissionsListCommand(self, event: MessageEvent, name: str):
        """List the groups a user is member of."""
        if isinstance(target := (await self.getPermissionsTarget(event, name)), str):
            yield target
            return
        yield f"User {target.name} is a member of groups {', '.join(target.groups)}."

    async def permissionsModify(
        self, event: MessageEvent, name: str, group: str, grant: bool
    ):
        if isinstance(target := (await self.getPermissionsTarget(event, name)), str):
            yield target
            return
        sender = await self.userDB.getUser(self.SERVICE, event.user_id)
        if sender is None:
            yield "You are not in my database. Please run !!/register."
            return
        group = group.removesuffix("s")
        try:
            promotionRequires = self.groups[group].get("promotionRequires", [])
        except KeyError:
            yield "That group does not exist."
            return
        if (not any([i in promotionRequires for i in sender.groups])) and len(
            promotionRequires
        ):
            yield "Insufficient permissions."
            return
        if grant:
            if group in target.groups:
                yield f"{target.name} is already a member of {group}."
            else:
                target.groups.append(group)
        else:
            if target.serviceIdent in self.groups[group].get("protected", {}).get(
                self.SERVICE, []
            ):
                yield "That user may not be removed."
            elif group not in target.groups:
                yield f"That user is not in {group}."
            else:
                target.groups.remove(group)
                yield f"{target.name} removed from {group}."
        await self.userDB.save(target)

    async def permissionsGrantCommand(self, event: MessageEvent, name: str, group: str):
        """Add a user to a group."""
        async for line in self.permissionsModify(event, name, group, True):
            yield line

    async def permissionsRevokeCommand(
        self, event: MessageEvent, name: str, group: str
    ):
        """Remove a user from a group."""
        async for line in self.permissionsModify(event, name, group, False):
            yield line

    async def registerCommand(self, event: MessageEvent):
        """Register yourself to the bot."""
        if await self.userDB.getUser(self.SERVICE, event.user_id):
            yield "You are already registered. If your details are out of date, run !!/refresh."
            return
        async with ClientSession() as session:
            async with session.get(
                f"https://chat.stackexchange.com/users/thumbs/{event.user_id}"
            ) as response:
                thumb = await response.json()
        await self.userDB.createUser(
            self.SERVICE,
            thumb["id"],
            thumb["name"],
            resolveChatPFP(thumb["email_hash"]),
        )
        yield "You have been registered! You don't have any permisssions yet."

    async def refreshCommand(self, event: MessageEvent):
        """Refresh your user information."""
        user = await self.userDB.getUser(self.SERVICE, event.user_id)
        if user is None:
            yield "You are not in my database. Please run !!/register."
            return
        async with ClientSession() as session:
            async with session.get(
                f"https://chat.stackexchange.com/users/thumbs/{event.user_id}"
            ) as response:
                thumb = await response.json()
        user.name = thumb["name"]
        user.pfp = resolveChatPFP(thumb["email_hash"])
        await self.userDB.save(user)
        yield "Your details have been updated."

    async def groupsListCommand(self, event: MessageEvent):
        """List all groups known to the bot."""
        yield "All groups: " + ", ".join(self.groups.keys())

    async def groupsMembersCommand(self, event: MessageEvent, group: str):
        """List all members of a group."""
        group = group.removesuffix("s")
        yield f"Members of {group}: " + ", ".join(
            map(lambda i: i.name, await self.userDB.membersOfGroup(self.SERVICE, group))
        )

    async def pingCommand(self, event: MessageEvent, group: str, message: str):
        """Ping all members of a group. Use with care!"""
        group = group.removesuffix("s")
        pings = " ".join(
            [
                "@" + target.name
                for target in await self.userDB.membersOfGroup(self.SERVICE, group)
                if target.serviceIdent != event.user_id
            ]
        )
        if not len(pings):
            yield "Nobody to ping."
        else:
            yield pings + " ^"

    async def issueOpenCommand(
        self,
        event: MessageEvent,
        repo: str,
        title: str,
        body: str,
        tags: list[str] = [],
    ):
        """Open an issue in a repository."""
        tagSet = set(tags)
        if repo in self.publicConfig["requiredLabels"]:
            requiredLabels = self.publicConfig["requiredLabels"][repo]
            for rule in requiredLabels["issues"]:
                labelSet = set(rule["tags"])
                if rule["exclusive"]:
                    if len(labelSet.intersection(tagSet)) != 1:
                        yield f"Must be tagged with exactly one of " + ", ".join(
                            f"`{i}`" for i in labelSet
                        )
                        return
                else:
                    if len(labelSet.intersection(tagSet)) < 1:
                        yield f"Must be tagged with one or more of " + ", ".join(
                            f"`{i}`" for i in labelSet
                        )
                        return
        body = body + (
            f"\n\n_Issue created by {event.user_name} [here]"
            f"(https://chat.stackexchange.com/transcript/{self.room.roomID}?m={event.message_id}#{event.message_id})"
            "_"
        )
        try:
            await self.gh.post(
                f"/repos/{self.privateConfig['account']}/{repo}/issues",
                data={"title": title, "body": body, "labels": tags},
                oauth_token=await self.gh.appToken(),
            )
        except BadRequest as e:
            yield f"Failed to open issue: {e.args}"

    async def issueCloseCommand(
        self, event: MessageEvent, repo: str, num: int, body: str = ""
    ):
        """Close an issue in a repository."""
        if body:
            body = body + (
                f"\n\n_Issue closed by {event.user_name} [here]"
                f"(https://chat.stackexchange.com/transcript/{self.room.roomID}?m={event.message_id}#{event.message_id})"
                "_"
            )
            try:
                await self.gh.post(
                    f"/repos/{self.privateConfig['account']}/{repo}/issues/{num}/comments",
                    data={"body": body},
                    oauth_token=await self.gh.appToken(),
                )
            except BadRequest as e:
                yield f"Failed to send comment: {e.args}"
        try:
            await self.gh.patch(
                f"/repos/{self.privateConfig['account']}/{repo}/issues/{num}",
                data={"state": "closed"},
                oauth_token=await self.gh.appToken(),
            )
        except BadRequest as e:
            yield f"Failed to close issue: {e.args}"

    async def prodCommand(self, event: MessageEvent, repo: str = ""):
        """Open a PR to update production."""
        if len(repo) == 0:
            repo = self.privateConfig["baseRepo"]
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
                    "body": f"Requested by {event.user_name} [here]({f'https://chat.stackexchange.com/transcript/{self.room.roomID}?m={event.message_id}#{event.message_id})'}.",
                },
                oauth_token=await self.gh.appToken(),
            )
        except ValidationError as e:
            yield f"Unable to open PR: {e}"
        except GitHubHTTPException as e:
            yield f"Failed to create issue: {e.status_code.value} {e.status_code.description}",

    async def idiomAddCommand(
        self,
        event: MessageEvent,
        title: str,
        code: str,
        description: str,
        keywords: list[str] = [],
    ):
        """Add an idiom to the idiom list."""
        file = await self.gh.getitem(
            f"/repos/{self.privateConfig['account']}/vyxal.github.io/contents/src/data/idioms.yaml",
            oauth_token=await self.gh.appToken(),
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
                    json.dumps(["", "", "", code, ""]).encode("utf-8")
                ).decode("utf-8"),
                "keywords": keywords,
            }
        )
        await self.gh.put(
            f"/repos/{self.privateConfig['account']}/vyxal.github.io/contents/src/data/idioms.yaml",
            data={
                "message": f"Added \"{title}\" to the idiom list.\nRequested by {event.user_name} here: {f'https://chat.stackexchange.com/transcript/{self.room.roomID}?m={event.message_id}#{event.message_id}'}",
                "content": base64.b64encode(
                    yaml.dump(idioms, encoding="utf-8", allow_unicode=True)
                ).decode("utf-8"),
                "sha": file["sha"],
            },
            oauth_token=await self.gh.appToken(),
        )

    async def trashCommand(
        self, event: MessageEvent, startRaw: str, endRaw: str, target: int = TRASH
    ):
        """Move messages to a room (defaults to Trash)."""
        async with ClientSession() as session:
            start = extractMessageIdent(startRaw)
            end = extractMessageIdent(endRaw)
            if start is None:
                yield "Malformed start id"
                return
            if end is None:
                yield "Malformed end id"
                return
            # Sanity check: make sure the messages are actually in our room
            if (await getRoomOfMessage(session, start)) != self.privateConfig[
                "chat"
            ]["room"]:
                yield "Start message does not exist or is not in this room"
                return
            if (await getRoomOfMessage(session, start)) != self.privateConfig[
                "chat"
            ]["room"]:
                yield "End message does not exist or is not in this room"
                return
            # Dubious code to figure out the range of messages we're dealing with
            identRange = [
                i
                async for i in getMessageRange(
                    session, self.privateConfig["chat"]["room"], start, end
                )
            ]
            await self.room.moveMessages(identRange, target)
            yield f"Moved {len(identRange)} messages successfully."
