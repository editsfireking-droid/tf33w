# Bloxy Plaza Discord Bot

Simple Python `discord.py` bot for invite rewards.

## Features

- Automatic invite detection
- Ignores bots
- Ignores invited accounts younger than 1 month
- Invite log embeds
- Invite reward panel with **My Stats** and **Claims History**
- Invite rewards:
  - 3 = 2,500 Robux
  - 5 = 5,000 Robux
  - 7 = 7,500 Robux
  - 9 = 10,000 Robux
- Boost reward embed:
  - 1 boost = 1,250 Robux
  - 2 boosts = 3,000 Robux
- `!verify` with Bloxlink verification button
- `!claim 3`, `!claim 5`, `!claim 7`, `!claim 9`
- Guide/rewards/boost/panel posting commands
- SQLite database for invite counts and claim history
- All bot command responses are embeds

## IMPORTANT: Discord Developer Portal

In your bot application, enable:

**Privileged Gateway Intents**
- Server Members Intent

The bot also needs these server permissions:
- View Channels
- Send Messages
- Embed Links
- Read Message History
- Manage Server (needed for reading server invites)

## Railway

1. Create a Railway project.
2. Add a Python service from this folder/repository.
3. Add the variables from `.env.example`.
4. Put your bot token in `DISCORD_TOKEN`.
5. Add a Railway Volume mounted at `/data`.
6. Keep `DB_PATH=/data/bloxy_plaza.db`.
7. Deploy.

### Railway start command

The included `Procfile` uses:

`worker: python bot.py`

## First setup

Replace the `0` values in Railway Variables with your actual IDs.

Then run these commands in the server as an administrator:

`!postpanel`

`!postguide`

`!postboost`

`!postrewards`

These commands send the corresponding embeds.

## Claiming

Members use:

`!claim 3`

`!claim 5`

`!claim 7`

`!claim 9`

The bot checks their invite count and verified role.

## Verification

`!verify` sends a button to:

https://bloxlink.gr/verify?server=4072224305994532

Set `VERIFIED_ROLE_ID` to the role Bloxlink gives verified users.

## Important invite-tracking note

Discord invite tracking works by comparing invite-use counts. The bot needs **Manage Server** permission to read invites.

Invite detection can occasionally be unable to identify the exact invite during unusual cases such as several people joining at exactly the same time. The bot logs those cases instead of guessing.

## Database

Do not delete `/data/bloxy_plaza.db` after the bot starts. It contains invite counts and claim history.

A Railway Volume is recommended so the database survives redeploys.
