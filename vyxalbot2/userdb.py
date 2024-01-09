from typing import Optional

from blinker import Signal
from odmantic import AIOEngine, Model, ObjectId


class User(Model):
    service: str
    serviceIdent: int
    name: str
    pfp: str
    groups: list[str] = []
    linked: dict[str, ObjectId] = {}
    bonusData: dict[str, str] = {}


class UserDB:
    userModify = Signal()

    def __init__(self, client, database: str):
        self.engine = AIOEngine(client=client, database=database)

    async def checkAuthentication(self, service: str, ident: int, command: str):
        return True # TODO

    async def getUser(self, service: str, ident: int) -> Optional[User]:
        return await self.engine.find_one(
            User, User.service == service, User.serviceIdent == ident
        )

    async def getUsers(self, service: str):
        return await self.engine.find(User, User.service == service)

    async def getUserByName(self, service: str, name: str) -> Optional[User]:
        return await self.engine.find_one(
            User, User.service == service, User.name == name
        )

    async def createUser(self, service: str, ident: int, name: str, pfp: str):
        if (await self.getUser(service, ident)) is not None:
            raise ValueError("User exists")
        await self.save(
            User(service=service, serviceIdent=ident, name=name, pfp=pfp)
        )

    async def linkUser(self, one: User, other: User):
        one.linked[other.service] = other.id
        other.linked[one.service] = one.id
        await self.save(one)
        await self.save(other)

    async def membersOfGroup(self, service: str, group: str):
        return await self.engine.find(
            User, User.service == service, {"groups": group}
        )

    async def save(self, user: User):
        await self.engine.save(user)
        await self.userModify.send_async(self)
