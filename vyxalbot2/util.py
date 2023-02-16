TAG_MAP = {
    "bug": "PR: Bug Fix",
    "documentation": "PR: Documentation Fix",
    "request: element": "PR: Element Implementation",
    "enhancement": "PR: Enhancement",
    "difficulty: very hard": "PR: Careful Review Required",
    "priority: high": "PR: Urgent Review Required",
    "online interpreter": "PR: Online Interpreter",
    "version-3": "PR: Version 3 Related",
    "difficulty: easy": "PR: Light and Easy",
    "good first issue": "PR: Light and Easy",
}

def formatUser(user: dict) -> str:
    return f'[{user["login"]}]({user["html_url"]})'


def formatRepo(repo: dict) -> str:
    return f'[{repo["full_name"]}]({repo["html_url"]})'


def formatIssue(issue: dict) -> str:
    return f'[#{issue["number"]}]({issue["html_url"]}) ({issue["title"]})'


def msgify(text):
    return (
        text.split("\n")[0]
        .split("\r")[0]
        .split("\f")[0]
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("`", "\\`")
    )


RAPTOR = r"""
                                                                   YOU CAN RUN, BUT YOU CAN'T HIDE, {user}
                                                         ___._
                                                       .'  <0>'-.._
                                                      /  /.--.____")
                                                     |   \   __.-'~
                                                     |  :  -'/
                                                    /:.  :.-'
    __________                                     | : '. |
    '--.____  '--------.______       _.----.-----./      :/
            '--.__            `'----/       '-.      __ :/
                  '-.___           :           \   .'  )/
                        '---._           _.-'   ] /  _/
                             '-._      _/     _/ / _/
                                 \_ .-'____.-'__< |  \___
                                   <_______.\    \_\_---.7
                                  |   /'=r_.-'     _\\ =/
                              .--'   /            ._/'>
                            .'   _.-'
       snd                 / .--'
                          /,/
                          |/`)
                          'c=,
"""
