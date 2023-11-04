import random
from asyncio import get_event_loop

import logging
import inspect

from discord import Client, CustomActivity, Game, Intents, Interaction, Message, Object, TextChannel
from discord.app_commands import CommandTree, Command as DiscordCommand, Group
from discord.ext.tasks import loop
from vyxalbot2.commands import Command
from vyxalbot2.commands.discord import DiscordCommands
from vyxalbot2.services import Service
from vyxalbot2.reactions import Reactions
from vyxalbot2.types import CommandImpl, CommonData, EventInfo

class VBClient(Client):
    def __init__(self, guild: int, statuses: list[str]):
        super().__init__(intents=Intents.all())
        self.guild = Object(guild)
        self.statuses = statuses
        self.tree = CommandTree(self)

    def wrap(self, service: "DiscordService", impl: CommandImpl):
        # discord.py checks the signature of the wrapper to generate autocomplete,
        # so we inject the wrapped function's signature into the wrapper via dark Python magicks
        # do note: this operation does not actually change the signature of the function!
        # it just make it look like it's changed to inspect and other machinery
        # which would be bad in any other situation but this, although even here it's not great
        # TL;DR I used the inspect to bamboozle the inspect
        async def wrapper(interaction: Interaction, *args, **kwargs):
            assert interaction.channel_id is not None
            async for line in impl(
                EventInfo(
                    "", # :(
                    interaction.user.display_name,
                    interaction.user.display_avatar.url,
                    interaction.user.id,
                    interaction.channel_id,
                    interaction.id,
                    service
                ),
                *args, **kwargs
            ):
                await interaction.response.send_message(line)
 
        # 😰
        wrapSig = inspect.signature(wrapper)
        wrapper.__signature__ = wrapSig.replace(
            parameters=[wrapSig.parameters["interaction"], *tuple(inspect.signature(impl).parameters.values())[1:]]
        )
        return wrapper

    def addCommand(self, service: "DiscordService", command: Command):
        parts = command.name.split(" ")
        parent = None
        assert len(parts) > 0
        if len(parts) > 1:
            part = parts.pop(0)
            parent = self.tree.get_command(part)
            if parent is None:
                parent = Group(name=part, description="This seems to be a toplevel group of some kind.")
            assert not isinstance(parent, DiscordCommand), "Cannot nest commands under commands"
            while len(parts) > 1:
                part = parts.pop(0)
                newParent = parent.get_command(part)
                if newParent is None:
                    newParent = Group(
                        name=part,
                        parent=parent,
                        description="This seems to be a group of some kind."
                    )
                parent = newParent
                assert not isinstance(parent, DiscordCommand), "Cannot nest commands under commands"
        self.tree.add_command(DiscordCommand(
            name=parts[0],
            description=command.helpStr,
            callback=self.wrap(service, command.impl),
            parent=parent
        ))
    async def setup_hook(self):
        self.tree.copy_global_to(guild=self.guild)
        self.updateStatus.start()

    @loop(hours=1)
    async def updateStatus(self):
        await self.change_presence(activity=Game(name=random.choice(self.statuses)))


class DiscordService(Service):
    @classmethod
    async def create(cls, reactions: Reactions, common: CommonData):
        client = VBClient(common.privateConfig["discord"]["guild"], common.statuses)
        await client.login(common.privateConfig["discord"]["token"])
        instance = cls(client, reactions, common)
        await instance.startup()
        return instance

    def __init__(self, client: VBClient, reactions: Reactions, common: CommonData):
        assert client.user is not None, "Need to be logged in to Discord!"
        super().__init__("discord", client.user.id, DiscordCommands(common))
        
        self.logger = logging.getLogger("DiscordService")
        self.client = client
        self.client.event(self.on_message)
        self.common = common
        self.reactions = reactions

        for command in self.commands.commands.values():
            self.client.addCommand(self, command)
        
    async def startup(self):
        self.clientTask = get_event_loop().create_task(self.client.connect())
        await self.client.wait_until_ready()
        await self.client.tree.sync()
        eventChannel = self.client.get_channel(self.common.privateConfig["discord"]["eventChannel"])
        assert isinstance(eventChannel, TextChannel), str(eventChannel)
        self.eventChannel = eventChannel
        self.logger.info(f"Discord connection established! We are {self.client.user}.")

    async def on_message(self, message: Message):
        await self.messageSignal.send_async(self, event=EventInfo(
            content=message.content,
            userName=message.author.display_name,
            pfp=message.author.display_avatar.url,
            roomIdent=message.channel.id,
            userIdent=message.author.id,
            messageIdent=message.id,
            service=self
        ))

    async def shutdown(self):
        self.clientTask.cancel()
        await self.clientTask

    async def send(self, message: str):
        return (await self.eventChannel.send(message)).id

    async def pin(self, message: int):
        await self.eventChannel.get_partial_message(message).pin()