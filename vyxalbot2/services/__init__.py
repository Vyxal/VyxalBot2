from typing import Self, TYPE_CHECKING

if TYPE_CHECKING:
    from vyxalbot2.commands import CommandSupplier
    from vyxalbot2.reactions import Reactions
    from vyxalbot2.types import CommonData, EventInfo

PinThat = object()

class Service:
    @classmethod
    async def create(cls, reactions: "Reactions", common: "CommonData") -> Self:
        raise NotImplementedError

    def __init__(self, name: str, clientIdent: int, commands: "CommandSupplier"):
        self.name = name
        self.clientIdent = clientIdent
        self.commands = commands

    async def startup(self):
        pass
    async def shutdown(self):
        pass

    def invokeCommand(self, name: str, event: "EventInfo", *args):
        return self.commands.invoke(name, event, *args)

    async def send(self, message: str):
        raise NotImplementedError

    async def pin(self, message: int):
        raise NotImplementedError