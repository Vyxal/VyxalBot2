from itertools import chain, repeat

COMMAND_REGEXES_IN: dict[tuple[str, ...], str] = {
    (
        r"status( (?P<boring>boring)| (?P<exciting>exciting))?",
        r"((lol )?(yo)?u good( (there )?(my )?(epic )?(bro|dude|sis|buddy|mate|m8|gamer)?)?\??)",
    ): "status",
    (r"info",): "info",
    (r"help( (?P<command>.+))?",): "help",
    (
        r"coffee (?P<user>.+)",
        r"(make|brew)( a cup of)? coffee for (?P<user>.+)",
        r"(make|brew) (?P<user>me) a coffee",
    ): "coffee",
    (r"maul (?P<user>.+)",): "maul",
    (r"die",): "die",
    (
        r"permissions (?P<action>list) (?P<user>(\d+)|me)",
        r"permissions (?P<action>grant|revoke) (?P<user>(\d+)|me)( (?P<permission>.+))?",
    ): "permissions",
    (r"groups (?P<action>list)", r"groups (?P<action>members) (?P<group>.+)"): "groups",
    (r"register",): "register",
    (r"ping (?P<group>\w+)( (?P<message>.+))?",): "ping",
    (r"(pl(s|z|ease) )?make? meh? (a )?coo?kie?", r"cookie"): "cookie",
    (r"hug",): "hug",
    (r"sus",): "sus",
    (r"repo(sitories|s)?",): "repo-list",
    (r"issue open (in (?P<repo>\w+) )?<b>(?P<title>.+)<\/b> (?P<content>.+)",): "issue-open",
    (r"prod(uction)?( (?P<repo>\w+))?",): "prod",
    (r"run( (?P<flags>-.+))? <code>(?P<code>.+)<\/code>",): "run",
    (r"amilyxal",): "amilyxal",
    (r"blame",): "blame",
    (r"hello",): "hello",
    (r"(good)?bye",): "goodbye",
}
MESSAGE_REGEXES_IN: dict[tuple[str, ...], str] = {
    (r"(wh?at( i[sz]|'s)? vyxal\??)", r"what vyxal i[sz]\??"): "info",
    (r"((please|pls|plz) )?(make|let|have) velociraptors maul (?P<user>.+)",): "maul",
    (r"(.* |^)(su+s(sy)?|amon?g ?us|suspicious)( .*|$)",): "sus",
    (r"(.* |^)([Ww]ho|[Ww]hat) (did|done) (that|this|it).*", r".*whodunit"): "blame",
    (r"good bot",): "good-bot",
    (r"(hello|howdy|mornin['g]|evenin['g])( y'?all)?",): "hello",
    (r"((good)?bye|see ya\!?|'night|goodnight)( y'?all)?",): "goodbye"
}
COMMAND_REGEXES: dict[str, str] = dict(
    chain.from_iterable(zip(k, repeat(v)) for k, v in COMMAND_REGEXES_IN.items())
)
MESSAGE_REGEXES: dict[str, str] = dict(
    chain.from_iterable(zip(k, repeat(v)) for k, v in MESSAGE_REGEXES_IN.items())
)

