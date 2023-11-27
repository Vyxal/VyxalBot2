import re
from time import time

from typing import Optional
from aiohttp import ClientSession
from aiohttp.web import Application, Request, Response, run_app
from gidgethub.aiohttp import GitHubAPI as AsyncioGitHubAPI
from gidgethub.routing import Router
from gidgethub.sansio import Event as GitHubEvent
from gidgethub.apps import get_installation_access_token, get_jwt
from dateutil.parser import parse as parseDatetime
from cachetools import LRUCache
import jwt
from sechat import Room
from vyxalbot2.services import PinThat, Service

from vyxalbot2.types import AppToken, PublicConfigType

from .formatters import formatIssue, formatRef, formatRepo, formatUser, msgify
from vyxalbot2.util import GITHUB_MERGE_QUEUE

def wrap(fun):
    async def wrapper(self: "GitHubApplication", event: GitHubEvent, services: list[Service], gh: AsyncioGitHubAPI):
        lines = [i async for i in fun(self, event)]
        for service in services:
            ids = []
            for line in lines:
                if line == PinThat:
                    await service.pin(ids[-1])
                    continue
                # ZWJ so Bridget ignores it
                ids.append(await service.send("\u200d" + line, discordSuppressEmbeds=True))
    return wrapper

class GitHubApplication(Application):
    def __init__(self, publicConfig: PublicConfigType, privkey: str, appId: str, account: str, webhookSecret: str):
        super().__init__()
        self.services = []
        self.privkey = privkey
        self.appId = appId
        self.account = account
        self.webhookSecret = webhookSecret
        self.publicConfig = publicConfig

        self._appToken: Optional[AppToken] = None
        self.ghRouter = Router()
        self.cache = LRUCache(maxsize=5000)
        self.gh = AsyncioGitHubAPI(ClientSession(), "VyxalBot2", cache=self.cache)

        self.router.add_post("/webhook", self.onHookRequest)
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

    def getJwt(self, *, app_id: str, private_key: str) -> str:
        # This is a copy of gidgethub's get_jwt(), except with the expiry claim decreased a bit
        time_int = int(time())
        payload = {"iat": time_int - 60, "exp": time_int + (7 * 60), "iss": app_id}
        bearer_token = jwt.encode(payload, private_key, algorithm="RS256")

        return bearer_token

    async def appToken(self) -> str:
        if self._appToken != None:
            if self._appToken.expires.timestamp() > time():
                return self._appToken.token
        jwt = self.getJwt(app_id=self.appId, private_key=self.privkey)
        async for installation in self.gh.getiter(
            "/app/installations",
            jwt=jwt,
        ):
            if installation["account"]["login"] == self.account:
                tokenData = await get_installation_access_token(
                    self.gh,
                    installation_id=installation["id"],
                    app_id=self.appId,
                    private_key=self.privkey,
                )
                self._appToken = AppToken(
                    tokenData["token"], parseDatetime(tokenData["expires_at"], ignoretz=True)
                )
                return self._appToken.token
        raise ValueError("Unable to locate installation")

    async def onHookRequest(self, request: Request) -> Response:
        event = None
        try:
            body = await request.read()
            event = GitHubEvent.from_http(
                request.headers, body, secret=self.webhookSecret
            )
            self.logger.info(f"Recieved delivery #{event.delivery_id} ({event.event})")
            if event.event == "ping":
                return Response(status=200)
            if repo := event.data.get("repository", False):
                if repo["visibility"] == "private":
                    return Response(status=200)
                if repo["name"] in self.publicConfig["ignoredRepositories"]:
                    return Response(status=200)
            await self.ghRouter.dispatch(event, self.services, self.gh)
            return Response(status=200)
        except Exception:
            if event:
                msg = f"An error occured while processing event {event.delivery_id}!"
            else:
                msg = f"An error occured while processing a request!"
            self.logger.exception(msg)
            try:
                for service in self.services:
                    await service.send(f"@Ginger " + msg)
            except RuntimeError:
                pass
            return Response(status=500)

    async def autoTagPR(self, event: GitHubEvent):
        pullRequest = event.data["pull_request"]
        if (
            event.data["repository"]["name"]
            not in self.publicConfig["importantRepositories"]
        ):
            return
        if len(pullRequest["labels"]):
            return
    
        autotagConfig = self.publicConfig["autotag"].get(event.data["repository"]["name"])
        if autotagConfig is None:
            autotagConfig = self.publicConfig["autotag"].get("*", {"prregex": {}, "issue2pr": {}})
        tags = set()
        for regex, tag in autotagConfig["prregex"].items():
            if re.fullmatch(regex, pullRequest["head"]["ref"]) is not None:
                tags.add(tag)
        if pullRequest["body"]:
            for match in re.finditer(
                r"(([Cc]lose[sd]?)|([Ff]ix(e[sd])?)|([Rr]esolve[sd]?)) #(?P<number>\d+)",
                pullRequest["body"],
            ):
                issue = await self.gh.getitem(
                    f"/repos/{event.data['repository']['full_name']}/issues/{int(match.group('number'))}",
                    oauth_token=await self.appToken(),
                )
                for label in issue["labels"]:
                    if label["name"] in autotagConfig["issue2pr"]:
                        tags.add(autotagConfig["issue2pr"][label["name"]])

        await self.gh.patch(
            f"/repos/{event.data['repository']['full_name']}/issues/{pullRequest['number']}",
            data={"labels": list(tags)},
            oauth_token=await self.appToken(),
        )

    @wrap
    async def onPushAction(self, event: GitHubEvent):
        if (
            event.data["ref"].split("/")[1] != "heads"
            or event.data["pusher"]["name"] == GITHUB_MERGE_QUEUE
        ):
            return
        branch = "/".join(event.data["ref"].split("/")[2:])
        for commit in event.data["commits"]:
            if not commit["distinct"]:
                continue
            if event.data["pusher"]["name"] == event.data["sender"]["login"]:
                user = formatUser(event.data["sender"])
            else:
                user = event.data["pusher"]["name"]
            yield f"{user} {'force-pushed' if event.data['forced'] else 'pushed'} a [commit]({commit['url']}) to {formatRef(branch, event.data['repository'])} in {formatRepo(event.data['repository'])}: {commit['message'].splitlines()[0]}"

    @wrap
    async def onIssueAction(self, event: GitHubEvent):
        issue = event.data["issue"]
        match event.data["action"]:
            case "assigned":
                assignee = event.data["assignee"]
                yield f'{formatUser(event.data["sender"])} assigned {formatUser(assignee)} to issue {formatIssue(issue)} in {formatRepo(event.data["repository"])}'
                if assignee["login"] == event.data["sender"]["login"]:
                    yield "https://i.stack.imgur.com/1VzAJ.jpg"
            case "unassigned":
                issue = event.data["issue"]
                assignee = event.data["assignee"]
                yield f'{formatUser(event.data["sender"])} unassigned {formatUser(assignee)} from issue {formatIssue(issue)} in {formatRepo(event.data["repository"])}'
            case "closed":
                yield f'{formatUser(event.data["sender"])} closed issue {formatIssue(issue)} as {issue["state_reason"]} in {formatRepo(event.data["repository"])}'
            case _ as action if action in ["opened", "reopened"]:
                yield f'{formatUser(event.data["sender"])} {action} issue {formatIssue(issue)} in {formatRepo(event.data["repository"])}'

    @wrap
    async def onPRAction(self, event: GitHubEvent):
        pullRequest = event.data["pull_request"]
        match event.data["action"]:
            case "assigned":
                assignee = event.data["assignee"]
                yield f'{formatUser(event.data["sender"])} assigned {formatUser(assignee)} to pull request {formatIssue(pullRequest)} in {formatRepo(event.data["repository"])}'
            case "unassigned":
                pullRequest = event.data["pull_request"]
                assignee = event.data["assignee"]
                yield f'{formatUser(event.data["sender"])} unassigned {formatUser(assignee)} from pull request {formatIssue(pullRequest)} in {formatRepo(event.data["repository"])}'
            case "closed":
                yield f'{formatUser(event.data["sender"])} {"merged" if pullRequest["merged"] else "closed"} pull request {formatIssue(pullRequest)} in {formatRepo(event.data["repository"])}'
            case "review_requested":
                return  # user doesn't want this apparently
                yield f'{formatUser(event.data["sender"])} requested {formatUser(event.data["requested_reviewer"])}\'s review on {formatIssue(pullRequest)}'
            case "ready_for_review":
                yield f'{formatUser(event.data["sender"])} marked pull request {formatIssue(pullRequest)} ready for review'
            case _ as action if action in ["opened", "reopened", "enqueued"]:
                yield f'{formatUser(event.data["sender"])} {action} pull request {formatIssue(pullRequest)} in {formatRepo(event.data["repository"])}'
                if action == "opened":
                    await self.autoTagPR(event)

    @wrap
    async def onThingCreated(self, event: GitHubEvent):
        if event.data["ref_type"] == "tag":
            return
        if event.data["sender"]["login"] == GITHUB_MERGE_QUEUE:
            return
        yield f'{formatUser(event.data["sender"])} created {event.data["ref_type"]} {event.data["ref"]} in {formatRepo(event.data["repository"])}'

    @wrap
    async def onThingDeleted(self, event: GitHubEvent):
        if (
            event.data["ref_type"] == "tag"
            or event.data["sender"]["login"] == GITHUB_MERGE_QUEUE
        ):
            return
        yield f'{formatUser(event.data["sender"])} deleted {event.data["ref_type"]} {event.data["ref"]} in {formatRepo(event.data["repository"])}'

    @wrap
    async def onReleaseCreated(self, event: GitHubEvent):
        release = event.data["release"]
        releaseName = release["name"].lower()
        # attempt to match version number, otherwise default to the whole name
        if match := re.search(r"\d.*", releaseName):
            releaseName = match[0]
        
        yield f'__[{event.data["repository"]["name"]} {releaseName}]({release["html_url"]})__'
        if (
            event.data["repository"]["name"]
            in self.publicConfig["importantRepositories"]
        ):
            yield PinThat

    @wrap
    async def onFork(self, event: GitHubEvent):
        yield f'{formatUser(event.data["sender"])} forked {formatRepo(event.data["forkee"])} from {formatRepo(event.data["repository"])}'

    @wrap
    async def onReviewSubmitted(self, event: GitHubEvent):
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
        
        yield (
            f'{formatUser(event.data["sender"])} [{action}]({review["html_url"]}) {formatIssue(event.data["pull_request"])} in {formatRepo(event.data["repository"])}'
            + (': "' + msgify(review["body"]) + '"' if review["body"] else "")
        )

    @wrap
    async def onRepositoryCreated(self, event: GitHubEvent):
        yield f'{formatUser(event.data["sender"])} created repository {formatRepo(event.data["repository"])}'

    @wrap
    async def onRepositoryDeleted(self, event: GitHubEvent):
        yield f'{formatUser(event.data["sender"])} deleted repository {formatRepo(event.data["repository"])}'
