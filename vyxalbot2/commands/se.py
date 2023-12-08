from datetime import datetime
from typing import Union, TYPE_CHECKING

import base64
import json
import yaml

from aiohttp import ClientSession
from gidgethub import BadRequest, ValidationError, HTTPException as GitHubHTTPException
from sechat import Room

if TYPE_CHECKING:
    from vyxalbot2.services.se import SEService
from vyxalbot2.commands.common import CommonCommands
from vyxalbot2.types import CommonData, EventInfo
from vyxalbot2.userdb import User
from vyxalbot2.util import TRASH, extractMessageIdent, getMessageRange, getRoomOfMessage, resolveChatPFP

class SECommands(CommonCommands):
    def __init__(self, room: Room, common: CommonData, service: "SEService"):
        super().__init__(common)
        self.room = room
        self.service = service
        self.userDB = common.userDB
        self.groups = common.publicConfig["groups"]
        self.commandHelp = self.genHelpStrings()

    def genHelpStrings(self):
        help: dict[str, list[str]] = {}
        for name, command in self.commands.items():
            baseName = name.split(" ")[0]
            if baseName in help:
                help[baseName].append(command.fullHelp)
            else:
                help[baseName] = [command.fullHelp]
        return help

    async def helpCommand(self, event: EventInfo, command: str = ""):
        """Provide help for a command."""
        if command:
            if command == "me":
                yield "I'd love to, but I don't have any limbs."
            elif command == "syntax":
                yield self.common.messages["syntaxhelp"]
            else:
                if command in self.commandHelp:
                    for line in self.commandHelp[command]:
                        yield line
                else:
                    yield "No help is available for that command."
        else:
            yield self.common.messages["help"] + ", ".join(sorted(set(map(lambda i: i.split(" ")[0], event.service.commands.commands.keys()))))

    async def getPermissionsTarget(self, event: EventInfo, name: str) -> Union[User, str]:
        if name == "me":
            target = await self.userDB.getUser(self.service, event.userIdent)
            if target is None:
                return "You are not in my database. Please run !!/register."
        else:
            target = await self.userDB.getUserByName(self.service, name)
            if target is None:
                return "I don't know any user by that name."
        return target

    async def permissionsListCommand(self, event: EventInfo, name: str):
        """List the groups a user is member of."""
        if isinstance(target := (await self.getPermissionsTarget(event, name)), str):
            yield target
            return
        yield f"User {target.name} is a member of groups {', '.join(target.groups)}."

    async def permissionsModify(self, event: EventInfo, name: str, group: str, grant: bool):
        if isinstance(target := (await self.getPermissionsTarget(event, name)), str):
            yield target
            return
        sender = await self.userDB.getUser(self.service, event.userIdent)
        if sender is None:
            yield "You are not in my database. Please run !!/register."
            return
        group = group.removesuffix("s")
        try:
            promotionRequires = self.groups[group].get("promotionRequires", [])
        except KeyError:
            yield "That group does not exist."
            return
        if (not any([i in promotionRequires for i in sender.groups])) and len(promotionRequires):
            yield "Insufficient permissions."
            return
        if grant:
            if group in target.groups:
                yield f"{target.name} is already a member of {group}."
            else:
                target.groups.append(group)
        else:
            if target.serviceIdent in self.groups[group].get("protected", {}).get(self.service.name, []):
                yield "That user may not be removed."
            elif group not in target.groups:
                yield f"That user is not in {group}."
            else:
                target.groups.remove(group)
                yield f"{target.name} removed from {group}."
        await self.userDB.save(target)

    async def permissionsGrantCommand(self, event: EventInfo, name: str, group: str):
        """Add a user to a group."""
        async for line in self.permissionsModify(event, name, group, True):
            yield line
    async def permissionsRevokeCommand(self, event: EventInfo, name: str, group: str):
        """Remove a user from a group."""
        async for line in self.permissionsModify(event, name, group, False):
            yield line

    async def registerCommand(self, event: EventInfo):
        """Register yourself to the bot."""
        if await self.userDB.getUser(self.service, event.userIdent):
            yield "You are already registered. If your details are out of date, run !!/refresh."
            return
        async with ClientSession() as session:
            async with session.get(
                f"https://chat.stackexchange.com/users/thumbs/{event.userIdent}"
            ) as response:
                thumb = await response.json()
        await self.userDB.createUser(
            self.service,
            thumb["id"],
            thumb["name"],
            resolveChatPFP(thumb["email_hash"])
        )
        yield "You have been registered! You don't have any permisssions yet."

    async def refreshCommand(self, event: EventInfo):
        """Refresh your user information."""
        user = await self.userDB.getUser(self.service, event.userIdent)
        if user is None:
            yield "You are not in my database. Please run !!/register."
            return
        async with ClientSession() as session:
            async with session.get(
                f"https://chat.stackexchange.com/users/thumbs/{event.userIdent}"
            ) as response:
                thumb = await response.json()
        user.name = thumb["name"]
        user.pfp = resolveChatPFP(thumb["email_hash"])
        await self.userDB.save(user)
        yield "Your details have been updated."

    async def groupsListCommand(self, event: EventInfo):
        """List all groups known to the bot."""
        yield "All groups: " + ", ".join(self.groups.keys())
    async def groupsMembersCommand(self, event: EventInfo, group: str):
        """List all members of a group."""
        group = group.removesuffix("s")
        yield f"Members of {group}: " + ', '.join(map(lambda i: i.name, await self.userDB.membersOfGroup(self.service, group)))

    async def pingCommand(self, event: EventInfo, group: str, message: str):
        """Ping all members of a group. Use with care!"""
        group = group.removesuffix("s")
        pings = " ".join(["@" + target.name for target in await self.userDB.membersOfGroup(self.service, group) if target.serviceIdent != event.userIdent])
        if not len(pings):
            yield "Nobody to ping."
        else:
            yield pings + " ^"

    async def issueOpenCommand(self, event: EventInfo, repo: str, title: str, body: str, tags: list[str] = []):
        """Open an issue in a repository."""
        tagSet = set(tags)
        if repo in self.common.publicConfig["requiredLabels"]:
            requiredLabels = self.common.publicConfig["requiredLabels"][repo]
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
            f"\n\n_Issue created by {event.userName} [here]"
            f'(https://chat.stackexchange.com/transcript/{self.room.roomID}?m={event.messageIdent}#{event.messageIdent})'
            "_"
        )
        try:
            await self.common.ghClient.gh.post(
                f"/repos/{self.common.privateConfig['account']}/{repo}/issues",
                data={
                    "title": title,
                    "body": body,
                    "labels": tags
                },
                oauth_token = await self.common.ghClient.appToken()
            )
        except BadRequest as e:
            yield f"Failed to open issue: {e.args}"

    async def issueCloseCommand(self, event: EventInfo, repo: str, num: int, body: str=""):
        """Close an issue in a repository."""
        if body:
            body = body + (
                f"\n\n_Issue closed by {event.userName} [here]"
                f'(https://chat.stackexchange.com/transcript/{self.room.roomID}?m={event.messageIdent}#{event.messageIdent})'
                "_"
            )
            try:
                await self.common.ghClient.gh.post(
                    f"/repos/{self.common.privateConfig['account']}/{repo}/issues/{num}/comments",
                    data={"body": body},
                    oauth_token = await self.common.ghClient.appToken()
                )
            except BadRequest as e:
                yield f"Failed to send comment: {e.args}"
        try:
            await self.common.ghClient.gh.patch(
                f"/repos/{self.common.privateConfig['account']}/{repo}/issues/{num}",
                data={"state": "closed"},
                oauth_token = await self.common.ghClient.appToken()
            )
        except BadRequest as e:
            yield f"Failed to close issue: {e.args}"

    async def prodCommand(self, event: EventInfo, repo: str = ""):
        """Open a PR to update production."""
        if len(repo) == 0:
            repo = self.common.privateConfig["baseRepo"]
        if repo not in self.common.publicConfig["production"]:
            yield "Repository not configured."
            return
        try:
            await self.common.ghClient.gh.post(
                f"/repos/{self.common.privateConfig['account']}/{repo}/pulls",
                data={
                    "title": f"Update production ({datetime.now().strftime('%b %d %Y')})",
                    "head": self.common.publicConfig["production"][repo]["head"],
                    "base": self.common.publicConfig["production"][repo]["base"],
                    "body": f"Requested by {event.userName} [here]({f'https://chat.stackexchange.com/transcript/{self.room.roomID}?m={event.messageIdent}#{event.messageIdent})'}.",
                },
                oauth_token=await self.common.ghClient.appToken()
            )
        except ValidationError as e:
            yield f"Unable to open PR: {e}"
        except GitHubHTTPException as e:
            yield f"Failed to create issue: {e.status_code.value} {e.status_code.description}",

    async def idiomAddCommand(self, event: EventInfo, title: str, code: str, description: str, keywords: list[str] = []):
        """Add an idiom to the idiom list."""
        file = await self.common.ghClient.gh.getitem(
            f"/repos/{self.common.privateConfig['account']}/vyxal.github.io/contents/src/data/idioms.yaml",
            oauth_token=await self.common.ghClient.appToken(),
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
        await self.common.ghClient.gh.put(
            f"/repos/{self.common.privateConfig['account']}/vyxal.github.io/contents/src/data/idioms.yaml",
            data={
                "message": f"Added \"{title}\" to the idiom list.\nRequested by {event.userName} here: {f'https://chat.stackexchange.com/transcript/{self.room.roomID}?m={event.messageIdent}#{event.messageIdent}'}",
                "content": base64.b64encode(
                    yaml.dump(
                        idioms, encoding="utf-8", allow_unicode=True
                    )
                ).decode("utf-8"),
                "sha": file["sha"],
            },
            oauth_token=await self.common.ghClient.appToken(),
        )

    async def trashCommand(self, event: EventInfo, startRaw: str, endRaw: str, target: int = TRASH):
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
            if (await getRoomOfMessage(session, start)) != self.common.privateConfig["chat"]["room"]:
                yield "Start message does not exist or is not in this room"
                return
            if (await getRoomOfMessage(session, start)) != self.common.privateConfig["chat"]["room"]:
                yield "End message does not exist or is not in this room"
                return
            # Dubious code to figure out the range of messages we're dealing with
            identRange = [i async for i in getMessageRange(session, self.common.privateConfig["chat"]["room"], start, end)]
            await self.room.moveMessages(identRange, target)
            yield f"Moved {len(identRange)} messages successfully."