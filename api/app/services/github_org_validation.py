from github import Github
from typing import Tuple


async def validate_user_in_github_org(github_token: str, org_name: str, github_username: str) -> Tuple[bool, str]:
    """
    Validate if a GitHub user belongs to a specific GitHub organization.

    Returns:
        Tuple[bool, str]: (is_member, message)
    """
    try:
        gh = Github(github_token)
        me = gh.get_user()

        if me.login.lower() == github_username.lower():
            user = me
        else:
            user = gh.get_user(github_username)

        user_orgs = user.get_orgs()
        in_org = any(o.login.lower() == org_name.lower() for o in user_orgs)

        if in_org:
            return True, f"Usuario '{github_username}' es miembro de '{org_name}'"

        return False, f"Usuario '{github_username}' no es miembro de la organización '{org_name}'"

    except Exception as e:
        return False, f"Error validando con GitHub: {str(e)}"
