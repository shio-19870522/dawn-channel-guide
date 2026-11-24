import asyncio
import logging
import os

import discord
from discord.ext import commands

logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("GUIDE_CHANNEL_ID", "1466318038704984197"))
intents = discord.Intents.default()
bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)
TITLE = "☁️ DAWN CLOUDY | CHANNEL GUIDE"
refresh_task = None

def groups(guild):
    cats = [(c.id, c.name) for c in guild.categories if c.name != "面談" and "hidden" not in c.name.casefold()]
    if any(isinstance(c, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.ForumChannel)) and c.category_id is None for c in guild.channels):
        cats.append((0, "カテゴリーなし"))
    return cats

def make_embed():
    return discord.Embed(title=TITLE, description="カテゴリーを選ぶと、チャンネル一覧と説明を**あなただけに**表示します。\n\n☁️ チャンネルの追加・変更は自動で反映されます。", color=0x8CCDEB)

class CategoryMenu(discord.ui.Select):
    def __init__(self, guild, page=0):
        opts = [discord.SelectOption(label=name[:100], value=str(cid), emoji="☁️") for cid, name in groups(guild)[page*25:(page+1)*25]]
        super().__init__(placeholder="☁️ カテゴリーを選択", options=opts or [discord.SelectOption(label="カテゴリーがありません", value="none")], custom_id=f"dawn:select:{page}")
    async def callback(self, interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("サーバー内で操作してください。", ephemeral=True)
        selected = self.values[0]
        if selected == "none":
            return await interaction.response.send_message("カテゴリーがありません。", ephemeral=True)
        cid = int(selected)
        names = dict(groups(interaction.guild))
        if cid not in names:
            return await interaction.response.send_message("このカテゴリーは削除されています。", ephemeral=True)
        category_name = names[cid]
        allowed_channel_names = None
        if "話す" in category_name:
            allowed_channel_names = {"ゆる作業", "自由"}
        elif "見る" in category_name:
            allowed_channel_names = {"おすすめグッズ"}
        channels = [
            ch for ch in interaction.guild.channels
            if isinstance(
                ch,
                (
                    discord.TextChannel,
                    discord.VoiceChannel,
                    discord.StageChannel,
                    discord.ForumChannel,
                ),
            )
            and (ch.category_id or 0) == cid
            and ch.permissions_for(interaction.user).view_channel
            and (
                allowed_channel_names is None
                or ch.name in allowed_channel_names
            )
        ]
        channels.sort(key=lambda ch: (ch.position, ch.id))
        if not channels:
            return await interaction.response.send_message("閲覧できるチャンネルはありません。", ephemeral=True)
        chunks = []
        current = ""
        for ch in channels:
            description = (getattr(ch, "topic", None) or "説明はまだ登録されていません。").replace("\n", " ").strip()[:150]
            description = discord.utils.escape_mentions(description).replace("@", "@\u200b")
            line = f"{ch.mention}\n{description}\n\n"
            if len(current) + len(line) > 3500:
                chunks.append(current)
                current = ""
            current += line
        if current:
            chunks.append(current)
        embeds = [discord.Embed(title=f"☁️ {names[cid]} ({i+1}/{len(chunks)})", description=chunk, color=0x8CCDEB) for i, chunk in enumerate(chunks)]
        await interaction.response.send_message(embeds=embeds[:10], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        for start in range(10, len(embeds), 10):
            await interaction.followup.send(embeds=embeds[start:start+10], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

class GuideView(discord.ui.View):
    def __init__(self, guild, page=0):
        super().__init__(timeout=None)
        self.add_item(CategoryMenu(guild, page))
        count = len(groups(guild))
        if count > 25:
            for label, target in (("◀ 前へ", page-1), ("次へ ▶", page+1)):
                button = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, disabled=target<0 or target*25>=count, custom_id=f"dawn:page:{page}:{target}")
                async def callback(interaction, target=target):
                    await interaction.response.edit_message(view=GuideView(interaction.guild, target))
                button.callback = callback
                self.add_item(button)

async def publish():
    channel = bot.get_channel(CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        logging.warning("Guide channel inaccessible: %s", CHANNEL_ID)
        return
    message = None
    async for old in channel.history(limit=200):
        if old.author.id == bot.user.id and old.embeds and old.embeds[0].title == TITLE:
            message = old
            break
    if message:
        await message.edit(embed=make_embed(), view=GuideView(channel.guild), allowed_mentions=discord.AllowedMentions.none())
    else:
        await channel.send(embed=make_embed(), view=GuideView(channel.guild), allowed_mentions=discord.AllowedMentions.none())

async def delayed_publish():
    await asyncio.sleep(3)
    try:
        await publish()
    except discord.HTTPException:
        logging.exception("Guide update failed")

def schedule():
    global refresh_task
    if refresh_task and not refresh_task.done():
        refresh_task.cancel()
    refresh_task = asyncio.create_task(delayed_publish())

@bot.event
async def on_ready():
    logging.info("Connected: %s", bot.user)
    try:
        await publish()
    except discord.HTTPException:
        logging.exception("Guide publish failed")

@bot.event
async def on_guild_channel_create(channel):
    if channel.guild.get_channel(CHANNEL_ID):
        schedule()

@bot.event
async def on_guild_channel_delete(channel):
    if channel.guild.get_channel(CHANNEL_ID):
        schedule()

@bot.event
async def on_guild_channel_update(before, after):
    if after.guild.get_channel(CHANNEL_ID):
        schedule()

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is missing")
    bot.run(TOKEN)
