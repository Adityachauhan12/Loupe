"""Dev-only: create a project and an API key. Prints the raw key once.

Usage:
    .venv/bin/python -m scripts.create_project "my project"
"""
from __future__ import annotations

import asyncio
import sys

from app.auth import generate_key
from app.db import SessionLocal
from app.models import ApiKey, Project


async def main(project_name: str) -> None:
    async with SessionLocal() as session:
        project = Project(name=project_name)
        session.add(project)
        await session.flush()

        raw, key_hash = generate_key()
        api_key = ApiKey(project_id=project.id, key_hash=key_hash, name="dev")
        session.add(api_key)
        await session.commit()

        print(f"project_id: {project.id}")
        print(f"api_key:    {raw}")
        print("Save the api_key now — it is not stored in plaintext.")


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "default"
    asyncio.run(main(name))
