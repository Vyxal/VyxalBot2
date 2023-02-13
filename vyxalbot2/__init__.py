from typing import Optional
from time import time
from datetime import datetime

import asyncio
import logging
import sys

from aiohttp import ClientSession
from aiohttp.web import Application, Request, Response
from sechat import Bot
from gidgethub.aiohttp import GitHubAPI as AsyncioGitHubAPI
from gidgethub.abc import GitHubAPI
from gidgethub.routing import Router
from gidgethub.sansio import Event as GitHubEvent
from gidgethub.apps import get_installation_access_token, get_jwt
from cachetools import LRUCache

from vyxalbot2.util import ConfigType, AppToken

logging.basicConfig(
    format="[%(name)s] %(levelname)s: %(message)s",
    stream=sys.stdout,
    level=logging.INFO,
)


class VyxalBot2(Application):
    def __init__(self, config: ConfigType) -> None:
        self.logger = logging.getLogger("VyxalBot2")
        super().__init__(logger=self.logger)

        self.config = config

        self.bot = Bot(logger=self.logger)
        self._appToken: Optional[AppToken] = None
        self.session = ClientSession()
        self.cache = LRUCache(maxsize=5000)
        self.ghRouter = Router()
        self.gh = AsyncioGitHubAPI(self.session, cache = self.cache)

        with open(self.config["pem"], "r") as f:
            self.privkey = f.read()

        self.router.add_post("/webhook", self.onHookRequest)

    async def on_startup(self):
        await self.bot.authenticate(
            self.config["SEEmail"], self.config["SEPassword"], self.config["SEHost"]
        )
        self.room = self.bot.joinRoom(self.config["SERoom"])
        await self.room.send("IT'S TIME TO BE A [Big Shot]")

    async def on_shutdown(self):
        await self.room.send("THIS IS JUST [[Victory Smoke]]!")
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
                self._appToken = AppToken(tokenData["token"], datetime.fromisoformat(tokenData["expires_at"]))
                return self._appToken
        raise ValueError("Unable to locate installation")

    async def onHookRequest(self, request: Request) -> Response:
        try:
            body = await request.read()
            event = GitHubEvent.from_http(request.headers, body, secret=self.config["webhookSecret"])
            self.logger.info(f"Recieved delivery #{event.delivery_id}")
            if event.event == "ping":
                return Response(status=200)
            await self.ghRouter.dispatch(event, self.gh)
            return Response(status=200)
        except Exception:
            self.logger.exception("An error occured while processing the request!")
            return Response(status=500)
