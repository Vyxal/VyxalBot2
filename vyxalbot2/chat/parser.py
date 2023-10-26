from typing import Any, Callable
from enum import Enum, auto
from string import digits, ascii_letters

from inspect import signature

from sechat.room import Room
from sechat.events import MessageEvent

class ParseState(Enum):
    TOPLEVEL = auto()
    FLAG = auto()
    STRING = auto()
    NUMBER = auto()
    STRARRAY = auto()

class TokenType(Enum):
    FLAG = auto()
    STRING = auto()
    FLOAT = auto()
    INT = auto()
    STRARRAY = auto()
    ERROR = auto()

TYPES_TO_TOKENS = {
    int: TokenType.INT,
    float: TokenType.FLOAT,
    str: TokenType.STRING,
    list[str]: TokenType.STRARRAY
}

class ParseError(Exception):
    def __init__(self, message: str):
        super().__init__()
        self.message = message

class CommandParser:
    def __init__(self, commands: dict[str, Callable]):
        self.commands = commands

    def parseArgs(self, args: str):
        charStack = list(args)
        stack = []
        state = ParseState.TOPLEVEL
        while True:
            match state:
                case ParseState.TOPLEVEL:
                    try:
                        char = charStack.pop(0)
                    except IndexError:
                        return
                    if char in ascii_letters:
                        state = ParseState.FLAG
                        stack.append(char)
                    elif char in digits:
                        state = ParseState.NUMBER
                        stack.append(char)
                    elif char == '"':
                        state = ParseState.STRING
                    elif char == "[":
                        state = ParseState.STRARRAY
                        stack.append([])
                    elif char == " ":
                        pass
                    else:
                        yield TokenType.ERROR, f"Unexpected toplevel character {char}"
                        return
                case ParseState.FLAG:
                    try:
                        char = charStack.pop(0)
                    except IndexError:
                        char = " "
                    if char == " ":
                        yield TokenType.FLAG, "".join(stack)
                        stack.clear()
                        state = ParseState.TOPLEVEL
                    else:
                        stack.append(char)
                case ParseState.STRING:
                    try:
                        char = charStack.pop(0)
                    except IndexError:
                        yield TokenType.ERROR, "Unclosed string"
                        return
                    if char == "\\":
                        try:
                            stack.append(charStack.pop(0))
                        except IndexError:
                            yield TokenType.ERROR, "Expected character to escape"
                            return
                    elif char == '"':
                        yield TokenType.STRING, "".join(stack)
                        stack.clear()
                        state = ParseState.TOPLEVEL
                    else:
                        stack.append(char)
                case ParseState.NUMBER:
                    try:
                        char = charStack.pop(0)
                    except IndexError:
                        char = None
                    else:
                        if char in digits:
                            stack.append(char)
                        elif char == ".":
                            stack.append(char)
                            try:
                                stack.append(charStack.pop(0))
                            except IndexError:
                                yield TokenType.ERROR, "Expected digit after period"
                                return
                        elif char == " ":
                            char = None
                        else:
                            yield TokenType.ERROR, "Expected digit or period"
                            return
                    if char == None:
                        if "." in stack:
                            yield TokenType.FLOAT, float("".join(stack))
                        else:
                            yield TokenType.INT, int("".join(stack))
                        stack.clear()
                        state = ParseState.TOPLEVEL
                case ParseState.STRARRAY:
                    while True:
                        try:
                            char = charStack.pop(0)
                        except IndexError:
                            yield TokenType.ERROR, "Unclosed strarray"
                            return
                        if char == "\\":
                            try:
                                stack[-1].append(charStack.pop(0))
                            except IndexError:
                                yield TokenType.ERROR, "Expected character to escape"
                                return
                        elif char == ",":
                            stack.append([])
                            break
                        elif char == "]":
                            yield TokenType.STRARRAY, ["".join(i) for i in stack if len(i)]
                            stack.clear()
                            state = ParseState.TOPLEVEL
                            break
                        else:
                            stack[-1].append(char)

    def parseCommand(self, command: str):
        args = list(self.parseArgs(command))
        try:
            ty, commandName = args.pop(0)
        except IndexError:
            raise ParseError("Expected command name") from None
        if ty != TokenType.FLAG:
            raise ParseError(f"Expected command name, got {ty.name}")
        assert isinstance(commandName, str)
        while len(args) and args[0][0] == TokenType.FLAG:
            assert isinstance((i := args.pop(0)[1]), str)
            commandName += " " + i
        try:
            impl = self.commands[commandName]
        except KeyError:
            maybeYouMeant = []
            for command in self.commands.keys():
                if command.startswith(commandName.split(" ")[0]):
                    maybeYouMeant.append(command)
            if len(maybeYouMeant):
                raise ParseError(f"Unknown command. Perhaps you forgot some quotes? Valid subcommands of {commandName.split(' ')[0]} are: " + ", ".join(maybeYouMeant))
            raise ParseError("Unknown command.") from None
        argValues = []
        for paramName, param in signature(impl).parameters.items():
            if paramName in ("event", "self"):
                continue
            paramType = TYPES_TO_TOKENS[param.annotation]
            try:
                argType, argValue = args.pop(0)
            except IndexError:
                if param.default is param.empty:
                    raise ParseError(f"Expected a value for {paramName}")
                else:
                    argValues.append(param.default)
            else:
                if argType == TokenType.ERROR:
                    raise ParseError(str(argValue))
                if argType == TokenType.FLAG:
                    argType = TokenType.STRING
                if argType != paramType:
                    raise ParseError(f"Expected {paramType.name} for {paramName} but got {argType.name}")
                argValues.append(argValue)
        return commandName, impl, argValues
        
