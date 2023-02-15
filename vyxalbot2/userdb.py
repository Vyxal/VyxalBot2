from typing import Optional

from tinydb import TinyDB, Query
from tinydb.table import Document

from vyxalbot2.util import GroupType


class UserDB:
    def __init__(self, dbPath: str, groupConfig: dict[str, GroupType]):
        self._db = TinyDB(dbPath)
        self.groupConfig = groupConfig

    def getUserInfo(self, user: int) -> Optional[Document]:
        return r[0] if len(r := self._db.search(Query().chatID == user)) else None

    def addUserToDatabase(self, userData: dict):
        self._db.insert(
            {"chatID": userData["id"], "name": userData["name"], "groups": []}
        )

    def removeUserFromDatabase(self, user: int):
        self._db.remove(Query().chatID == user)

    def addUserToGroup(self, user: Document, group: str):
        user["groups"].append(group)
        self._db.update(
            {"groups": user["groups"]}, Query().chatID == user["chatID"]
        )

    def removeUserFromGroup(self, user: Document, group: str):
        user["groups"].remove(group)
        self._db.update(
            {"groups": user["groups"]}, Query().chatID == user["chatID"]
        )
