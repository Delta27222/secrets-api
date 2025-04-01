from typing import List, Optional

from bson import ObjectId
from github import Github
from motor.motor_asyncio import AsyncIOMotorClient

from ..core.config import database_name, users_collection_name
from ..models.user import UserCreate, UserInDB

collection_name = users_collection_name


async def get_user_by_username(conn: AsyncIOMotorClient, username: str) -> Optional[UserInDB]:
    user = await conn[database_name][collection_name].find_one({"username": username})
    if user:
        return UserInDB(**user)
    return None


async def get_user_by_email(conn: AsyncIOMotorClient, email: str) -> Optional[UserInDB]:
    user = await conn[database_name][collection_name].find_one({"email": email})
    if user:
        return UserInDB(**user)
    return None


async def get_user_by_id(conn: AsyncIOMotorClient, id: str) -> Optional[UserInDB]:
    user = await conn[database_name][collection_name].find_one({"_id": ObjectId(id)})
    if user:
        return UserInDB(**user)
    return None


async def get_or_create_user(conn: AsyncIOMotorClient, github_token: str) -> UserInDB:
    # Create Github instance

    github = Github(github_token)

    # Get user info from github
    try:
        github_user = github.get_user()
        primary_email = None
        for email in github_user.get_emails():
            if email.primary:
                primary_email = email.email
                break

    except Exception as e:
        raise ValueError(f"Error al obtener datos del usuario de GitHub: {e}")

    # Seek user in db
    user = await conn[database_name][collection_name].find_one({"username": github_user.login})

    if user:
        # User already exists, return it
        return UserInDB(**user)
    else:
        # Create user in db
        new_user = UserCreate(
            email=primary_email,
            username=github_user.login,
            displayName=github_user.name if github_user.name else github_user.login
        )
        data = new_user.model_dump(by_alias=True)

        result = await conn[database_name][collection_name].insert_one(data)
        inserted_user = await conn[database_name][collection_name].find_one({"_id": result.inserted_id})

        # Return user created
        return UserInDB(**inserted_user)
