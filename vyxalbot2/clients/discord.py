from functools import update_wrapper, wraps
import random
from typing import Callable
from discord import Client, CustomActivity, Intents, Interaction, Message, Object
from discord.app_commands import CommandTree, Command
from discord.ext.tasks import loop

from vyxalbot2.commands import CommonCommands
from vyxalbot2.reactions import Reactions
from vyxalbot2.types import EventInfo, MessagesType


class DiscordClient(Client):
    def __init__(
        self,
        guildId: int,
        commonCommands: CommonCommands,
        reactions: Reactions,
        messages: MessagesType,
        statuses: list[str],
    ):
        intents = Intents.all()
        super().__init__(intents=intents)

        self.commonCommands = commonCommands
        self.reactions = reactions
        self.messages = messages
        self.statuses = statuses

        self.guildObj = Object(guildId)
        self.tree = CommandTree(self)

    def commonWrapper(self, common: Callable):
        @wraps(common)
        async def wrapper(interaction: Interaction, *args):
            await interaction.response.defer(thinking=True)
            response = [
                line
                async for line in common(
                    EventInfo(
                        content=None,
                        userName=interaction.user.display_name,
                        pfp=interaction.user.display_avatar.url,
                        sentBySelf=False,
                    ),
                    *args
                )
            ]
            await interaction.followup.send("\n".join(response))
        return wrapper

    async def setup_hook(self):
        for command in self.commonCommands.commands.values():
            self.tree.add_command(
                Command(
                    name=command.name,
                    description=command.description,
                    callback=self.commonWrapper(command.impl),
                )
            )
        await self.tree.sync()
        self.updateStatus.start()

    @loop(hours=1)
    async def updateStatus(self):
        await self.wait_until_ready()
        await self.change_presence(activity=CustomActivity(random.choice(self.statuses)))

    async def on_message(self, message: Message):
        async for line in self.reactions.onMessage(
            EventInfo(
                message.content,
                message.author.display_name,
                message.author.display_avatar.url,
                message.author == self.user,
            )
        ):
            await message.channel.send(line)
