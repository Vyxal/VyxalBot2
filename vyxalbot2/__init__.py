from typing import Optional, cast, Any
from time import time
from datetime import datetime
from pathlib import Path

import logging
import sys
import json
import os
import signal
import random
import re

import tomli

from aiohttp import ClientSession
from aiohttp.web import Application, Request, Response, GracefulExit, run_app
from sechat import Bot, Room, MessageEvent, EventType
from gidgethub.aiohttp import GitHubAPI as AsyncioGitHubAPI
from gidgethub.abc import GitHubAPI
from gidgethub.routing import Router
from gidgethub.sansio import Event as GitHubEvent
from gidgethub.apps import get_installation_access_token, get_jwt
from cachetools import LRUCache

from vyxalbot2.util import (
    ConfigType,
    MessagesType,
    AppToken,
    formatUser,
    formatRepo,
    formatIssue,
    msgify,
    COMMAND_REGEXES,
    MESSAGE_REGEXES,
    RAPTOR,
)

__version__ = "2.0.0"


class VyxalBot2(Application):
    ADMIN_COMMANDS = ["die"]

    def __init__(
        self, config: ConfigType, messages: MessagesType, statuses: list[str]
    ) -> None:
        self.logger = logging.getLogger("VyxalBot2")
        super().__init__(logger=self.logger)

        self.config = config
        self.messages = messages
        self.statuses = statuses
        self.errorsSinceStartup = 0

        self.bot = Bot(logger=self.logger)
        self._appToken: Optional[AppToken] = None
        self.session = ClientSession()
        self.cache = LRUCache(maxsize=5000)
        self.ghRouter = Router()
        self.gh = AsyncioGitHubAPI(self.session, "VyxalBot2", cache=self.cache)

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

        self.ghRouter.add(self.onRepositoryCreated, "repository", action="created")
        self.ghRouter.add(self.onRepositoryDeleted, "repository", action="deleted")

    async def onStartup(self, _):
        await self.bot.authenticate(
            self.config["SEEmail"], self.config["SEPassword"], self.config["SEHost"]
        )
        self.room = self.bot.joinRoom(self.config["SERoom"])
        self.room.register(self.onMessage, EventType.MESSAGE)
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
            if installation["account"]["id"] == self.config["accountID"]:
                tokenData = await get_installation_access_token(
                    gh,
                    installation_id=installation["id"],
                    app_id=self.config["appID"],
                    private_key=self.privkey,
                )
                self._appToken = AppToken(
                    tokenData["token"], datetime.fromisoformat(tokenData["expires_at"])
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
            self.logger.info(f"Recieved delivery #{event.delivery_id} ({event.event})")
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

    async def runCommand(
        self, room: Room, event: MessageEvent, command: str, args: dict[str, Any]
    ):
        if event.message_id == room.userID:
            return
        if (
            command in VyxalBot2.ADMIN_COMMANDS
            and event.message_id not in self.config["admins"]
        ):
            await self.room.reply(event.message_id, "You do not have permission to run that command. If you think you should be able to, ping Ginger.")
            return
        match command:
            case "help":
                if commandName := args.get("command", ""):
                    if commandName == "me":
                        await self.room.reply(
                            event.message_id, "I'd love to, but I don't have any limbs."
                        )
                    else:
                        await self.room.reply(
                            event.message_id,
                            self.messages["commandhelp"].get(
                                commandName, "No help is available for that command."
                            ),
                        )
                else:
                    await self.room.reply(
                        event.message_id, self.messages["help"].format(version=__version__) + f"{', '.join(sorted(set(COMMAND_REGEXES.values())))}"
                    )
            case "info":
                await self.room.reply(event.message_id, self.messages["info"])
            case "status":
                if args.get("boring", ""):
                    await self.room.reply(
                        event.message_id,
                        f"Bot status: Online\nUptime: {datetime.now() - self.startupTime}\nRunning since: {self.startupTime.isoformat()}\nErrors since startup: {self.errorsSinceStartup}",
                    )
                else:
                    await self.room.reply(
                        event.message_id, "I am doing " + random.choice(self.statuses)
                    )
            case "coffee":
                await self.room.send(f"@{event.user_name if args['user'] == 'me' else args['user']} Here's your coffee: ☕")
            case "maul":
                await self.room.send(RAPTOR.format(user=args["user"].upper()))
            case "die":
                signal.raise_signal(signal.SIGINT)
            case "amiadmin":
                await self.room.reply(event.message_id, f"You are{' ' if event.user_id in self.config['admins'] else ' not'} a bot admin.")

    async def onMessage(self, room: Room, event: MessageEvent):
        try:
            if match := re.fullmatch(r"!!\/(?P<command>.+)", event.content):
                rawCommand = match["command"]
                for regex, command in COMMAND_REGEXES.items():
                    if match := re.fullmatch(regex, rawCommand):
                        return await self.runCommand(
                            room, event, command, match.groupdict()
                        )
                await self.room.send(f"Sorry {event.user_name}, I'm afraid can't do that.")
        except Exception:
            msg = f"@Ginger An error occurred while handling message {event.message_id}!"
            await self.room.send(msg)
            self.logger.exception(msg)
            self.errorsSinceStartup += 1

    async def onIssueAction(self, event: GitHubEvent, gh: GitHubAPI):
        issue = event.data["issue"]
        match event.data["action"]:
            case "assigned":
                assignee = event.data["assignee"]
                self.logger.info(
                    f'Issue {issue["number"]} assigned to {assignee["login"]} by {issue["user"]["login"]} in {issue["repository_url"]}'
                )
                await self.room.send(
                    f'{formatUser(issue["user"])} assigned {formatUser(assignee)} to issue {formatIssue(issue)} in {formatRepo(event.data["repository"])}'
                )
            case "unassigned":
                issue = event.data["issue"]
                assignee = event.data["assignee"]
                self.logger.info(
                    f'Issue {issue["number"]} unassigned from {assignee["login"]} by {issue["user"]["login"]} in {issue["repository_url"]}'
                )
                await self.room.send(
                    f'{formatUser(issue["user"])} unassigned {formatUser(assignee)} from issue {formatIssue(issue)} in {formatRepo(event.data["repository"])}'
                )
            case _ as action if action in ["closed", "opened", "reopened"]:
                self.logger.info(
                    f'Issue {issue["number"]} {action} in {issue["repository_url"]}'
                )
                await self.room.send(
                    f'{formatUser(issue["user"])} {action} issue {formatIssue(issue)} in {formatRepo(event.data["repository"])}'
                )

    async def onPRAction(self, event: GitHubEvent, gh: GitHubAPI):
        pullRequest = event.data["pull_request"]
        match event.data["action"]:
            case "assigned":
                assignee = event.data["assignee"]
                self.logger.info(
                    f'Pull request {pullRequest["number"]} assigned to {assignee["login"]} by {pullRequest["user"]["login"]} in {event.data["repository"]["html_url"]}'
                )
                await self.room.send(
                    f'{formatUser(pullRequest["user"])} assigned {formatUser(assignee)} to pull request {formatIssue(pullRequest)} in {formatRepo(event.data["repository"])}'
                )
            case "unassigned":
                pullRequest = event.data["issue"]
                assignee = event.data["assignee"]
                self.logger.info(
                    f'Pull request {pullRequest["number"]} unassigned from {assignee["login"]} by {pullRequest["user"]["login"]} in {event.data["repository"]["html_url"]}'
                )
                await self.room.send(
                    f'{formatUser(pullRequest["user"])} unassigned {formatUser(assignee)} from pull request {formatIssue(pullRequest)} in {formatRepo(event.data["repository"])}'
                )
            case _ as action if action in ["closed", "opened", "reopened", "enqueued"]:
                self.logger.info(
                    f'Pull request {pullRequest["number"]} {action} in {event.data["repository"]["html_url"]}'
                )
                await self.room.send(
                    f'{formatUser(pullRequest["user"])} {action} pull request {formatIssue(pullRequest)} in {formatRepo(event.data["repository"])}'
                )

    async def onThingCreated(self, event: GitHubEvent, gh: GitHubAPI):
        self.logger.info(
            f'{event.data["sender"]["login"]} created {event.data["ref_type"]} {event.data["ref"]} in {event.data["repository"]["html_url"]}'
        )
        await self.room.send(
            f'{formatUser(event.data["sender"])} created {event.data["ref_type"]} {event.data["ref"]} in {formatRepo(event.data["repository"])}'
        )

    async def onThingDeleted(self, event: GitHubEvent, gh: GitHubAPI):
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
            f'{formatUser(event.data["sender"])} released [{release["name"]}]({release["html_url"]}) in {formatRepo(event.data["repository"])}'
        )
        if event.data["repository"]["name"] in self.config["importantRepositories"]:
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
        return VyxalBot2(config, cast(Any, messages), statuses)

    run_app(makeApp(), port=config["port"])
