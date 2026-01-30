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
# CHARACTERS (base)
# Each character has the same base stats across rarities; rarities only affect max_level
CHARACTERS = [
    {
        "id": "hilde",
        "name": "Hilde",
        "base": {"hp": 89, "atk": 65, "def": 92, "spd": 65},
        "ability": "First turn: +100% DEF",
        "image": "https://media.discordapp.net/attachments/815650716730654743/1466808264175124492/IMG_6210.jpg?ex=697e1726&is=697cc5a6&hm=11cce5cd58f5a8db5dc4e8a8d4afa8154f6fb39d00ccc7aee76a0907c338e901&=&format=webp&width=692&height=968"
    },
    {
        "id": "joo_shiyoon",
        "name": "Joo Shiyoon",
        "base": {"hp": 60, "atk": 95, "def": 86, "spd": 89},
        "ability": "First turn: +100% SPD",
        "image": "https://media.discordapp.net/attachments/815650716730654743/1466811090754343074/IMG_6211.jpg?ex=697e19c8&is=697cc848&hm=4a8459bf4b0279d805bd0708e96489a4a9225bc5063029b0b4e6e5ffa08b4df6&=&format=webp"
    },
    {
        "id": "yoo_mina",
        "name": "Yoo Mina",
        "base": {"hp": 75, "atk": 75, "def": 75, "spd": 85},
        "ability": "First turn: +50% ATK",
        "image": "https://media.discordapp.net/attachments/815650716730654743/1466811096576037029/IMG_6213.webp?ex=697e19c9&is=697cc849&hm=ddbe9afe21e256f3aeaaabc6990e8f5745f1feaaaf62faf45d925875a02f5339&=&format=webp"
    },
]

RARITY_MAX_LEVEL = {
    "Common": 30,
    "Rare": 40,
    "Epic": 50,
    "Legendary": 60,
}
RARITIES = ["Common", "Rare", "Epic", "Legendary"]
RARITY_WEIGHTS = [60, 25, 10, 5]  # percent-ish weights for random drops

# ------------------------
# DATA (persisted in data.json)
# ------------------------
data_lock = asyncio.Lock()
data = {"users": {}}

def _load_data_from_disk():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        return {"users": {}}
    return {"users": {}}

async def load_data():
    global data
    loaded = await asyncio.to_thread(_load_data_from_disk)
    data = loaded if loaded is not None else {"users": {}}

def _save_data_to_disk(d):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

async def save_data():
    async with data_lock:
        await asyncio.to_thread(_save_data_to_disk, data)

# ------------------------
# HELPERS
# ------------------------
def ensure_user(user_id: int):
    uid = str(user_id)
    if uid not in data["users"]:
        data["users"][uid] = {
            "stamina": 20,
            "gold": 0,
            "inventory": [],
            "last_hourly": 0.0,
            "level": 1,
            "exp": 0,
            "floor": 1,
            # user max stamina scales with level: base 20 + (level-1)*5 (applied via level ups)
        }
    return data["users"][uid]

def exp_to_next(level: int) -> int:
    return 100 * level

def maybe_level_up_user(user: dict) -> list:
    """Checks and performs user level ups. Returns list of level-up messages."""
    messages = []
    while user.get("exp", 0) >= exp_to_next(user.get("level", 1)):
        need = exp_to_next(user.get("level", 1))
        user["exp"] -= need
        user["level"] = user.get("level", 1) + 1
        # increase max stamina effectively by granting stamina
        bonus = 5
        user["stamina"] = user.get("stamina", 0) + bonus
        messages.append(f"Level up! Now level {user['level']} (+{bonus} max stamina).")
    return messages

def create_card_instance(card_base: dict, rarity: str):
    inst_id = f"{card_base['id']}_{int(time.time()*1000)}_{random.randint(1000,9999)}"
    return {
        "instance_id": inst_id,
        "id": card_base["id"],
        "name": card_base["name"],
        "rarity": rarity,
        "level": 1,
        "exp": 0,
        "max_level": RARITY_MAX_LEVEL[rarity],
        "base": card_base["base"],
        "ability": card_base["ability"],
        "image": card_base.get("image", ""),
    }

def find_card_by_name(name: str):
    for c in CHARACTERS:
        if c["name"].lower() == name.lower() or c["id"] == name.lower().replace(" ", "_"):
            return c
    return None

def card_power(card_inst: dict) -> float:
    # scale base stats by level (e.g., +3% per level)
    lvl = card_inst.get("level", 1)
    mult = 1 + 0.03 * (lvl - 1)
    b = card_inst["base"]
    return (b["hp"] * 0.2 + b["atk"] + b["def"] + b["spd"]) * mult

# ------------------------
# BOT
# ------------------------
bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS, help_command=None)

@bot.event
async def on_ready():
    await load_data()
    print(f"Logged in as {bot.user} (id: {bot.user.id})")
    print(f"Data file: {os.path.abspath(DATA_FILE)}")

# ------------------------
# COMMANDS
# ------------------------
@bot.command(name="help")
async def help_cmd(ctx):
    # dynamically list commands
    lines = [f"Comandi disponibili (prefisso `{PREFIX}`):"]
    for c in bot.commands:
        if c.hidden:
            continue
        names = ", ".join([c.name] + (c.aliases or []))
        doc = c.help or ""
        lines.append(f"- `{PREFIX}{names}` — {doc}")
    await ctx.send("\n".join(lines))

@bot.command(name="profile", aliases=["p"]) 
async def profile(ctx):
    """Mostra il profilo dell'utente: stamina, gold, level e carte."""
    user = ensure_user(ctx.author.id)
    await ctx.send(
        f"👤 **Profile — {ctx.author.name}**\n"
        f"⚡ Stamina: {user['stamina']}\n"
        f"💰 Gold: {user['gold']}\n"
        f"🎴 Cards owned: {len(user['inventory'])}\n"
        f"⭐ Level: {user.get('level',1)} | EXP: {user.get('exp',0)}/{exp_to_next(user.get('level',1))}\n"
        f"🗼 Floor: {user.get('floor',1)}"
    )

@bot.command(name="stamina")
async def stamina_cmd(ctx):
    """Mostra lo stamina corrente dell'utente."""
    user = ensure_user(ctx.author.id)
    await ctx.send(f"⚡ Current stamina: **{user['stamina']}**")

@bot.command(name="gold", aliases=["g"]) 
async def gold_cmd(ctx):
    """Mostra i gold correnti dell'utente."""
    user = ensure_user(ctx.author.id)
    await ctx.send(f"💰 Gold: **{user['gold']}**")

@bot.command(name="inventory", aliases=["inv"]) 
async def inventory_cmd(ctx):
    """Elenca le carte dell'utente."""
    user = ensure_user(ctx.author.id)
    inv = user["inventory"]
    if not inv:
        await ctx.send("🎴 Your inventory is empty.")
        return
    text = "🎴 **Your cards:**\n"
    for i, c in enumerate(inv[:25], start=1):
        name = c.get("name", "Unknown")
        rarity = c.get("rarity", "")
        iid = c.get("instance_id", "")
        lvl = c.get("level", 1)
        text += f"{i}. {name} ({rarity}) Lv{lvl} — id: `{iid}`\n"
    if len(inv) > 25:
        text += f"... e altri {len(inv)-25} carte\n"
    await ctx.send(text)

@bot.command(name="hourly")
async def hourly_cmd(ctx):
    """Claim a random stamina reward every hour (5,10,15)."""
    user = ensure_user(ctx.author.id)
    now = time.time()
    elapsed = now - user.get("last_hourly", 0.0)
    cooldown = 3600
    if elapsed < cooldown:
        remaining = int((cooldown - elapsed) / 60)
        remaining_secs = int(cooldown - elapsed)
        minutes = remaining
        seconds = remaining_secs - minutes * 60
        await ctx.send(f"⏳ Hourly non pronto. Riprova tra {minutes} minuti e {seconds} secondi.")
        return
    amount = random.choice([5, 10, 15])
    user["last_hourly"] = now
    user["stamina"] = user.get("stamina", 0) + amount
    await save_data()
    await ctx.send(f"🎁 Hourly claimed! +{amount} stamina.")

@bot.command(name="farm")
@commands.cooldown(1, 900, commands.BucketType.user)
async def farm_cmd(ctx):
    """Farm per ottenere gold (cooldown 15 minuti)."""
    user = ensure_user(ctx.author.id)
    amount = random.randint(100, 1000)
    user["gold"] = user.get("gold", 0) + amount
    await save_data()
    await ctx.send(f"⛏️ Hai guadagnato **{amount}** gold!")

@bot.command(name="drop")
@commands.cooldown(1, 900, commands.BucketType.user)
async def drop_cmd(ctx):
    """Ottieni una carta casuale (cooldown 15 minuti), non consuma stamina."""
    user = ensure_user(ctx.author.id)
    base = deepcopy(random.choice(CHARACTERS))
    rarity = random.choices(RARITIES, weights=RARITY_WEIGHTS, k=1)[0]
    card_instance = create_card_instance(base, rarity)
    user["inventory"].append(card_instance)
    await save_data()
    await ctx.send(
        f"🎉 **New card obtained!**\n"
        f"🧙 {card_instance['name']} ({card_instance['rarity']}) Lv{card_instance['level']}\n"
        f"ID: `{card_instance['instance_id']}`\n"
        f"✨ Ability: {card_instance['ability']}"
    )

@bot.command(name="cinfo")
async def cinfo_cmd(ctx, *, name: str):
    """Mostra le informazioni base di una carta (stats base). Uso: -cinfo <nome carta>"""
    base = find_card_by_name(name)
    if not base:
        await ctx.send("Carta non trovata.")
        return
    stats = base["base"]
    lines = [f"📜 **{base['name']}** - stats base (Common Lv1):"]
    lines.append(f"HP: {stats['hp']} | ATK: {stats['atk']} | DEF: {stats['def']} | SPD: {stats['spd']}")
    lines.append(f"Ability: {base['ability']}")
    lines.append("Max level per rarità:")
    for r, ml in RARITY_MAX_LEVEL.items():
        lines.append(f"- {r}: {ml}")
    await ctx.send("\n".join(lines))

@bot.command(name="enhance")
async def enhance_cmd(ctx, target: str, *args):
    """Enhance a card using other cards. Uso: -enhance <id_or_index> [-r Rarity] [-n Name] [-l Num]"""
    user = ensure_user(ctx.author.id)
    inv = user["inventory"]
    # find target by instance_id or numeric index
    target_card = None
    if target.isdigit():
        idx = int(target) - 1
        if 0 <= idx < len(inv):
            target_card = inv[idx]
    else:
        for c in inv:
            if c["instance_id"] == target:
                target_card = c
                break
    if not target_card:
        await ctx.send("Target card non trovata in inventario.")
        return
    # parse flags
    flag_r = None
    flag_n = None
    flag_l = 1
    it = iter(args)
    for a in it:
        if a == "-r":
            try:
                flag_r = next(it)
            except StopIteration:
                pass
        elif a == "-n":
            try:
                flag_n = next(it)
            except StopIteration:
                pass
        elif a == "-l":
            try:
                flag_l = int(next(it))
            except StopIteration:
                pass
    # gather sacrifice candidates
    candidates = []
    for c in inv:
        if c is target_card:
            continue
        if flag_r and c.get("rarity", "") != flag_r:
            continue
        if flag_n and c.get("name", "").lower() != flag_n.lower():
            continue
        candidates.append(c)
    if len(candidates) < flag_l:
        await ctx.send(f"Non ci sono abbastanza carte da usare (trovate {len(candidates)}, richieste {flag_l}).")
        return
    to_use = candidates[:flag_l]
    # compute exp gain: base 50 per card * rarity multiplier
    rarity_mul = {"Common": 1, "Rare": 1.5, "Epic": 2, "Legendary": 3}
    gained = 0
    for c in to_use:
        gained += 50 * rarity_mul.get(c.get("rarity","Common"),1)
        inv.remove(c)
    target_card["exp"] = target_card.get("exp",0) + int(gained)
    # level up card as needed
    leveled = []
    while target_card.get("level",1) < target_card.get("max_level",30):
        need = 100 * target_card.get("level",1)
        if target_card.get("exp",0) >= need:
            target_card["exp"] -= need
            target_card["level"] += 1
            leveled.append(target_card["level"])
        else:
            break
    await save_data()
    msg = f"Enhance completato: +{int(gained)} exp alla carta."
    if leveled:
        msg += f" Livelli saliti fino a {target_card['level']}."
    await ctx.send(msg)

@bot.command(name="level")
async def level_cmd(ctx, member: discord.Member = None):
    """Mostra il livello dell'utente."""
    target = member or ctx.author
    user = ensure_user(target.id)
    await ctx.send(f"{target.name} — Level {user.get('level',1)} | EXP: {user.get('exp',0)}/{exp_to_next(user.get('level',1))}")

@bot.command(name="battle", aliases=["bt"]) 
async def battle_cmd(ctx, card_ref: str = None):
    """Combatti il floor corrente usando una carta (opzionale specificare indice o instance_id)."""
    user = ensure_user(ctx.author.id)
    inv = user["inventory"]
    if not inv:
        await ctx.send("Non hai carte per combattere.")
        return
    # select card
    chosen = None
    if card_ref:
        if card_ref.isdigit():
            idx = int(card_ref) - 1
            if 0 <= idx < len(inv):
                chosen = inv[idx]
        else:
            for c in inv:
                if c["instance_id"] == card_ref:
                    chosen = c
                    break
    if not chosen:
        chosen = inv[0]
    floor = user.get("floor",1)
    # create enemy power scaling with floor
    enemy_power = 100 + (floor - 1) * 50
    player_power = card_power(chosen)
    # simple random factor
    player_roll = player_power * random.uniform(0.8, 1.2)
    enemy_roll = enemy_power * random.uniform(0.8, 1.2)
    if player_roll >= enemy_roll:
        # win
        gold_gain = 50 + floor * 10
        exp_gain_user = 30 + floor * 5
        exp_gain_card = 40 + floor * 10
        user["gold"] = user.get("gold",0) + gold_gain
        user["exp"] = user.get("exp",0) + exp_gain_user
        chosen["exp"] = chosen.get("exp",0) + exp_gain_card
        lvl_msgs = maybe_level_up_user(user)
        # card level up
        while chosen.get("level",1) < chosen.get("max_level",30):
            need = 100 * chosen.get("level",1)
            if chosen.get("exp",0) >= need:
                chosen["exp"] -= need
                chosen["level"] += 1
            else:
                break
        await save_data()
        msg = f"🏆 Vittoria! Guadagni {gold_gain} gold. Carta `{chosen['name']}` guadagna {exp_gain_card} EXP."
        if lvl_msgs:
            msg += f"\n" + "\n".join(lvl_msgs)
        await ctx.send(msg)
    else:
        # lose: small penalties
        user["stamina"] = max(0, user.get("stamina",0) - 3)
        await save_data()
        await ctx.send("❌ Sconfitta. Perdi 3 stamina.")

@bot.command(name="floor", aliases=["fl"]) 
async def floor_cmd(ctx, action: str = None):
    """Gestisci i floors. -floor next per passare al floor successivo (max 10). -floor set <n> per impostare."""
    user = ensure_user(ctx.author.id)
    if not action:
        await ctx.send(f"Sei al floor {user.get('floor',1)}")
        return
    if action.lower() == "next":
        if user.get("floor",1) < 10:
            user["floor"] = user.get("floor",1) + 1
            await save_data()
            await ctx.send(f"Hai raggiunto il floor {user['floor']}.")
        else:
            await ctx.send("Sei già al floor massimo (10).")
    elif action.isdigit():
        n = int(action)
        if 1 <= n <= 10:
            user["floor"] = n
            await save_data()
            await ctx.send(f"Floor impostato a {n}.")
        else:
            await ctx.send("Numero di floor non valido (1-10).")
    else:
        await ctx.send("Azione floor non riconosciuta.")

# error handler for cooldowns
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Comando in cooldown. Riprova tra {int(error.retry_after)} secondi.")
    else:
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
