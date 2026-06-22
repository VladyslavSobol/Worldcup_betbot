from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GroupChat


async def bind_group_chat(session: AsyncSession, chat_id: int, title: str | None) -> GroupChat:
    group = await session.scalar(select(GroupChat).where(GroupChat.chat_id == chat_id))
    if group:
        group.title = title
        group.is_primary = True
        return group

    existing_groups = (await session.scalars(select(GroupChat))).all()
    for existing in existing_groups:
        existing.is_primary = False

    group = GroupChat(chat_id=chat_id, title=title, is_primary=True)
    session.add(group)
    await session.flush()
    return group


async def get_primary_group_chat(session: AsyncSession) -> GroupChat | None:
    return await session.scalar(
        select(GroupChat).where(GroupChat.is_primary.is_(True)).order_by(GroupChat.id.desc())
    )
