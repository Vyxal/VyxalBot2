from collections import UserDict
from dataclasses import dataclass
from enum import Enum
from typing import Any, AsyncGenerator, Callable, Self

import re
import inspect


from vyxalbot2.types import EventInfo

class Command(dict[str, Self]):
    def __init__(self, name: str, doc: str, impl: Callable[..., AsyncGenerator[Any, None]]):
        super().__init__()
        self.name = name
        self.helpStr = doc
        self.impl = impl

    def __hash__(self):
        return hash(self.name)

    @property
    def fullHelp(self):
        parameters = []
        for parameter in inspect.signature(self.impl).parameters.values():
            if parameter.name in ("event", "self"):
                continue
            if issubclass(parameter.annotation, Enum):
                typeString = "|".join(member.value for member in parameter.annotation)
                if parameter.default is not parameter.empty:
                    assert isinstance(parameter.default, parameter.annotation)
                    typeString += " = " + parameter.default.value
            else:
                typeString = parameter.annotation.__name__
            if parameter.default is not parameter.empty:
                parameters.append(f"[{parameter.name}: {typeString}]")
            else:
                parameters.append(f"<{parameter.name}: {typeString}>")
        return (f"`!!/{self.name} " + " ".join(parameters)).strip() + "`: " + self.helpStr

class CommandSupplier:
    def __init__(self):
        self.commands = self.genCommands()

    def invoke(self, name: str, event: EventInfo, *args):
        return self.commands[name].impl(event, *args)

    def genCommands(self):
        commands: dict[str, Command] = {}
        for attrName in self.__dir__():
            attr = getattr(self, attrName)
            if not (callable(attr) and hasattr(attr, "__name__")):
                continue
            if not attr.__name__.lower().endswith("command"):
                continue
            if attr.__doc__ is None:
                continue
            name = re.sub(r"([A-Z])", lambda match: " " + match.group(0).lower(), attr.__name__.removesuffix("Command"))
            commands[name] = Command(name, attr.__doc__, attr)
        
        return commands