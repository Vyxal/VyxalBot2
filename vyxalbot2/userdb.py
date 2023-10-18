from typing import Optional

from tinydb import TinyDB, Query
from tinydb.table import Document

from vyxalbot2.types import GroupType


class UserDB:
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
