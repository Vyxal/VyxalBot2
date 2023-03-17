from typing import Optional, cast, Any
from time import time
from datetime import datetime
from pathlib import Path
from asyncio import create_task
from string import ascii_letters

import logging
import sys
import json
import os
import signal
import random
import re
import codecs

import tomli

from aiohttp import ClientSession
from aiohttp.web import Application, Request, Response, run_app
from aiohttp.client_exceptions import ContentTypeError
from sechat import Bot, Room, MessageEvent, EventType, UnknownEvent
from gidgethub import HTTPException as GitHubHTTPException, ValidationError
from gidgethub.aiohttp import GitHubAPI as AsyncioGitHubAPI
from gidgethub.abc import GitHubAPI
from gidgethub.routing import Router
from gidgethub.sansio import Event as GitHubEvent
from gidgethub.apps import get_installation_access_token, get_jwt
from cachetools import LRUCache
from platformdirs import user_state_path
from dateutil.parser import parse as parseDatetime
from uwuipy import uwuipy

from vyxalbot2.userdb import UserDB
from vyxalbot2.util import (
    formatUser,
    formatRepo,
    formatIssue,
    msgify,
    RAPTOR,
    TAG_MAP,
)
from vyxalbot2.types import ConfigType, MessagesType, AppToken
from vyxalbot2.commands import COMMAND_REGEXES, MESSAGE_REGEXES, COMMAND_ALIASES

__version__ = "2.0.0"


class VyxalBot2(Application):
    ADMIN_COMMANDS = ["die"]

    def __init__(
        self,
        config: ConfigType,
        messages: MessagesType,
        storagePath: str,
        statuses: list[str],
    ) -> None:
        self.logger = logging.getLogger("VyxalBot2")
        super().__init__(logger=self.logger)

        self.config = config
        self.messages = messages
        self.statuses = statuses
        self.userDB = UserDB(storagePath, self.config["groups"])
        self.replyDB = ReplyDB(storagePath)
        self.errorsSinceStartup = 0

        self.bot = Bot(logger=self.logger)
        self._appToken: Optional[AppToken] = None
        self.session = ClientSession()
        self.cache = LRUCache(maxsize=5000)
        self.ghRouter = Router()
        self.gh = AsyncioGitHubAPI(self.session, "VyxalBot2", cache=self.cache)
        self.runningTasks = set()

        with open(self.config["pem"], "r") as f:
            self.privkey = f.read()

        self.router.add_post("/webhook", self.onHookRequest)
        self.on_startup.append(self.onStartup)
        self.on_cleanup.append(self.onShutdown)

        self.ghRouter.add(self.onIssueAction, "issues")
        self.ghRouter.add(self.onPRAction, "pull_request")

        self.ghRouter.add(self.onThingCreated, "create")
        self.ghRouter.add(self.onThingDeleted, "delete")
        self.ghRouter.add(self.onReleaseCreated, "release", action="released")
        self.ghRouter.add(self.onFork, "fork")
        self.ghRouter.add(
            self.onReviewSubmitted, "pull_request_review", action="submitted"
        )

        self.ghRouter.add(
            self.onRepositoryCreated, "repository", action="created"
        )
        self.ghRouter.add(
            self.onRepositoryDeleted, "repository", action="deleted"
        )

    async def onStartup(self, _):
        await self.bot.authenticate(
            self.config["SEEmail"],
            self.config["SEPassword"],
            self.config["SEHost"],
        )
        self.room = self.bot.joinRoom(self.config["SERoom"])
        self.room.register(self.onMessage, EventType.MESSAGE)
        self.room.register(self.onEditMessage, EventType.EDIT)
        await self.room.send("Well, here we are again.")
        self.startupTime = datetime.now()

    async def onShutdown(self, _):
        try:
            await self.room.send("Ah'll be bahk.")
        except RuntimeError:
            pass
        await self.bot.__aexit__(None, None, None)  # DO NOT TRY THIS AT HOME
        await self.session.close()

    async def appToken(self, gh: GitHubAPI) -> AppToken:
        if self._appToken != None:
            if self._appToken.expires.timestamp() > time():
                return self._appToken
        jwt = get_jwt(app_id=self.config["appID"], private_key=self.privkey)
        async for installation in gh.getiter(
            "/app/installations",
            jwt=jwt,
        ):
            if installation["account"]["login"] == self.config["account"]:
                tokenData = await get_installation_access_token(
                    gh,
                    installation_id=installation["id"],
                    app_id=self.config["appID"],
                    private_key=self.privkey,
                )
                self._appToken = AppToken(
                    tokenData["token"], parseDatetime(tokenData["expires_at"])
                )
                return self._appToken
        raise ValueError("Unable to locate installation")

    async def onHookRequest(self, request: Request) -> Response:
        event = None
        try:
            body = await request.read()
            event = GitHubEvent.from_http(
                request.headers, body, secret=self.config["webhookSecret"]
            )
            self.logger.info(
                f"Recieved delivery #{event.delivery_id} ({event.event})"
            )
            if event.event == "ping":
                return Response(status=200)
            if repo := event.data.get("repository", False):
                if repo["visibility"] == "private":
                    return Response(status=200)
            await self.ghRouter.dispatch(event, self.gh)
            return Response(status=200)
        except Exception:
            self.errorsSinceStartup += 1
            if event:
                msg = f"An error occured while processing event {event.delivery_id}!"
            else:
                msg = f"An error occured while processing a request!"
            self.logger.exception(msg)
            try:
                await self.room.send(f"@Ginger " + msg)
            except RuntimeError:
                pass
            return Response(status=500)

    async def permissionsCommand(
        self, event: MessageEvent, args: dict[str, Any]
    ) -> str:
        target = self.userDB.getUserInfo(
            int(args["user"]) if args["user"] != "me" else event.user_id
        )
        sender = self.userDB.getUserInfo(event.user_id)
        if not sender:
            return "You are not in my database. Please run !!/register."
        if not target:
            return "That user is not in my database."
        match args["action"]:
            case "list":
                return f"User {target['name']} is a member of groups {', '.join(target['groups'])}."
            case "grant" | "revoke" as action:
                if not args.get("permission"):
                    return "You need to specify a permission!"
                args["permission"] = args["permission"].removesuffix("s")
                try:
                    promotionRequires = self.config["groups"][
                        args["permission"]
                    ].get("promotionRequires", [])
                    if (not any([i in promotionRequires for i in sender["groups"]])) and len(promotionRequires):  # type: ignore
                        return "Insufficient permissions!"
                except KeyError:
                    return "No such group!"
                if action == "grant":
                    if self.userDB.addUserToGroup(target, args["permission"]):
                        return f"User {target['name']} is now a member of group {args['permission']}."
                    else:
                        return f"User {target['name']} is already a member of group {args['permission']}."
                else:
                    self.userDB.removeUserFromGroup(target, args["permission"])
                    return f"User {target['name']} is no longer a member of group {args['permission']}."
        return ""

    async def runVyxalCommand(self, event: MessageEvent, args: dict[str, Any]):
        async with self.session.get(
            "https://vyxal.pythonanywhere.com/session"
        ) as sessionData:
            messageID = await self.room.reply(event.message_id, "Running...")
            async with self.session.post(
                f"https://vyxal.pythonanywhere.com/execute",
                data=json.dumps(
                    {
                        "code": args["code"],
                        "flags": args["flags"] if args["flags"] else "",
                        "footer": "",
                        "header": "",
                        "inputs": "",
                        "session": await sessionData.text(),
                    }
                ),
                headers={"Content-Type": "application/json"},
            ) as result:
                message = ""
                try:
                    responseJson = await result.json()
                except ContentTypeError:
                    await self.room.edit(
                        messageID,
                        f":{event.message_id} An error occured: "
                        + await result.text(),
                    )
                else:
                    if responseJson["stdout"]:
                        message += "stdout:\n" + responseJson["stdout"].strip()
                    if responseJson["stderr"]:
                        message += (
                            "\nstderr:\n" + responseJson["stderr"].strip()
                        )
                    await self.room.edit(
                        messageID, f":{event.message_id} " + message.strip()
                    )

    async def runCommand(
        self,
        room: Room,
        event: MessageEvent,
        command: str,
        args: dict[str, Any],
    ) -> Optional[str | int]:
        if event.user_id == room.userID:
            return None
        for groupName, group in self.config["groups"].items():
            if command in group.get("canRun", []) and not (
                groupName in r["groups"]
                if (r := self.userDB.getUserInfo(event.user_id))
                else False
            ):
                return f'You do not have permission to run that command (must be a member of group "{groupName}"). If you think you should be able to, ping Ginger.'
        match command:
            case "die":
                signal.raise_signal(signal.SIGINT)
                return None
            case "help":
                if commandName := args.get("command", ""):
                    if commandName == "me":
                        return "I'd love to, but I don't have any limbs."
                    else:
                        return self.messages["commandhelp"].get(
                            commandName,
                            "No help is available for that command.",
                        )
                else:
                    return (
                        self.messages["help"].format(version=__version__)
                        + f"{', '.join(sorted(map(lambda i: i if not i.startswith('!') else COMMAND_ALIASES[i], set(COMMAND_REGEXES.values()))))}"
                    )

            case "info":
                return self.messages["info"]
            case "status":
                if args.get("mood", ""):
                    msg = f"Bot status: Online\nUptime: {datetime.now() - self.startupTime}\nRunning since: {self.startupTime.isoformat()}\nErrors since startup: {self.errorsSinceStartup}"
                    match args.get("mood", ""):
                        case "boring":
                            pass
                        case "exciting":
                            msg = "\n".join(
                                line + ("!" * random.randint(2, 5))
                                for line in msg.upper().splitlines()
                            )
                        case "tingly":
                            uwu = uwuipy(None, 0.3, 0.2, 0.2, 1)  # type: ignore Me when the developers of uwuipy don't annotate their types correctly
                            msg = uwu.uwuify(msg)
                        case "sleepy":
                            msg = (
                                "\n".join(
                                    msg.splitlines()[
                                        : random.randint(
                                            1, len(msg.splitlines())
                                        )
                                    ]
                                )
                                + " *yawn*\n"
                                + "z" * random.randint(5, 10)
                            )
                        case "cryptic":
                            msg = codecs.encode(msg, "rot13")
                        case "goofy":
                            msg = "\n".join(
                                map(
                                    lambda i: i + "🤓" * random.randint(1, 3),
                                    msg.splitlines(),
                                )
                            )
                    return msg
                else:
                    return (
                        i + "."
                        if not (i := random.choice(self.statuses)).endswith(".")
                        and i.endswith(tuple(ascii_letters))
                        else i
                    )

            case "permissions":
                return self.permissionsCommand(event, args)
            case "register":
                if self.userDB.getUserInfo(event.user_id):
                    self.userDB.removeUserFromDatabase(event.user_id)
                self.userDB.addUserToDatabase(
                    await (
                        await self.session.get(
                            f"https://chat.stackexchange.com/users/thumbs/{event.user_id}"
                        )
                    ).json()
                )
                return "You have been registered! You don't have any permissions yet; ping an admin if you think you should."
            case "groups":
                match args["action"]:
                    case "list":
                        return f"All groups: {', '.join(self.config['groups'].keys())}"
                    case "members":
                        args["group"] = args["group"].removesuffix("s")
                        return f"Members of group {args['group']}: {', '.join(map(lambda i: i['name'], self.userDB.membersOfGroup(args['group'])))}"

            case "ping":
                args["group"] = args["group"].removesuffix("s")
                if not len(
                    message := " ".join(
                        [
                            "@" + user["name"]
                            for user in self.userDB.membersOfGroup(
                                args["group"]
                            )
                        ]
                    )
                    + " ^"
                ):
                    return "Nobody to ping."
                else:
                    return message
            case "coffee":
                return f"@{event.user_name if args['user'] == 'me' else args['user']} Here's your coffee: ☕"
            case "maul":
                if args["user"].lower() == "vyxalbot":
                    return "As if I'm going to let you do that, idiot."  # TODO: Maul the user who tried mauling the bot
                else:
                    return RAPTOR.format(user=args["user"].upper())
            case "cookie":
                if info := self.userDB.getUserInfo(event.user_id):
                    if "admin" in info["groups"]:
                        return "Here you go: 🍪"
                if random.random() <= 0.75:
                    return "Here you go: 🍪"
                else:
                    return "No."
            case "hug":
                return random.choice(self.messages["hugs"])
            case "!repo-list":
                return "Repositories: " + " | ".join(
                    [
                        formatRepo(item, False)
                        async for item in self.gh.getiter(
                            f"/users/{self.config['account']}/repos",
                            {"sort": "created"},
                            oauth_token=(await self.appToken(self.gh)).token,
                        )
                    ][:5]
                )
            case "!issue-open":
                try:
                    repo = args["repo"] or self.config["baseRepo"]
                    # ICKY SPECIAL CASING
                    if repo == "Vyxal":
                        if not isinstance(args["labels"], str):
                            return 'You must specify one of "version-2" or "version-3" as a label!'
                        if "version-3" not in args["labels"].split(
                            ";"
                        ) and "version-2" not in args["labels"].split(";"):
                            return 'You must specify one of "version-2" or "version-3" as a label!'
                    await self.gh.post(
                        f"/repos/{self.config['account']}/{repo}/issues",
                        data={
                            "title": args["title"],
                            "body": args["content"]
                            + f"\n\n_Issue created by {event.user_name} [here]({f'https://chat.stackexchange.com/transcript/{event.room_id}?m={event.message_id}#{event.message_id}'})_",
                            "labels": (
                                args["labels"].split(";")
                                if args["labels"]
                                else []
                            ),
                        },
                        oauth_token=(await self.appToken(self.gh)).token,
                    )
                    return None
                except GitHubHTTPException as e:
                    return f"Failed to create issue: {e.status_code.value} {e.status_code.description}"
            case "sus":
                if (
                    "__msg__" in args
                    and random.random() >= 0.25
                    and event.user_id != self.room.userID
                ):
                    return None
                return "ඞ" * random.randint(8, 64)
            case "amilyxal":
                return f"You are {'' if (event.user_id == 354515) != (random.random() <= 0.1) else 'not '}lyxal."
            case "prod":
                if (
                    repo := (
                        args["repo"]
                        if args["repo"]
                        else self.config["baseRepo"]
                    )
                ) not in self.config["production"].keys():
                    return f"That repository isn't listed in config.json."
                try:
                    await self.gh.post(
                        f"/repos/{self.config['account']}/{repo}/pulls",
                        data={
                            "title": f"Update production ({datetime.now().strftime('%b %d %Y')})",
                            "head": self.config["production"][repo]["head"],
                            "base": self.config["production"][repo]["base"],
                            "body": f"Requested by {event.user_name} [here]({f'https://chat.stackexchange.com/transcript/{event.room_id}?m={event.message_id}#{event.message_id})'}.",
                        },
                        oauth_token=(await self.appToken(self.gh)).token,
                    )
                    return None
                except ValidationError as e:
                    return f"Failed to create issue: Webhook validation failed: {e.errors.get('message', 'Unknown error')}"

                except GitHubHTTPException as e:
                    return f"Failed to create issue: {e.status_code.value} {e.status_code.description}"
            case "run":
                return "This command is disabled."
                # return
                task = create_task(self.runVyxalCommand(event, args))
                task.add_done_callback(self.runningTasks.discard)
                self.runningTasks.add(task)
            case "blame":
                return f"It was {random.choice(self.userDB.users())['name']}'s fault!"
            case "!good-bot":
                return await self.room.send(":3")
            case "hello":
                return random.choice(self.messages["hello"])
            case "goodbye":
                return random.choice(self.messages["goodbye"])

    async def onEditMessage(self, room: Room, event: UnknownEvent):
        myMessage: int = self.replyDB.getCorrespondingId(
            event.args["message_id"]
        )
        try:
            if match := re.fullmatch(
                r"!!\/(?P<command>.+)", event.args["content"]
            ):
                rawCommand = match["command"]
                for regex, command in COMMAND_REGEXES.items():
                    if match := re.fullmatch(regex, rawCommand):
                        response = self.runCommand(
                            room, event, command, match.groupdict()
                        )
                        if response is not None:
                            return await self.room.edit(
                                myMessage,
                                f":{myMessage}" + response,
                            )
                return await self.room.edit(
                    myMessage,
                    f"Sorry {event.user_name}, I'm afraid I can't do that.",
                )
        except Exception as e:
            msg = f"@Ginger An error occurred while handling message {event.message_id}!"
            await self.room.edit(myMessage, msg)
            self.logger.exception(msg)
            self.errorsSinceStartup += 1

    async def onMessage(self, room: Room, event: MessageEvent):
        try:
            if match := re.fullmatch(r"!!\/(?P<command>.+)", event.content):
                rawCommand = match["command"]
                for regex, command in COMMAND_REGEXES.items():
                    if match := re.fullmatch(regex, rawCommand):
                        response = self.runCommand(
                            room, event, command, match.groupdict()
                        )
                        if response is not None:
                            if isinstance(response, int):
                                return response
                            temp = await self.room.send(response)
                            self.replyDB.addReplyToDatabase(
                                [event.message_id, temp]
                            )
                            return temp
                return await self.room.send(
                    f"Sorry {event.user_name}, I'm afraid I can't do that."
                )
            for regex, command in MESSAGE_REGEXES.items():
                if match := re.fullmatch(regex, event.content):
                    response = self.runCommand(
                        room,
                        event,
                        command,
                        match.groupdict() | {"__msg__": True},
                    )
                    if response is not None:
                        await self.room.send(response)
        except Exception:
            msg = f"@Ginger An error occurred while handling message {event.message_id}!"
            await self.room.send(msg)
            self.logger.exception(msg)
            self.errorsSinceStartup += 1

    async def autoTag(self, event: GitHubEvent, gh: GitHubAPI):
        pullRequest = event.data["pull_request"]
        if (
            event.data["repository"]["name"]
            not in self.config["importantRepositories"]
        ):
            return
        if len(pullRequest["labels"]):
            return
        if not pullRequest["body"]:
            return
        token = (await self.appToken(gh)).token
        for match in re.finditer(
            r"(([Cc]lose[sd]?)|([Ff]ix(e[sd])?)|([Rr]esolve[sd]?)) #(?P<number>\d+)",
            pullRequest["body"],
        ):
            issue = await gh.getitem(
                f"/repos/{event.data['repository']['full_name']}/issues/{int(match.group('number'))}",
                oauth_token=token,
            )
            await gh.patch(
                f"/repos/{event.data['repository']['full_name']}/issues/{pullRequest['number']}",
                data={
                    "labels": list(
                        set(
                            filter(
                                None,
                                map(
                                    lambda i: TAG_MAP.get(i["name"], False),
                                    issue["labels"],
                                ),
                            )
                        )
                    )
                },
                oauth_token=token,
            )

    async def onIssueAction(self, event: GitHubEvent, gh: GitHubAPI):
        issue = event.data["issue"]
        match event.data["action"]:
            case "assigned":
                assignee = event.data["assignee"]
                self.logger.info(
                    f'Issue {issue["number"]} assigned to {assignee["login"]} by {event.data["sender"]["login"]} in {issue["repository_url"]}'
                )
                await self.room.send(
                    f'{formatUser(event.data["sender"])} assigned {formatUser(assignee)} to issue {formatIssue(issue)} in {formatRepo(event.data["repository"])}'
                )
            case "unassigned":
                issue = event.data["issue"]
                assignee = event.data["assignee"]
                self.logger.info(
                    f'Issue {issue["number"]} unassigned from {assignee["login"]} by {event.data["sender"]["login"]} in {issue["repository_url"]}'
                )
                await self.room.send(
                    f'{formatUser(event.data["sender"])} unassigned {formatUser(assignee)} from issue {formatIssue(issue)} in {formatRepo(event.data["repository"])}'
                )
            case _ as action if action in ["closed", "opened", "reopened"]:
                self.logger.info(
                    f'Issue {issue["number"]} {action} in {issue["repository_url"]}'
                )
                await self.room.send(
                    f'{formatUser(event.data["sender"])} {action} issue {formatIssue(issue)} in {formatRepo(event.data["repository"])}'
                )

    async def onPRAction(self, event: GitHubEvent, gh: GitHubAPI):
        pullRequest = event.data["pull_request"]
        match event.data["action"]:
            case "assigned":
                assignee = event.data["assignee"]
                self.logger.info(
                    f'Pull request {pullRequest["number"]} assigned to {assignee["login"]} by {event.data["sender"]["login"]} in {event.data["repository"]["html_url"]}'
                )
                await self.room.send(
                    f'{formatUser(event.data["sender"])} assigned {formatUser(assignee)} to pull request {formatIssue(pullRequest)} in {formatRepo(event.data["repository"])}'
                )
            case "unassigned":
                pullRequest = event.data["pull_request"]
                assignee = event.data["assignee"]
                self.logger.info(
                    f'Pull request {pullRequest["number"]} unassigned from {assignee["login"]} by {event.data["sender"]["login"]} in {event.data["repository"]["html_url"]}'
                )
                await self.room.send(
                    f'{formatUser(event.data["sender"])} unassigned {formatUser(assignee)} from pull request {formatIssue(pullRequest)} in {formatRepo(event.data["repository"])}'
                )
            case "closed":
                self.logger.info(
                    f'Pull request {pullRequest["number"]} {"merged" if pullRequest["merged"] else "closed"} in {event.data["repository"]["html_url"]}'
                )
                await self.room.send(
                    f'{formatUser(event.data["sender"])} {"merged" if pullRequest["merged"] else "closed"} pull request {formatIssue(pullRequest)} in {formatRepo(event.data["repository"])}'
                )
            case "review_requested":
                return  # user doesn't want this apparently
                await self.room.send(
                    f'{formatUser(event.data["sender"])} requested {formatUser(event.data["requested_reviewer"])}\'s review on {formatIssue(pullRequest)}'
                )
            case _ as action if action in ["opened", "reopened", "enqueued"]:
                self.logger.info(
                    f'Pull request {pullRequest["number"]} {action} in {event.data["repository"]["html_url"]}'
                )
                await self.room.send(
                    f'{formatUser(event.data["sender"])} {action} pull request {formatIssue(pullRequest)} in {formatRepo(event.data["repository"])}'
                )
                if action == "opened":
                    await self.autoTag(event, gh)

    async def onThingCreated(self, event: GitHubEvent, gh: GitHubAPI):
        if event.data["ref_type"] == "tag":
            return
        self.logger.info(
            f'{event.data["sender"]["login"]} created {event.data["ref_type"]} {event.data["ref"]} in {event.data["repository"]["html_url"]}'
        )
        await self.room.send(
            f'{formatUser(event.data["sender"])} created {event.data["ref_type"]} {event.data["ref"]} in {formatRepo(event.data["repository"])}'
        )

    async def onThingDeleted(self, event: GitHubEvent, gh: GitHubAPI):
        if event.data["ref_type"] == "tag":
            return
        self.logger.info(
            f'{event.data["sender"]["login"]} deleted {event.data["ref_type"]} {event.data["ref"]} in {event.data["repository"]["html_url"]}'
        )
        await self.room.send(
            f'{formatUser(event.data["sender"])} deleted {event.data["ref_type"]} {event.data["ref"]} in {formatRepo(event.data["repository"])}'
        )

    async def onReleaseCreated(self, event: GitHubEvent, gh: GitHubAPI):
        release = event.data["release"]
        self.logger.info(
            f'{event.data["sender"]["login"]} released {release["html_url"]}'
        )
        message = await self.room.send(
            f'__[{event.data["repository"]["name"]} {release["name"].lower()}]({release["html_url"]})__'
        )
        if (
            event.data["repository"]["name"]
            in self.config["importantRepositories"]
        ):
            await self.room.pin(message)

    async def onFork(self, event: GitHubEvent, gh: GitHubAPI):
        self.logger.info(
            f'{event.data["sender"]["login"]} forked {event.data["forkee"]["full_name"]} from {event.data["repository"]["full_name"]}'
        )
        await self.room.send(
            f'{formatUser(event.data["sender"])} forked {formatRepo(event.data["forkee"])} from {formatRepo(event.data["repository"])}'
        )

    async def onReviewSubmitted(self, event: GitHubEvent, g: GitHubAPI):
        review = event.data["review"]
        match review["state"]:
            case "commented":
                if not review["body"]:
                    return
                action = "commented on"
            case "approved":
                action = "approved"
            case "changes_requested":
                action = "requested changes on"
            case _:
                action = "did something to"
        await self.room.send(
            f'{formatUser(event.data["sender"])} [{action}]({review["html_url"]}) {formatIssue(event.data["pull_request"])}'
            + (': "' + msgify(review["body"]) + '"' if review["body"] else "")
        )

    async def onRepositoryCreated(self, event: GitHubEvent, g: GitHubAPI):
        await self.room.send(
            f'{formatUser(event.data["sender"])} created repository {formatRepo(event.data["repository"])}'
        )

    async def onRepositoryDeleted(self, event: GitHubEvent, g: GitHubAPI):
        await self.room.send(
            f'{formatUser(event.data["sender"])} deleted repository {formatRepo(event.data["repository"])}'
        )


def run():
    CONFIG_PATH = os.environ.get("VYXALBOT_CONFIG", "config.json")
    STORAGE_PATH = user_state_path("vyxalbot2", None, __version__)
    os.makedirs(STORAGE_PATH, exist_ok=True)
    DATA_PATH = Path(__file__).resolve().parent.parent / "data"
    MESSAGES_PATH = DATA_PATH / "messages.toml"
    STATUSES_PATH = DATA_PATH / "statuses.txt"

    logging.basicConfig(
        format="[%(name)s] %(levelname)s: %(message)s",
        stream=sys.stdout,
        level=logging.DEBUG,
    )

    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    with open(MESSAGES_PATH, "rb") as f:
        messages = tomli.load(f)
    with open(STATUSES_PATH, "r") as f:
        statuses = f.read().splitlines()

    async def makeApp():
        return VyxalBot2(
            config,
            cast(Any, messages),
            str(STORAGE_PATH / "storage.json"),
            statuses,
        )

    run_app(makeApp(), port=config["port"])
