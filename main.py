import discord
from discord.ext import commands
import random
import time
import os
import json
import asyncio
from copy import deepcopy

# ------------------------
# CONFIG
# ------------------------
INTENTS = discord.Intents.default()
INTENTS.message_content = True

PREFIX = "-"
DATA_FILE = "data.json"

# ------------------------
# TEST CHARACTERS (base)
# ------------------------
CHARACTERS = [
    {"id": "naruto", "name": "Naruto", "rarity": "Common", "hp": 100, "atk": 20, "def": 10, "spd": 15, "ability": "Shadow Clone"},
    {"id": "sasuke", "name": "Sasuke", "rarity": "Rare", "hp": 120, "atk": 30, "def": 15, "spd": 20, "ability": "Chidori"},
    {"id": "goku",   "name": "Goku",   "rarity": "Epic",   "hp": 200, "atk": 45, "def": 20, "spd": 25, "ability": "Kamehameha"},
    {"id": "luffy",  "name": "Luffy",  "rarity": "Legendary", "hp": 250, "atk": 55, "def": 25, "spd": 30, "ability": "Gear Fifth"},
]

# ------------------------
# DATA (persisted in data.json)
# Structure:
# {
#   "users": {
#       "<user_id>": {
#           "stamina": int,
#           "gold": int,
#           "inventory": [ {card instance}, ... ],
#           "last_hourly": float
#       },
#       ...
#   }
# }
# ------------------------
data_lock = asyncio.Lock()
data = {"users": {}}


def _load_data_from_disk():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        # if file corrupted or unreadable, start fresh
        return {"users": {}}
    return {"users": {}}


async def load_data():
    global data
    # run file IO in thread to avoid blocking event loop
    loaded = await asyncio.to_thread(_load_data_from_disk)
    data = loaded if loaded is not None else {"users": {}}


def _save_data_to_disk(d):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


async def save_data():
    async with data_lock:
        await asyncio.to_thread(_save_data_to_disk, data)


def ensure_user(user_id: int):
    uid = str(user_id)
    if uid not in data["users"]:
        data["users"][uid] = {
            "stamina": 20,
            "gold": 0,
            "inventory": [],
            "last_hourly": 0.0
        }
    return data["users"][uid]


# ------------------------
# BOT
# ------------------------
bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS)


@bot.event
async def on_ready():
    await load_data()
    print(f"Logged in as {bot.user} (id: {bot.user.id})")
    # optional: print where data is stored
    print(f"Data file: {os.path.abspath(DATA_FILE)}")


# ------------------------
# COMMANDS
# ------------------------
@bot.command(name="profile")
async def profile(ctx):
    user = ensure_user(ctx.author.id)
    await ctx.send(
        f"👤 **Profile — {ctx.author.name}**\n"
        f"⚡ Stamina: {user['stamina']}\n"
        f"💰 Gold: {user['gold']}\n"
        f"🎴 Cards owned: {len(user['inventory'])}"
    )


@bot.command(name="stamina")
async def stamina_cmd(ctx):
    user = ensure_user(ctx.author.id)
    await ctx.send(f"⚡ Current stamina: **{user['stamina']}**")


@bot.command(name="gold")
async def gold_cmd(ctx):
    user = ensure_user(ctx.author.id)
    await ctx.send(f"💰 Gold: **{user['gold']}**")


@bot.command(name="inventory")
async def inventory_cmd(ctx):
    user = ensure_user(ctx.author.id)
    inv = user["inventory"]
    if not inv:
        await ctx.send("🎴 Your inventory is empty.")
        return
    text = "🎴 **Your cards:**\n"
    # show up to 25 entries to avoid very long messages
    for c in inv[:25]:
        name = c.get("name", "Unknown")
        rarity = c.get("rarity", "")
        iid = c.get("instance_id", "")
        text += f"- {name} ({rarity}) — id: `{iid}`\n"
    if len(inv) > 25:
        text += f"... e altri {len(inv)-25} carte\n"
    await ctx.send(text)


@bot.command(name="hourly")
async def hourly_cmd(ctx):
    user = ensure_user(ctx.author.id)
    now = time.time()
    elapsed = now - user.get("last_hourly", 0.0)
    cooldown = 3600  # 1 hour
    if elapsed < cooldown:
        remaining = int((cooldown - elapsed) / 60)
        remaining_secs = int(cooldown - elapsed)
        minutes = remaining
        seconds = remaining_secs - minutes * 60
        await ctx.send(f"⏳ Hourly non pronto. Riprova tra {minutes} minuti e {seconds} secondi.")
        return
    # grant rewards
    user["last_hourly"] = now
    user["stamina"] = user.get("stamina", 0) + 10
    user["gold"] = user.get("gold", 0) + 50
    await save_data()
    await ctx.send("🎁 Hourly claimed! +10 stamina, +50 gold.")


@bot.command(name="drop")
@commands.cooldown(1, 10, commands.BucketType.user)  # anti-spam: 1 use per 10s per user
async def drop_cmd(ctx):
    user = ensure_user(ctx.author.id)
    if user.get("stamina", 0) < 5:
        await ctx.send("❌ Not enough stamina (5 required).")
        return
    user["stamina"] -= 5
    card = deepcopy(random.choice(CHARACTERS))
    # unique instance id (timestamp + random)
    inst_id = f"{card['id']}_{int(time.time()*1000)}_{random.randint(1000,9999)}"
    card_instance = {"instance_id": inst_id, **card}
    user["inventory"].append(card_instance)
    await save_data()
    await ctx.send(
        f"🎉 **New card obtained!**\n"
        f"🧙 {card['name']} ({card['rarity']})\n"
        f"❤️ HP: {card['hp']} | ⚔ ATK: {card['atk']} | 🛡 DEF: {card['def']} | 💨 SPD: {card['spd']}\n"
        f"✨ Ability: {card['ability']}"
    )


# simple error handler for command cooldowns
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Comando in cooldown. Riprova tra {int(error.retry_after)} secondi.")
    else:
        # print other errors to console for debugging
        print(f"Unhandled command error: {error}")


# ------------------------
# RUN
# ------------------------
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("ERROR: set the DISCORD_TOKEN environment variable.")
    else:
        bot.run(token)