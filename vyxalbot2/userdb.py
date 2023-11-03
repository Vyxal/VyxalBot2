from typing import Optional
from blinker import Signal

from tinydb import TinyDB, Query
from tinydb.table import Document

from motor.motor_asyncio import AsyncIOMotorClient
from odmantic import AIOEngine, EmbeddedModel, Model, ObjectId
from vyxalbot2.services import Service

from vyxalbot2.types import GroupType

class User(Model):
    service: str
    serviceIdent: int
    name: str
    pfp: str
    groups: list[str] = []
    linked: dict[str, ObjectId] = {}

class UserDBOld:
    def __init__(self, dbPath: str, groupConfig: dict[str, GroupType]):
        self._db = TinyDB(dbPath)
        self.groupConfig = groupConfig

    def getUserInfo(self, user: int) -> Optional[Document]:
        return r[0] if len(r := self._db.search(Query().chatID == user)) else None

    def getUserInfoByName(self, name: str) -> Optional[Document]:
        return r[0] if len(r := self._db.search(Query().name == name)) else None

    def addUserToDatabase(self, userData: dict):
        self._db.insert(
            {"chatID": userData["id"], "name": userData["name"], "groups": []}
        )

    def refreshUserData(self, userData: dict):
        self._db.update({"name": userData["name"]}, Query().chatID == userData["id"])

    def removeUserFromDatabase(self, user: int):
        self._db.remove(Query().chatID == user)

    def addUserToGroup(self, user: Document, group: str):
        if group in user["groups"]:
            return False
        user["groups"].append(group)
        self._db.update({"groups": user["groups"]}, Query().chatID == user["chatID"])
        return True

    def removeUserFromGroup(self, user: Document, group: str):
        user["groups"].remove(group)
        self._db.update({"groups": user["groups"]}, Query().chatID == user["chatID"])

    def membersOfGroup(self, group: str):
        return self._db.search(Query().groups.any([group]))

    def users(self):
        return self._db.all()

class UserDB:
    userModify = Signal()
    def __init__(self, client, database: str):
        self.engine = AIOEngine(client=client, database=database)

    async def getUser(self, service: Service, ident: int) -> Optional[User]:
        return await self.engine.find_one(User, User.service == service.name, User.serviceIdent == ident)
    
    async def getUsers(self, service: Service):
        return await self.engine.find(User, User.service == service.name)

    async def getUserByName(self, service: Service, name: str) -> Optional[User]:
        return await self.engine.find_one(User, User.service == service.name, User.name == name)

    async def createUser(self, service: Service, ident: int, name: str, pfp: str):
        if (await self.getUser(service, ident)) is not None:
            raise ValueError("User exists")
        await self.save(User(service=service.name, serviceIdent=ident, name=name, pfp=pfp))

    async def linkUser(self, one: User, other: User):
        one.linked[other.service] = other.id
        other.linked[one.service] = one.id
        await self.save(one)
        await self.save(other)

    async def membersOfGroup(self, service: Service, group: str):
        return await self.engine.find(User, User.service == service.name, {"groups": group})

    async def save(self, user: User):
        await self.engine.save(user)
        await self.userModify.send_async(self)