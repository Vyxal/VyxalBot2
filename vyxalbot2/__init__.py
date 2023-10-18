from typing import Optional, cast, Any
from time import time
from datetime import datetime
from pathlib import Path
from asyncio import create_task, wait_for
from html import unescape
from string import ascii_letters

import logging
import sys
import json
import os
import random
import re
import codecs
import base64
import subprocess

import tomli
import yaml

from aiohttp import ClientSession
from aiohttp.web import Application, Request, Response, run_app
from aiohttp.client_exceptions import ContentTypeError
from sechat import Bot, Room, MessageEvent, EventType
from gidgethub import HTTPException as GitHubHTTPException, ValidationError
from gidgethub.aiohttp import GitHubAPI as AsyncioGitHubAPI
from gidgethub.abc import GitHubAPI
from gidgethub.routing import Router
from gidgethub.sansio import Event as GitHubEvent
from gidgethub.apps import get_installation_access_token, get_jwt
from cachetools import LRUCache
from platformdirs import user_state_path
from dateutil.parser import parse as parseDatetime
from uwuivy import uwuipy

from vyxalbot2.userdb import UserDB
from vyxalbot2.util import (
    GITHUB_MERGE_QUEUE,
    formatUser,
    formatRepo,
    formatIssue,
    formatRef,
    msgify,
    RAPTOR,
)
from vyxalbot2.types import PublicConfigType, PrivateConfigType, MessagesType, AppToken
from vyxalbot2.chat import Chat

__version__ = "2.0.0"


class VyxalBot2(Application):
    ADMIN_COMMANDS = ["die"]

    def __init__(
        self,
        publicConfig: PublicConfigType,
        privateConfig: PrivateConfigType,
        messages: MessagesType,
        storagePath: str,
        statuses: list[str],
    ) -> None:
        self.logger = logging.getLogger("VyxalBot2")
        super().__init__(logger=self.logger)

        self.publicConfig = publicConfig
        self.privateConfig = privateConfig
        self.messages = messages
        self.statuses = list(filter(lambda i: hash(i) != -327901152, statuses))
        self.userDB = UserDB(storagePath, self.publicConfig["groups"])
        self.errorsSinceStartup = 0
        self.lu = False

        self.bot = Bot(logger=self.logger)
        self._appToken: Optional[AppToken] = None
        self.session = ClientSession()
        self.cache = LRUCache(maxsize=5000)
        self.ghRouter = Router()
        self.gh = AsyncioGitHubAPI(self.session, "VyxalBot2", cache=self.cache)
        self.runningTasks = set()

        with open(self.privateConfig["pem"], "r") as f:
            self.privkey = f.read()

        self.router.add_post("/webhook", self.onHookRequest)
        self.on_startup.append(self.onStartup)
        self.on_cleanup.append(self.onShutdown)

        self.ghRouter.add(self.onPushAction, "push")
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
            self.privateConfig["chat"]["email"],
            self.privateConfig["chat"]["password"],
            self.privateConfig["chat"]["host"],
        )
        self.room = await self.bot.joinRoom(self.privateConfig["chat"]["room"])
        self.chat = Chat(self.room, self.userDB, self.gh, self.publicConfig, self.privateConfig, self.messages, self.statuses)
        await self.room.send(
            "Well, here we are again."
            if random.random() > 0.01
            else "GOOD MORNING, MOTHERF***ERS"
        )
        self.startupTime = datetime.now()

    async def onShutdown(self, _):
        try:
            await self.room.send("Ah'll be bahk.")
        except RuntimeError:
            pass
        await wait_for(
            self.bot.__aexit__(None, None, None), 6
        )  # DO NOT TRY THIS AT HOME
        await wait_for(self.session.close(), 3)

    async def appToken(self, gh: GitHubAPI) -> AppToken:
        if self._appToken != None:
            if self._appToken.expires.timestamp() > time():
                return self._appToken
        jwt = get_jwt(app_id=self.privateConfig["appID"], private_key=self.privkey)
        async for installation in gh.getiter(
            "/app/installations",
            jwt=jwt,
        ):
            if installation["account"]["login"] == self.privateConfig["account"]:
                tokenData = await get_installation_access_token(
                    gh,
                    installation_id=installation["id"],
                    app_id=self.privateConfig["appID"],
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
                request.headers, body, secret=self.privateConfig["webhookSecret"]
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

    async def autoTagPR(self, event: GitHubEvent, gh: GitHubAPI):
        pullRequest = event.data["pull_request"]
        if (
            event.data["repository"]["name"]
            not in self.publicConfig["importantRepositories"]
        ):
            return
        if len(pullRequest["labels"]):
            return
        
        token = (await self.appToken(gh)).token
        autotagConfig = self.publicConfig["autotag"].get(
            event.data["repository"]["full_name"], self.publicConfig["autotag"].get("*", {"prregex": {}, "issue2pr": {}})
        )
        tags = set()
        for regex, tag in autotagConfig["prregex"].items():
            if re.fullmatch(regex, pullRequest["head"]["ref"]) is not None:
                tags.add(tag)
        if pullRequest["body"]:
            for match in re.finditer(
                r"(([Cc]lose[sd]?)|([Ff]ix(e[sd])?)|([Rr]esolve[sd]?)) #(?P<number>\d+)",
                pullRequest["body"],
            ):
                issue = await gh.getitem(
                    f"/repos/{event.data['repository']['full_name']}/issues/{int(match.group('number'))}",
                    oauth_token=token,
                )
                tags.update(
                    filter(
                        None,
                        map(
                            lambda i: autotagConfig["issue2pr"].get(i["name"], False),
                            issue["labels"],
                        ),
                    )
                )

        await gh.patch(
            f"/repos/{event.data['repository']['full_name']}/issues/{pullRequest['number']}",
            data={"labels": list(tags)},
            oauth_token=token,
        )

    async def onPushAction(self, event: GitHubEvent, gh: GitHubAPI):
        if (
            event.data["ref"].split("/")[1] != "heads"
            or event.data["pusher"]["name"] == GITHUB_MERGE_QUEUE
        ):
            return  # It's probably a tag push
        branch = event.data["ref"].split("/")[2]
        for commit in event.data["commits"]:
            if not commit["distinct"]:
                continue
            if event.data["pusher"]["name"] == event.data["sender"]["login"]:
                user = formatUser(event.data["sender"])
            else:
                user = event.data["pusher"]["name"]
            await self.room.send(
                f"{user} {'force-pushed' if event.data['forced'] else 'pushed'} a [commit]({commit['url']}) to {formatRef(branch, event.data['repository'])} in {formatRepo(event.data['repository'])}: {commit['message'].splitlines()[0]}"
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
                if assignee["login"] == event.data["sender"]["login"]:
                    await self.room.send(
                        "https://i.stack.imgur.com/1VzAJ.jpg"
                    )  # Obama gives himself a medal image
            case "unassigned":
                issue = event.data["issue"]
                assignee = event.data["assignee"]
                self.logger.info(
                    f'Issue {issue["number"]} unassigned from {assignee["login"]} by {event.data["sender"]["login"]} in {issue["repository_url"]}'
                )
                await self.room.send(
                    f'{formatUser(event.data["sender"])} unassigned {formatUser(assignee)} from issue {formatIssue(issue)} in {formatRepo(event.data["repository"])}'
                )
            case "closed":
                self.logger.info(
                    f'Issue {issue["number"]} closed as {issue["state_reason"]} in {issue["repository_url"]}'
                )
                await self.room.send(
                    f'{formatUser(event.data["sender"])} closed issue {formatIssue(issue)} as {issue["state_reason"]} in {formatRepo(event.data["repository"])}'
                )
            case _ as action if action in ["opened", "reopened"]:
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
                    await self.autoTagPR(event, gh)

    async def onThingCreated(self, event: GitHubEvent, gh: GitHubAPI):
        if event.data["ref_type"] == "tag":
            return
        if event.data["sender"]["login"] == GITHUB_MERGE_QUEUE:
            return
        self.logger.info(
            f'{event.data["sender"]["login"]} created {event.data["ref_type"]} {event.data["ref"]} in {event.data["repository"]["html_url"]}'
        )
        await self.room.send(
            f'{formatUser(event.data["sender"])} created {event.data["ref_type"]} {event.data["ref"]} in {formatRepo(event.data["repository"])}'
        )

    async def onThingDeleted(self, event: GitHubEvent, gh: GitHubAPI):
        if (
            event.data["ref_type"] == "tag"
            or event.data["sender"]["login"] == GITHUB_MERGE_QUEUE
        ):
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

        releaseName = release["name"].lower()
        # attempt to match version number, otherwise default to previous behaviour
        if match := re.search(r"\d.*", releaseName):
            releaseName = match[0]
        message = await self.room.send(
            f'__[{event.data["repository"]["name"]} {releaseName}]({release["html_url"]})__'
        )
        if (
            event.data["repository"]["name"]
            in self.publicConfig["importantRepositories"]
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
            f'{formatUser(event.data["sender"])} [{action}]({review["html_url"]}) {formatIssue(event.data["pull_request"])} in {formatRepo(event.data["repository"])}'
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
    PUBLIC_CONFIG_PATH = os.environ.get("VYXALBOT_CONFIG_PUBLIC", "config.json")
    PRIVATE_CONFIG_PATH = os.environ.get("VYXALBOT_CONFIG_PRIVATE", "private.json")
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

    with open(PUBLIC_CONFIG_PATH, "r") as f:
        publicConfig = json.load(f)
    with open(PRIVATE_CONFIG_PATH, "r") as f:
        privateConfig = json.load(f)
    with open(MESSAGES_PATH, "rb") as f:
        messages = tomli.load(f)
    with open(STATUSES_PATH, "r") as f:
        statuses = f.read().splitlines()

    async def makeApp():
        return VyxalBot2(
            publicConfig,
            privateConfig,
            cast(Any, messages),
            str(STORAGE_PATH / "storage.json"),
            statuses,
        )

    run_app(makeApp(), port=privateConfig["port"])
