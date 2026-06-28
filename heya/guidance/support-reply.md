---
name: support-reply
description: How to draft a support reply (ticket, forum, email, chat). Structure, tone, and the hard rules, on top of the writing voice. Override it with your own support-reply in your guidance folder.
---

# Support reply

Use this when you draft a reply to a customer, a ticket, a forum post, or a chat.
It sits on top of `read_guidance('writing-voice')` and `read_guidance('banned-words')`.
Read those too. This is a sensible default; replace it with your own if you want.

## Before you write a word

Identify the stage of the conversation. The greeting, tone, and closing follow
from it.

- New ticket: a fresh issue. Greet, acknowledge the problem in one line, then help.
- Follow-up: you are mid-thread. No fresh greeting, pick up where it left off.
- Resolution: the issue is solved. Confirm what fixed it, offer the next step.
- Needs more info: you cannot answer yet. Ask the smallest set of questions that
  unblocks you, and say why each one matters.
- Bad news or a no: be honest and kind. State the limit, then the best path you
  can offer.

## Structure

1. A short, human greeting. Use the person's name if you have it.
2. The answer first. Lead with what they can do, not with background.
3. The why, briefly, only as much as they need.
4. Concrete steps, in order, with the exact setting, path, or command.
5. A closing that points to the next step and invites a reply.

## Tone

- Warm but not performative. You are talking to a person whose time matters.
- Confident without being blunt. You know your stuff; you do not need to prove it.
- Plain. Short sentences. No jargon you have not explained.
- No emoji unless they used one first. No exclamation pile-ups.
- Speak as the team when you are the team. Do not refer to your own company in
  the third person.

## Hard rules

- Never invent a fact, a setting, a version, or a fix. If you are not sure,
  verify it or say you will check.
- Ground a fix: name the exact setting, the doc, or the file and line. A claim
  is not evidence.
- For a code snippet, say where it goes and what it does, and label a workaround
  as unsupported when it is one.
- No banned words or phrases. Re-read `banned-words` before you send.
- Never add any AI attribution.
