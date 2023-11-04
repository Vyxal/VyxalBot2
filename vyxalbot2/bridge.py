from logging import getLogger
from aiohttp import ClientSession
from discord import Client, Guild, TextChannel
from vyxalbot2.services import Service
from vyxalbot2.services.discord import DiscordService
from vyxalbot2.types import CommonData, EventInfo
from vyxalbot2.userdb import User


class DiscordBridge:
    def __init__(self, source: Service, discord: DiscordService, guild: Guild, common: CommonData):
        self.logger = getLogger("DiscordBridge")
        self.source = source
        self.discord = discord
        self.guild = guild
        self.common = common

        self.webhook = None

        channel = self.guild.get_channel(common.privateConfig["discord"]["bridgeChannel"])
        assert isinstance(channel, TextChannel)
        self.channel = channel
        source.messageSignal.connect(self.onMessage, source, False)
        discord.messageSignal.connect(self.onDiscordMessage, discord, False)

    async def fetchPFP(self, pfp: str):
        async with ClientSession() as session:
            async with session.get(pfp) as response:
                return await response.content.read()

    async def start(self):
        self.webhook = (await self.channel.webhooks())[0]
        self.logger.info("Ready!")

    async def onMessage(self, sender, event: EventInfo, directedAtUs: bool = False):
        if directedAtUs:
            return
        assert self.webhook is not None
        await self.webhook.send(event.content, username=event.userName, avatar_url=event.pfp)

    async def onDiscordMessage(self, sender, event: EventInfo, directedAtUs: bool = False):
        assert self.discord.client.user is not None
        assert self.webhook is not None
        if event.roomIdent != self.channel.id:
            return
        if event.userIdent == self.discord.client.user.id:
            return
        if event.userIdent == self.webhook.id:
            return
        await self.source.send(f"◈ [{event.userName}] " + event.content)