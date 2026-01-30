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
RARITY_WEIGHTS = [60, 25, 10, 5]  # weights for random drops

# rating rank for sorting inventory
RARITY_RANK = {"Common": 1, "Rare": 2, "Epic": 3, "Legendary": 4}

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
            "floor_unlocked": 1,
            # user selected card instance id:
            "selected": None,
        }
    # Normalize existing inventory entries if missing fields (basic migration)
    user = data["users"][uid]
    inv = user.get("inventory", [])
    for c in inv:
        if "level" not in c:
            c.setdefault("level", 1)
        if "exp" not in c:
            c.setdefault("exp", 0)
        if "max_level" not in c:
            c["max_level"] = RARITY_MAX_LEVEL.get(c.get("rarity", "Common"), 30)
        if "base" not in c:
            # try to find base by id
            base = next((b for b in CHARACTERS if b["id"] == c.get("id")), None)
            if base:
                c["base"] = base["base"]
                c.setdefault("ability", base.get("ability", ""))
                c.setdefault("image", base.get("image", ""))
    return user

def exp_to_next(level: int) -> int:
    return 100 * level

def maybe_level_up_user(user: dict) -> list:
    """Checks and performs user level ups. Returns list of level-up messages."""
    messages = []
    while user.get("exp", 0) >= exp_to_next(user.get("level", 1)):
        need = exp_to_next(user.get("level", 1))
        user["exp"] -= need
        user["level"] = user.get("level", 1) + 1
        # increase stamina as an effective max increase
        bonus = 5
        user["stamina"] = user.get("stamina", 0) + bonus
        messages.append(f"Level up! Now level {user['level']} (+{bonus} stamina).")
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

def sort_inventory(inv: list) -> list:
    """
    Return a new list sorted by rarity (desc), then level (desc),
    then instance timestamp (newer first).
    """
    def inst_time(c):
        parts = str(c.get("instance_id","")).split("_")
        try:
            return int(parts[1])
        except Exception:
            return 0
    return sorted(
        inv,
        key=lambda c: (
            -RARITY_RANK.get(c.get("rarity", "Common"), 1),
            -c.get("level", 1),
            -inst_time(c)
        )
    )

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
    lines = [f"Available commands (prefix `{PREFIX}`):"]
    for c in bot.commands:
        if c.hidden:
            continue
        names = ", ".join([c.name] + (c.aliases or []))
        doc = c.help or ""
        lines.append(f"- `{PREFIX}{names}` — {doc}")
    await ctx.send("\n".join(lines))

@bot.command(name="profile", aliases=["p"])
async def profile(ctx):
    """Show user profile: stamina, gold, level and cards."""
    user = ensure_user(ctx.author.id)
    await ctx.send(
        f"👤 **Profile — {ctx.author.name}**\n"
        f"⚡ Stamina: {user['stamina']}\n"
        f"💰 Gold: {user['gold']}\n"
        f"🎴 Cards owned: {len(user['inventory'])}\n"
        f"⭐ Level: {user.get('level',1)} | EXP: {user.get('exp',0)}/{exp_to_next(user.get('level',1))}\n"
        f"🗼 Floor: {user.get('floor',1)} (unlocked: {user.get('floor_unlocked',1)})"
    )

@bot.command(name="stamina")
async def stamina_cmd(ctx):
    """Show current stamina."""
    user = ensure_user(ctx.author.id)
    await ctx.send(f"⚡ Current stamina: **{user['stamina']}**")

@bot.command(name="gold", aliases=["g"])
async def gold_cmd(ctx):
    """Show current gold."""
    user = ensure_user(ctx.author.id)
    await ctx.send(f"💰 Gold: **{user['gold']}**")

@bot.command(name="inventory", aliases=["inv"])
async def inventory_cmd(ctx):
    """List user's cards (sorted by rarity and level)."""
    user = ensure_user(ctx.author.id)
    inv = user["inventory"]
    if not inv:
        await ctx.send("🎴 Your inventory is empty.")
        return
    sorted_inv = sort_inventory(inv)
    text = "🎴 **Your cards (sorted by rarity then level):**\n"
    for i, c in enumerate(sorted_inv[:50], start=1):
        name = c.get("name", "Unknown")
        rarity = c.get("rarity", "")
        iid = c.get("instance_id", "")
        lvl = c.get("level", 1)
        sel_mark = ""
        if user.get("selected") == iid:
            sel_mark = " 🔹 (selected)"
        text += f"{i}. {name} ({rarity}) Lv{lvl}{sel_mark} — id: `{iid}`\n"
    if len(sorted_inv) > 50:
        text += f"... and {len(sorted_inv)-50} more cards\n"
    await ctx.send(text)

@bot.command(name="select")
async def select_cmd(ctx, index: int):
    """Select a card to use in floors by inventory index (sorted by rarity+level). Usage: -select <index>"""
    user = ensure_user(ctx.author.id)
    inv = user["inventory"]
    if not inv:
        await ctx.send("Your inventory is empty.")
        return
    sorted_inv = sort_inventory(inv)
    if index < 1 or index > len(sorted_inv):
        await ctx.send(f"Invalid index (1-{len(sorted_inv)}).")
        return
    card = sorted_inv[index - 1]
    user["selected"] = card["instance_id"]
    await save_data()
    await ctx.send(f"Selected card `{card['name']}` (ID: `{card['instance_id']}`).")

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
        await ctx.send(f"⏳ Hourly not ready. Try again in {minutes} minutes and {seconds} seconds.")
        return
    amount = random.choice([5, 10, 15])
    user["last_hourly"] = now
    user["stamina"] = user.get("stamina", 0) + amount
    await save_data()
    await ctx.send(f"🎁 Hourly claimed! +{amount} stamina.")

@bot.command(name="farm")
@commands.cooldown(1, 900, commands.BucketType.user)
async def farm_cmd(ctx):
    """Farm to get gold (15-minute cooldown)."""
    user = ensure_user(ctx.author.id)
    amount = random.randint(100, 1000)
    user["gold"] = user.get("gold", 0) + amount
    await save_data()
    await ctx.send(f"⛏️ You gained **{amount}** gold!")

@bot.command(name="drop")
@commands.cooldown(1, 900, commands.BucketType.user)
async def drop_cmd(ctx):
    """Get a random card (15-minute cooldown), does not consume stamina."""
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
    """Show the base information of a card (base stats). Usage: -cinfo <card name>"""
    base = find_card_by_name(name)
    if not base:
        await ctx.send("Card not found.")
        return
    stats = base["base"]

    embed = discord.Embed(
        title=f"{base['name']} — Base stats (Common Lv1)",
        description=f"Ability: {base['ability']}",
        color=discord.Color.blue()
    )
    embed.add_field(name="HP", value=str(stats['hp']), inline=True)
    embed.add_field(name="ATK", value=str(stats['atk']), inline=True)
    embed.add_field(name="DEF", value=str(stats['def']), inline=True)
    embed.add_field(name="SPD", value=str(stats['spd']), inline=True)

    # max levels
    max_levels = "\n".join([f"{r}: {ml}" for r, ml in RARITY_MAX_LEVEL.items()])
    embed.add_field(name="Max level by rarity", value=max_levels, inline=False)

    image_url = base.get("image", "")
    if image_url:
        # put image at the bottom of the embed
        embed.set_image(url=image_url)

    await ctx.send(embed=embed)

@bot.command(name="enhance")
async def enhance_cmd(ctx, target: str, *args):
    """Enhance a card using other cards. Usage: -enhance <id_or_index> [-r Rarity] [-n Name] [-l Num]"""
    user = ensure_user(ctx.author.id)
    inv = user["inventory"]
    # find target by instance_id or numeric index (from sorted inventory)
    target_card = None
    if target.isdigit():
        idx = int(target) - 1
        sorted_inv = sort_inventory(inv)
        if 0 <= idx < len(sorted_inv):
            target_card = sorted_inv[idx]
    else:
        for c in inv:
            if c["instance_id"] == target:
                target_card = c
                break
    if not target_card:
        await ctx.send("Target card not found in inventory.")
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
    # gather sacrifice candidates (exclude target instance)
    candidates = []
    for c in list(inv):
        if c is target_card:
            continue
        if flag_r and c.get("rarity", "") != flag_r:
            continue
        if flag_n and c.get("name", "").lower() != flag_n.lower():
            continue
        candidates.append(c)
    if len(candidates) < flag_l:
        await ctx.send(f"Not enough cards to use (found {len(candidates)}, required {flag_l}).")
        return
    to_use = candidates[:flag_l]
    # compute exp gain: base 50 per card * rarity multiplier
    rarity_mul = {"Common": 1, "Rare": 1.5, "Epic": 2, "Legendary": 3}
    gained = 0
    for c in to_use:
        gained += 50 * rarity_mul.get(c.get("rarity","Common"),1)
        # remove from real inventory
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
    msg = f"Enhance complete: +{int(gained)} exp to the card."
    if leveled:
        msg += f" Levels increased up to {target_card['level']}."
    await ctx.send(msg)

@bot.command(name="level")
async def level_cmd(ctx, member: discord.Member = None):
    """Show the user's level."""
    target = member or ctx.author
    user = ensure_user(target.id)
    await ctx.send(f"{target.name} — Level {user.get('level',1)} | EXP: {user.get('exp',0)}/{exp_to_next(user.get('level',1))}")

# ------------------------
# BATTLE (animated embed)
# ------------------------
ENEMY_IMAGE = "https://cdn.discordapp.com/attachments/815650716730654743/1466823551628869786/IMG_6214.jpg?ex=697e2562&is=697cd3e2&hm=a30d2cdc6f5f819ca69f575fc2ae0e24719c085230e4521f5f07c6d64982d899"

def make_enemy_for_floor(floor: int) -> dict:
    """Return an enemy dict with stats scaled by floor."""
    base_hp = 120 + (floor - 1) * 80
    base_atk = 25 + (floor - 1) * 10
    base_def = 10 + (floor - 1) * 5
    base_spd = 20 + (floor - 1) * 2
    return {"name": f"Floor {floor} Enemy", "hp": base_hp, "atk": base_atk, "def": base_def, "spd": base_spd, "image": ENEMY_IMAGE}

def damage_formula(attacker_atk: int, defender_def: int) -> int:
    """Simple damage formula."""
    dmg = max(1, int(attacker_atk - defender_def * 0.5))
    return dmg

@bot.command(name="battle", aliases=["bt"])
async def battle_cmd(ctx):
    """
    Start an animated turn-based battle on the user's current floor using the selected card.
    The embed will be edited after each turn to animate the fight.
    """
    user = ensure_user(ctx.author.id)
    inv = user["inventory"]
    if not inv:
        await ctx.send("You don't have any cards to fight with.")
        return

    sel_id = user.get("selected")
    if not sel_id:
        await ctx.send("No card selected. Use `-select <index>` to choose a card first.")
        return

    # find selected card in inventory
    chosen = None
    for c in inv:
        if c.get("instance_id") == sel_id:
            chosen = c
            break
    if not chosen:
        await ctx.send("Selected card not found in inventory (it may have been used). Select another.")
        return

    floor = user.get("floor", 1)
    # require that floor is unlocked (user can only battle floors <= floor_unlocked)
    if floor > user.get("floor_unlocked", 1):
        await ctx.send(f"Floor {floor} is locked. Complete previous floors to unlock it.")
        return

    enemy = make_enemy_for_floor(floor)

    # compute player stats scaled by level
    lvl = chosen.get("level", 1)
    p_hp = int(chosen["base"]["hp"] * (1 + 0.02 * (lvl - 1)))
    p_atk_base = int(chosen["base"]["atk"] * (1 + 0.02 * (lvl - 1)))
    p_def_base = int(chosen["base"]["def"] * (1 + 0.02 * (lvl - 1)))
    p_spd_base = int(chosen["base"]["spd"] * (1 + 0.01 * (lvl - 1)))

    e_hp = enemy["hp"]
    e_atk = enemy["atk"]
    e_def = enemy["def"]
    e_spd = enemy["spd"]

    # prepare temporary stats for first-turn abilities
    p_atk = p_atk_base
    p_def = p_def_base
    p_spd = p_spd_base

    ability_used = False

    # apply first-turn ability effects BEFORE determining initiative (as requested)
    ability_text = ""
    ability = chosen.get("ability", "") or ""
    if "DEF" in ability and "100" in ability:
        # Hilde: double DEF for first turn
        p_def = int(p_def_base * 2)
        ability_text = f"{chosen['name']}'s ability activates: DEF doubled for first turn!"
    elif "SPD" in ability and "100" in ability:
        # Joo: double SPD for first turn
        p_spd = int(p_spd_base * 2)
        ability_text = f"{chosen['name']}'s ability activates: SPD doubled for first turn!"
    elif "ATK" in ability and "50" in ability:
        # Yoo: +50% ATK for first turn
        p_atk = int(p_atk_base * 1.5)
        ability_text = f"{chosen['name']}'s ability activates: ATK increased by 50% for first turn!"

    # determine who acts first using (possibly buffed) speed
    if p_spd > e_spd:
        turn_order = ["player", "enemy"]
    elif p_spd < e_spd:
        turn_order = ["enemy", "player"]
    else:
        turn_order = ["player", "enemy"] if random.choice([True, False]) else ["enemy", "player"]

    # initial embed
    embed = discord.Embed(title=f"Battle — Floor {floor}", color=discord.Color.blue())
    embed.add_field(name="Player", value=f"{chosen['name']} — Lv{lvl} ({chosen.get('rarity')})", inline=True)
    embed.add_field(name="Enemy", value=f"{enemy['name']}", inline=True)
    embed.add_field(name="Status", value="Battle starting...", inline=False)
    if chosen.get("image"):
        embed.set_thumbnail(url=chosen.get("image"))  # top-right image
    embed.set_image(url=enemy.get("image"))  # bottom image (enemy)
    message = await ctx.send(embed=embed)

    # small delay before starting
    await asyncio.sleep(1.0)

    # animate turns
    max_turns = 40
    turn_logs = []
    current_turn = 0
    player_current_hp = p_hp
    enemy_current_hp = e_hp

    # We need to revert temporary buffs after first player's turn and/or after first full round.
    buff_applied = True  # we applied the first-turn buff already in stats above
    while player_current_hp > 0 and enemy_current_hp > 0 and current_turn < max_turns:
        current_turn += 1
        # for each actor in order
        for actor in turn_order:
            if actor == "player":
                if player_current_hp <= 0 or enemy_current_hp <= 0:
                    break
                dmg = damage_formula(p_atk, e_def)
                enemy_current_hp -= dmg
                enemy_current_hp = max(0, enemy_current_hp)
                log = f"Turn {current_turn} — {chosen['name']} attacks for {dmg} damage. Enemy HP: {enemy_current_hp}."
                turn_logs.append(log)

                # update embed with latest logs
                short_logs = "\n".join(turn_logs[-6:])  # show last 6 actions for brevity
                embed = discord.Embed(title=f"Battle — Floor {floor}", description=short_logs, color=discord.Color.green())
                embed.add_field(name="Player", value=f"{chosen['name']} — Lv{lvl} ({chosen.get('rarity')})", inline=True)
                embed.add_field(name="Enemy", value=f"{enemy['name']}", inline=True)
                embed.add_field(name="HP", value=f"{chosen['name']}: {player_current_hp} | Enemy: {enemy_current_hp}", inline=False)
                if chosen.get("image"):
                    embed.set_thumbnail(url=chosen.get("image"))
                embed.set_image(url=enemy.get("image"))
                await message.edit(embed=embed)
                await asyncio.sleep(1.0)

                # remove first-turn buff effects that should only last their first use
                if buff_applied:
                    # after player's first action, revert ATK/SPD/DEF to base for subsequent turns
                    p_atk = p_atk_base
                    p_def = p_def_base
                    p_spd = p_spd_base
                    buff_applied = False

                if enemy_current_hp <= 0:
                    break

            else:  # enemy's turn
                if player_current_hp <= 0 or enemy_current_hp <= 0:
                    break
                dmg = damage_formula(e_atk, p_def)
                player_current_hp -= dmg
                player_current_hp = max(0, player_current_hp)
                log = f"Turn {current_turn} — Enemy attacks for {dmg} damage. {chosen['name']} HP: {player_current_hp}."
                turn_logs.append(log)

                short_logs = "\n".join(turn_logs[-6:])
                embed = discord.Embed(title=f"Battle — Floor {floor}", description=short_logs, color=discord.Color.red())
                embed.add_field(name="Player", value=f"{chosen['name']} — Lv{lvl} ({chosen.get('rarity')})", inline=True)
                embed.add_field(name="Enemy", value=f"{enemy['name']}", inline=True)
                embed.add_field(name="HP", value=f"{chosen['name']}: {player_current_hp} | Enemy: {enemy_current_hp}", inline=False)
                if chosen.get("image"):
                    embed.set_thumbnail(url=chosen.get("image"))
                embed.set_image(url=enemy.get("image"))
                await message.edit(embed=embed)
                await asyncio.sleep(1.0)

                if player_current_hp <= 0:
                    break

        # loop continues until someone dies or max_turns reached

    # final result embed
    if enemy_current_hp <= 0 and player_current_hp > 0:
        result = "Victory"
        color = discord.Color.green()
    elif player_current_hp <= 0 and enemy_current_hp > 0:
        result = "Defeat"
        color = discord.Color.red()
    else:
        result = "Draw"
        color = discord.Color.orange()

    final_desc = "\n".join(turn_logs[-15:]) if turn_logs else "No actions taken."
    embed = discord.Embed(title=f"Battle — Floor {floor} — {result}", description=final_desc, color=color)
    embed.add_field(name="Player HP left", value=str(player_current_hp), inline=True)
    embed.add_field(name="Enemy HP left", value=str(enemy_current_hp), inline=True)
    if chosen.get("image"):
        embed.set_thumbnail(url=chosen.get("image"))
    embed.set_image(url=enemy.get("image"))
    await message.edit(embed=embed)

    # apply rewards/penalties and progression
    if enemy_current_hp <= 0 and player_current_hp > 0:
        gold_gain = 50 + floor * 10
        exp_gain_user = 30 + floor * 5
        exp_gain_card = 40 + floor * 10
        user["gold"] = user.get("gold", 0) + gold_gain
        user["exp"] = user.get("exp", 0) + exp_gain_user
        # add exp to chosen instance
        chosen["exp"] = chosen.get("exp", 0) + exp_gain_card

        lvl_msgs = maybe_level_up_user(user)
        # level up card
        while chosen.get("level", 1) < chosen.get("max_level", 30):
            need = 100 * chosen.get("level", 1)
            if chosen.get("exp", 0) >= need:
                chosen["exp"] -= need
                chosen["level"] += 1
            else:
                break

        # unlock next floor
        if user.get("floor_unlocked", 1) < floor + 1:
            user["floor_unlocked"] = floor + 1

        await save_data()
        extra = f"\nYou won! +{gold_gain} gold, +{exp_gain_user} EXP. Next floor unlocked: {user.get('floor_unlocked', user.get('floor',1))}"
        if lvl_msgs:
            extra = "\n".join(lvl_msgs) + extra
        await ctx.send(extra)
    else:
        # loss penalty
        user["stamina"] = max(0, user.get("stamina", 0) - 3)
        await save_data()
        await ctx.send("You lost the battle. You lose 3 stamina.")

# Updated floor command: show info and restrict next to unlocked floors
@bot.command(name="floor", aliases=["fl"])
async def floor_cmd(ctx, action: str = None):
    """Manage floors. -floor next to go to the next floor (unlocks limited by progression). -floor <n> to set (only to unlocked)."""
    user = ensure_user(ctx.author.id)
    if not action:
        floor = user.get("floor", 1)
        unlocked = user.get("floor_unlocked", 1)
        # show enemy stats for current floor
        enemy = make_enemy_for_floor(floor)
        await ctx.send(
            f"You are at floor {floor} (unlocked up to {unlocked}).\n"
            f"Enemy stats — HP: {enemy['hp']} | ATK: {enemy['atk']} | DEF: {enemy['def']} | SPD: {enemy['spd']}"
        )
        return

    if action.lower() == "next":
        current = user.get("floor", 1)
        unlocked = user.get("floor_unlocked", 1)
        if current >= 10:
            await ctx.send("You are already at the maximum floor (10).")
            return
        if unlocked < current + 1:
            await ctx.send("Next floor is locked. Complete the current floor to unlock the next one.")
            return
        user["floor"] = current + 1
        await save_data()
        await ctx.send(f"You moved to floor {user['floor']}.")
        return

    # set to numeric floor only if unlocked
    if action.isdigit():
        n = int(action)
        unlocked = user.get("floor_unlocked", 1)
        if 1 <= n <= unlocked:
            user["floor"] = n
            await save_data()
            await ctx.send(f"Floor set to {n}.")
        else:
            await ctx.send(f"Cannot set floor to {n}. Unlocked up to {unlocked}.")
        return

    await ctx.send("Unrecognized floor action. Use `next` or a floor number you have unlocked.")

# error handler for cooldowns
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Command on cooldown. Try again in {int(error.retry_after)} seconds.")
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
