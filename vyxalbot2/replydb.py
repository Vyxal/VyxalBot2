from typing import Optional

from tinydb import TinyDB, Query
from tinydb.table import Document


class ReplyDB:
    def __init__(self, dbPath: str):
        self._db = TinyDB(dbPath)

    def getCorrespondingId(self, msg: int) -> Optional[Document]:
        return (
            r[0] if len(r := self._db.search(Query().parentId == msg)) else None
        )

    def addReplyToDatabase(self, messageMap: list):
        self._db.insert(
            {"parentId": messageMap[0], "botMessageId": messageMap[1]}
        )

    def removeReplyId(self, msg: int):
        self._db.remove(Query().parentId == msg)
