from typing import Optional
from time import time
from datetime import datetime

import asyncio
import logging
import sys

from aiohttp import ClientSession
from aiohttp.web import Application, Request, Response, GracefulExit
from sechat import Bot, Room, MessageEvent, EventType
from gidgethub.aiohttp import GitHubAPI as AsyncioGitHubAPI
from gidgethub.abc import GitHubAPI
from gidgethub.routing import Router
from gidgethub.sansio import Event as GitHubEvent
from gidgethub.apps import get_installation_access_token, get_jwt
from cachetools import LRUCache

from vyxalbot2.util import ConfigType, AppToken, formatUser, formatRepo


class VyxalBot2(Application):
    ADMIN_COMMANDS = ["die"]

    def __init__(self, config: ConfigType) -> None:
        self.logger = logging.getLogger("VyxalBot2")
        super().__init__(logger=self.logger)

        self.config = config

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
        self.on_shutdown.append(self.onShutdown)

        self.ghRouter.add(self.onIssueOpened, "issues", action="opened")
        self.ghRouter.add(self.onIssueClosed, "issues", action="closed")
        self.ghRouter.add(self.onIssueReopened, "issues", action="reopened")
        self.ghRouter.add(self.onIssueAssigned, "issues", action="assigned")
        self.ghRouter.add(self.onIssueUnassigned, "issues", action="unassigned")

        self.ghRouter.add(self.onPROpened, "pull_request", action="opened")
        self.ghRouter.add(self.onPRClosed, "pull_request", action="closed")
        self.ghRouter.add(self.onPRReopened, "pull_request", action="reopened")
        self.ghRouter.add(self.onPRAssigned, "pull_request", action="assigned")
        self.ghRouter.add(self.onPRUnassigned, "pull_request", action="unassigned")

        self.ghRouter.add(self.onThingCreated, "create")
        self.ghRouter.add(self.onReleaseCreated, "release", action="released")

    async def onStartup(self, _):
        await self.bot.authenticate(
            self.config["SEEmail"], self.config["SEPassword"], self.config["SEHost"]
        )
        self.room = self.bot.joinRoom(self.config["SERoom"])
        self.room.register(self.onMessage, EventType.MESSAGE)
        await self.room.send("IT'S TIME TO BE A [Big Shot]")

    async def onShutdown(self, _):
        await self.room.send("SEE YOU KID!")
        await self.session.close()
        await self.bot.__aexit__(None, None, None)  # DO NOT TRY THIS AT HOME

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
            await self.ghRouter.dispatch(event, self.gh)
            return Response(status=200)
        except Exception:
            if event:
                msg = f"An error occured while processing event {event.delivery_id}!"
            else:
                msg = f"An error occured while processing a request!"
            self.logger.exception(msg)
            await self.room.send(f"@Ginger " + msg)
            return Response(status=500)

    async def runCommand(
        self, room: Room, event: MessageEvent, command: str, args: list[str]
    ):
        if (
            command in VyxalBot2.ADMIN_COMMANDS
            and event.user_id not in self.config["admins"]
        ):
            await self.room.send("[Permissions] NO")
        match command:
            case "die":
                raise GracefulExit()
            case _:
                await self.room.send(
                    f"[{command.title()}]!? {event.user_name.upper()}!? WHAT ARE YOU TALKING ABOUT!?"
                )

    async def onMessage(self, room: Room, event: MessageEvent):
        if event.content.startswith("!!/"):
            command = event.content.removeprefix("!!/").split(" ")
            await self.runCommand(room, event, command[0], command[1:])

    async def onIssueOpened(self, event: GitHubEvent, gh: GitHubAPI):
        issue = event.data["issue"]
        self.logger.info(f'Issue {issue["number"]} opened in {issue["repository_url"]}')
        await self.room.send(
            f'{formatUser(issue["user"])} opened issue [#{issue["number"]}]({issue["url"]}) ({issue["title"]}) in {formatRepo(event.data["repository"])}'
        )

    async def onIssueClosed(self, event: GitHubEvent, gh: GitHubAPI):
        issue = event.data["issue"]
        self.logger.info(f'Issue {issue["number"]} closed in {issue["repository_url"]}')
        await self.room.send(
            f'{formatUser(issue["user"])} closed issue [#{issue["number"]}]({issue["url"]}) ({issue["title"]}) in {formatRepo(event.data["repository"])}'
        )

    async def onIssueReopened(self, event: GitHubEvent, gh: GitHubAPI):
        issue = event.data["issue"]
        self.logger.info(
            f'Issue {issue["number"]} reopened in {issue["repository_url"]}'
        )
        await self.room.send(
            (
                f'{formatUser(issue["user"])} reopened issue [#{issue["number"]}]({issue["url"]}) ({issue["title"]}) in {formatRepo(event.data["repository"])}'
            )
        )

    async def onIssueAssigned(self, event: GitHubEvent, gh: GitHubAPI):
        issue = event.data["issue"]
        assignee = event.data["assignee"]
        self.logger.info(
            f'Issue {issue["number"]} assigned to {assignee["login"]} by {issue["user"]["login"]} in {issue["repository_url"]}'
        )
        await self.room.send(
            f'{formatUser(issue["user"])} assigned [{assignee["login"]}]({assignee["html_url"]}) to issue [#{issue["number"]}]({issue["url"]}) ({issue["title"]}) in {formatRepo(event.data["repository"])}'
        )

    async def onIssueUnassigned(self, event: GitHubEvent, gh: GitHubAPI):
        issue = event.data["issue"]
        assignee = event.data["assignee"]
        self.logger.info(
            f'Issue {issue["number"]} unassigned from {assignee["login"]} by {issue["user"]["login"]} in {issue["repository_url"]}'
        )
        await self.room.send(
            f'{formatUser(issue["user"])} unassigned [{assignee["login"]}]({assignee["html_url"]}) from issue [#{issue["number"]}]({issue["url"]}) ({issue["title"]}) in {formatRepo(event.data["repository"])}'
        )

    async def onPROpened(self, event: GitHubEvent, gh: GitHubAPI):
        pullRequest = event.data["pullRequest"]
        self.logger.info(
            f'Pull request {pullRequest["number"]} opened in {pullRequest["repository_url"]}'
        )
        await self.room.send(
            f'{formatUser(pullRequest["user"])} opened pull request [#{pullRequest["number"]}]({pullRequest["url"]}) ({pullRequest["title"]}) in {formatRepo(event.data["repository"])}'
        )

    async def onPRClosed(self, event: GitHubEvent, gh: GitHubAPI):
        pullRequest = event.data["pullRequest"]
        self.logger.info(
            f'Pull request {pullRequest["number"]} closed in {pullRequest["repository_url"]}'
        )
        await self.room.send(
            f'{formatUser(pullRequest["user"])} closed pull request [#{pullRequest["number"]}]({pullRequest["url"]}) ({pullRequest["title"]}) in {formatRepo(event.data["repository"])}'
        )

    async def onPRReopened(self, event: GitHubEvent, gh: GitHubAPI):
        pullRequest = event.data["pullRequest"]
        self.logger.info(
            f'Pull request {pullRequest["number"]} reopened in {pullRequest["repository_url"]}'
        )
        await self.room.send(
            f'{formatUser(pullRequest["user"])} reopened pull request [#{pullRequest["number"]}]({pullRequest["url"]}) ({pullRequest["title"]}) in {formatRepo(event.data["repository"])}'
        )

    async def onPRAssigned(self, event: GitHubEvent, gh: GitHubAPI):
        pullRequest = event.data["pullRequest"]
        assignee = event.data["assignee"]
        self.logger.info(
            f'Pull request {pullRequest["number"]} assigned to {assignee["login"]} by {pullRequest["user"]["login"]} in {pullRequest["repository_url"]}'
        )
        await self.room.send(
            f'{formatUser(pullRequest["user"])} assigned [{assignee["login"]}]({assignee["html_url"]}) to pullRequest [#{pullRequest["number"]}]({pullRequest["url"]}) ({pullRequest["title"]}) in {formatRepo(event.data["repository"])}'
        )

    async def onPRUnassigned(self, event: GitHubEvent, gh: GitHubAPI):
        pullRequest = event.data["pullRequest"]
        assignee = event.data["assignee"]
        self.logger.info(
            f'Pull request {pullRequest["number"]} unassigned from {assignee["login"]} by {pullRequest["user"]["login"]} in {pullRequest["repository_url"]}'
        )
        await self.room.send(
            f'{formatUser(pullRequest["user"])} unassigned [{assignee["login"]}]({assignee["html_url"]}) from pullRequest [#{pullRequest["number"]}]({pullRequest["url"]}) ({pullRequest["title"]}) in {formatRepo(event.data["repository"])}'
        )

    async def onThingCreated(self, event: GitHubEvent, gh: GitHubAPI):
        self.logger.info(
            f'{event.data["sender"]["login"]} created {event.data["ref_type"]} {event.data["ref"]} in {event.data["repository"]["html_url"]}'
        )
        await self.room.send(
            f'{formatUser(event.data["sender"])} created {event.data["ref_type"]} {event.data["ref"]} in {formatRepo(event.data["repository"])}'
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