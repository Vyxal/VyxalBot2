from typing import cast, Any
from enum import Enum
from io import BytesIO
from dataclasses import dataclass, field, InitVar

from websockets.client import connect

import msgpack


class ATOException(Exception):
    def __init__(self, code, message):
        super().__init__(code, message)
        self.code = code
        self.message = message


class StatusType(Enum):
    EXITED = "exited"
    KILLED = "killed"
    CORE_DUMPED = "core_dumped"
    UNKNOWN = "unknown"
    TIMED_OUT = "timed_out"


@dataclass(repr=True)
class Status:
    type: StatusType
    code: int


@dataclass(repr=True)
class Result:
    stdout: BytesIO
    stderr: BytesIO
    stdout_truncated: bool
    stderr_truncated: bool
    status: Status = field(init=False)
    status_type: InitVar[str]
    status_value: InitVar[int]
    timed_out: InitVar[bool]
    real: int
    kernel: int
    user: int
    max_mem: int
    waits: int
    preemptions: int
    major_page_faults: int
    minor_page_faults: int
    input_ops: int
    output_ops: int

    def __post_init__(self, status_type: str, status_value: int, timed_out: bool):
        if timed_out:
            self.status = Status(StatusType.TIMED_OUT, status_value)
        else:
            self.status = Status(StatusType(status_type), status_value)


class ATO:
    def __init__(self, address="wss://ato.pxeger.com/api/v1/ws/execute"):
        self.address = address

    async def run(self, language: str, code: str, input: str = "", timeout: int = 10):
        async with connect(self.address) as socket:
            await socket.send(
                cast(
                    bytes,
                    msgpack.dumps(
                        {
                            "language": language,
                            "code": code,
                            "input": input,
                            "options": [],
                            "arguments": [],
                            "timeout": timeout,
                        }
                    ),
                )
            )
            stdout = BytesIO()
            stderr = BytesIO()
            async for message in socket:
                data = cast(dict[str, Any], msgpack.loads(message))
                if "Done" in data.keys():
                    stdout.seek(0)
                    stderr.seek(0)
                    return Result(stdout, stderr, **data["Done"])
                elif "Stdout" in data.keys():
                    stdout.write(data["Stdout"])
                elif "Stderr" in data.keys():
                    stderr.write(data["Stderr"])
                else:
                    raise RuntimeError("Unknown key type", data)
        raise RuntimeError()
