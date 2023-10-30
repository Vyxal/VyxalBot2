def msgify(text):
    return (
        text.split("\n")[0]
        .split("\r")[0]
        .split("\f")[0]
        .replace("_", r"\_")
        .replace("*", r"\*")
        .replace("`", r"\`")
    )

def linkify(text):
    return msgify(str(text)).replace("[", "\\[").replace("]", "\\]")

def formatUser(user: dict) -> str:
    return f'[{linkify(user["login"])}]({user["html_url"]})'


def formatRepo(repo: dict, fullName: bool = True) -> str:
    return f'[{linkify(repo["full_name"] if fullName else repo["name"])}]({repo["html_url"]})'


def formatIssue(issue: dict) -> str:
    return f'[#{linkify(issue["number"])}]({issue["html_url"]}) ({issue["title"]})'


def formatRef(ref: str, repo: dict) -> str:
    return f'[{repo["name"]}/{ref}]({repo["html_url"]}/tree/{ref})'