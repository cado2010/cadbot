# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Remembering and forgetting people.

Claude decides whom to ask and when; code enforces the rules: nothing is saved without a
recorded yes (consent gate), and erasing needs a separate spoken confirmation from the person
themselves while they are recognised (confirmation gate).
"""

from __future__ import annotations

import secrets
import time
from typing import Any

from cadbot.agent.tools.registry import HelpInfo, Tool, ToolContext, ToolResult
from cadbot.people.store import ConsentRequired

CONFIRM_WINDOW_S = 120
ADMIN_HINT = ("The owner can erase anyone with `python -m cadbot.admin forget --name <name>` "
              "on the device (the web UI comes later).")


def _no_people(ctx: ToolContext) -> ToolResult | None:
    if ctx.people is None or ctx.vision is None:
        return ToolResult("Face recognition isn't available right now.", is_error=True)
    return None


def _track(ctx: ToolContext, number: Any) -> Any:
    assert ctx.vision is not None
    return ctx.vision.tracker.get(int(number)) if number is not None else None


async def remember_person(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    if (error := _no_people(ctx)) is not None:
        return error
    assert ctx.people is not None and ctx.vision is not None
    track = _track(ctx, args["track"])
    if track is None:
        return ToolResult(f"track {args['track']} isn't in view any more; ask again when you "
                          "can see their face.", is_error=True)
    name = (args.get("name") or "").strip() or None
    declined = bool(args.get("declined")) and name is None
    person = ctx.people.remember_pending(
        track, name=name, description=args.get("description", ""), declined=declined,
        lighting=ctx.vision.lighting(), thumbnail_jpeg=ctx.vision.thumbnail(track))
    if declined:
        return ToolResult(f"Held as {person.person_id} for this visit only (no name, nothing "
                          "saved). Don't ask their name again this visit.")
    return ToolResult(
        f"{name} is {person.person_id}, held in memory only. Nothing is saved yet: ask once "
        "whether they'd like you to remember them, then call confirm_remember with their "
        "answer.")


async def confirm_remember(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    if (error := _no_people(ctx)) is not None:
        return error
    assert ctx.people is not None
    person_id, accepted = args["person_id"], bool(args["accepted"])
    if ctx.people.get(person_id) is None:
        return ToolResult(f"No person {person_id}.", is_error=True)
    try:
        person = ctx.people.confirm(person_id, accepted, permanent=bool(args.get("permanent")),
                                    consent_reference=ctx.conversation.last_utterance)
    except (ValueError, ConsentRequired) as exc:
        return ToolResult(str(exc), is_error=True)
    if person.status == "saved":
        return ToolResult(f"Saved {person.name} ({person_id}) with {len(person.views)} face "
                          "view(s). Kept until they say 'forget me'.")
    return ToolResult("Not saved. Use their name for this visit only; it's forgotten when they "
                      "leave. Don't ask again this visit.")


async def update_person(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    if (error := _no_people(ctx)) is not None:
        return error
    assert ctx.people is not None and ctx.vision is not None
    person_id = args["person_id"]
    if ctx.people.get(person_id) is None:
        return ToolResult(f"No person {person_id}.", is_error=True)
    track = None
    if args.get("track") is not None:
        track = _track(ctx, args["track"])
        if track is None:
            return ToolResult(f"track {args['track']} isn't in view.", is_error=True)
    person = ctx.people.update(person_id, name=args.get("name"),
                               description=args.get("description"), track=track,
                               lighting=ctx.vision.lighting())
    saved = "saved" if person.status == "saved" else "held for this visit only (not saved)"
    return ToolResult(f"Updated {person.name or person_id}: {saved}.")


async def find_person(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    if (error := _no_people(ctx)) is not None:
        return error
    assert ctx.people is not None and ctx.vision is not None
    matches = ctx.people.find(args["name"])
    if not matches:
        return ToolResult(f"I don't know anyone called {args['name']!r}.")
    in_view = {t.identity.person_id for t in ctx.vision.tracker.visible()
               if t.identity is not None}
    lines = []
    for p in matches:
        seen = "in view now" if p.person_id in in_view else "not in view"
        lines.append(f"{p.person_id}: {p.name}, {p.status}, {p.description or 'no notes'}, "
                     f"{seen}")
    return ToolResult("\n".join(lines))


def _present_and_confident(ctx: ToolContext, person_id: str) -> bool:
    assert ctx.vision is not None
    return any(t.identity is not None and t.identity.person_id == person_id
               and t.identity.level == "confident" for t in ctx.vision.tracker.visible())


async def forget_person(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    if (error := _no_people(ctx)) is not None:
        return error
    assert ctx.people is not None
    person_id = args["person_id"]
    person = ctx.people.get(person_id)
    if person is None:
        return ToolResult(f"No person {person_id}.", is_error=True)
    token = args.get("confirm_token")
    if not token:
        if not _present_and_confident(ctx, person_id):
            return ToolResult(
                "Not allowed: only the person themselves can ask to be forgotten, while I can "
                "see and recognise them. " + ADMIN_HINT, is_error=True)
        token = "fg_" + secrets.token_hex(3)
        ctx.conversation.confirmations[token] = (person_id, ctx.conversation.utterance_seq,
                                                 time.monotonic())
        return ToolResult(
            f"Needs confirmation. This deletes {person.name or 'their'} face data "
            f"({len(person.views)} view(s)), name and notes, and can't be undone. Read that "
            f"aloud and ask them to say 'yes, forget me'. If they do, call forget_person again "
            f"with confirm_token={token}.")
    pending = ctx.conversation.confirmations.get(token)
    if pending is None or pending[0] != person_id:
        return ToolResult("That confirmation token isn't valid; start again.", is_error=True)
    _pid, issued_seq, issued_at = pending
    if ctx.conversation.utterance_seq <= issued_seq:
        return ToolResult("Not yet: they must confirm in a new, separate spoken answer.",
                          is_error=True)
    if time.monotonic() - issued_at > CONFIRM_WINDOW_S:
        del ctx.conversation.confirmations[token]
        return ToolResult("The confirmation expired; ask again.", is_error=True)
    del ctx.conversation.confirmations[token]
    report = ctx.people.forget(person_id)
    name = report.name or "them"
    return ToolResult(f"Done: erased {name} ({report.views} face view(s)). Tell them "
                      f"\"Done. I've forgotten you.\"")


REMEMBER_PERSON = Tool(
    name="remember_person",
    description=(
        "Hold the person on a face track in memory with the name they gave (nothing is saved "
        "to disk). Then ask once whether they'd like to be remembered and call "
        "confirm_remember. If they'd rather not give a name, call it with declined=true and "
        "no name, so you recognise them this visit without asking again."),
    input_schema={"type": "object", "properties": {
        "track": {"type": "integer", "description": "The face track number from the readings."},
        "name": {"type": "string"},
        "description": {"type": "string",
                        "description": "A short appearance note, e.g. 'red jacket, glasses'."},
        "declined": {"type": "boolean"}},
        "required": ["track"], "additionalProperties": False},
    handler=remember_person,
    help=HelpInfo("People and memory", "Learn your name and recognise you next time",
                  ("My name is Sam", "Remember me")),
)

CONFIRM_REMEMBER = Tool(
    name="confirm_remember",
    description=(
        "Record the person's answer to 'may I remember you?'. accepted=true only for a clear "
        "yes; then their face, name and notes are saved until they say 'forget me'. A no, no "
        "clear answer, or walking away means accepted=false."),
    input_schema={"type": "object", "properties": {
        "person_id": {"type": "string"}, "accepted": {"type": "boolean"},
        "permanent": {"type": "boolean", "description": "They asked to be remembered for good."}},
        "required": ["person_id", "accepted"], "additionalProperties": False},
    handler=confirm_remember,
    help=HelpInfo("People and memory", "Only remembers people who say yes",
                  ("Yes, remember me",), user_facing=False),
)

UPDATE_PERSON = Tool(
    name="update_person",
    description=(
        "Change a known person's name or appearance note, or link a face track to them once "
        "they confirm who they are ('Are you Priya?' 'Yes'), which also saves that view of "
        "their face if they agreed to be remembered."),
    input_schema={"type": "object", "properties": {
        "person_id": {"type": "string"}, "name": {"type": "string"},
        "description": {"type": "string"}, "track": {"type": "integer"}},
        "required": ["person_id"], "additionalProperties": False},
    handler=update_person,
    help=HelpInfo("People and memory", "Correct the name I know you by",
                  ("Actually, call me Sam",)),
)

FIND_PERSON = Tool(
    name="find_person",
    description="Look up people cadbot knows by name: their ids, status and whether they're "
                "in view.",
    input_schema={"type": "object", "properties": {"name": {"type": "string"}},
                  "required": ["name"], "additionalProperties": False},
    handler=find_person,
    help=HelpInfo("People and memory", "Tell you whom I know", ("Do you know Priya?",),
                  user_facing=False),
)

FORGET_PERSON = Tool(
    name="forget_person",
    description=(
        "Erase everything about a person (face data, name, notes). Only for the person "
        "themselves ('forget me') while they're confidently recognised. The first call "
        "returns a summary and a confirm_token; read the summary aloud, and only after a "
        "separate spoken 'yes' call again with the token. Requests to forget someone else are "
        "refused; point them to the owner."),
    input_schema={"type": "object", "properties": {
        "person_id": {"type": "string"}, "confirm_token": {"type": "string"}},
        "required": ["person_id"], "additionalProperties": False},
    handler=forget_person,
    side_effects=True,
    help=HelpInfo("Privacy", "Forget everything about you", ("Forget me",)),
)

ALL = [REMEMBER_PERSON, CONFIRM_REMEMBER, UPDATE_PERSON, FIND_PERSON, FORGET_PERSON]
