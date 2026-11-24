import asyncio
import logging
import os
import sqlite3
from pathlib import Path

import discord
from discord.ext import commands

logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("GUIDE_CHANNEL_ID", "1466318038704984197"))
intents = discord.Intents.default()
bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)
TITLE = "☁️ DAWN CLOUDY | CHANNEL GUIDE"
refresh_task = None
EDITOR_USER_ID = 1294559769935482914
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
description_db = sqlite3.connect(DATA_DIR / "channel_descriptions.sqlite3")
description_db.execute(
    "CREATE TABLE IF NOT EXISTS channel_descriptions "
    "(channel_id INTEGER PRIMARY KEY, description TEXT NOT NULL)"
)
description_db.commit()

def groups(guild):
    cats = [(c.id, c.name) for c in guild.categories if c.name != "面談" and "hidden" not in c.name.casefold()]
    if any(isinstance(c, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.ForumChannel)) and c.category_id is None for c in guild.channels):
        cats.append((0, "カテゴリーなし"))
    return cats

def can_edit_descriptions(interaction):
    return bool(
        interaction.guild
        and (
            interaction.user.id == EDITOR_USER_ID
            or interaction.user.id == interaction.guild.owner_id
        )
    )


def saved_description(channel_id):
    row = description_db.execute(
        "SELECT description FROM channel_descriptions WHERE channel_id=?",
        (channel_id,),
    ).fetchone()
    return row[0] if row else ""


def save_description(channel_id, description):
    description = description.strip()
    if description:
        description_db.execute(
            "INSERT INTO channel_descriptions(channel_id, description) "
            "VALUES (?, ?) ON CONFLICT(channel_id) "
            "DO UPDATE SET description=excluded.description",
            (channel_id, description),
        )
    else:
        description_db.execute(
            "DELETE FROM channel_descriptions WHERE channel_id=?",
            (channel_id,),
        )
    description_db.commit()


def channels_for_category(guild, category_id, member):
    category_names = dict(groups(guild))
    category_name = category_names.get(category_id, "")
    allowed_channel_names = None
    if "話す" in category_name:
        allowed_channel_names = ("ゆる作業", "自由")
    elif "見る" in category_name:
        allowed_channel_names = ("新おすすめ",)
    channels = [
        channel for channel in guild.channels
        if isinstance(
            channel,
            (
                discord.TextChannel,
                discord.VoiceChannel,
                discord.StageChannel,
                discord.ForumChannel,
            ),
        )
        and (channel.category_id or 0) == category_id
        and channel.permissions_for(member).view_channel
        and (
            allowed_channel_names is None
            or any(name in channel.name for name in allowed_channel_names)
        )
    ]
    return sorted(channels, key=lambda channel: (channel.position, channel.id))


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
        channels = channels_for_category(
            interaction.guild, cid, interaction.user
        )
        if not channels:
            return await interaction.response.send_message("閲覧できるチャンネルはありません。", ephemeral=True)
        chunks = []
        current = ""
        for ch in channels:
            description = (
                saved_description(ch.id)
                or getattr(ch, "topic", None)
                or "説明はまだ登録されていません。"
            ).replace("\n", " ").strip()[:150]
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

class DescriptionModal(discord.ui.Modal, title="チャンネル説明を編集"):
    def __init__(self, channel):
        super().__init__(timeout=300)
        self.channel_id = channel.id
        current = (
            saved_description(channel.id)
            or getattr(channel, "topic", None)
            or ""
        )
        self.description = discord.ui.TextInput(
            label="説明文",
            style=discord.TextStyle.paragraph,
            placeholder="このチャンネルの説明を入力",
            default=current[:150] or None,
            required=False,
            max_length=150,
        )
        self.add_item(self.description)

    async def on_submit(self, interaction):
        if not can_edit_descriptions(interaction):
            return await interaction.response.send_message(
                "説明文を編集できるのは、しおちゃんとサーバーオーナーだけです。",
                ephemeral=True,
            )
        save_description(self.channel_id, str(self.description.value))
        await interaction.response.send_message(
            "説明文を保存したで！カテゴリーを選び直すと反映内容を確認できるで。",
            ephemeral=True,
        )


class DescriptionChannelMenu(discord.ui.Select):
    def __init__(self, channels):
        options = [
            discord.SelectOption(
                label=channel.name[:100],
                value=str(channel.id),
            )
            for channel in channels[:25]
        ]
        super().__init__(
            placeholder="説明を追加・変更するチャンネル",
            options=options,
        )
        self.channels = {channel.id: channel for channel in channels}

    async def callback(self, interaction):
        if not can_edit_descriptions(interaction):
            return await interaction.response.send_message(
                "説明文を編集できるのは、しおちゃんとサーバーオーナーだけです。",
                ephemeral=True,
            )
        channel = self.channels.get(int(self.values[0]))
        if channel is None:
            return await interaction.response.send_message(
                "チャンネルが見つかりません。メニューを開き直してください。",
                ephemeral=True,
            )
        await interaction.response.send_modal(DescriptionModal(channel))


class DescriptionChannelView(discord.ui.View):
    def __init__(self, channels):
        super().__init__(timeout=180)
        self.add_item(DescriptionChannelMenu(channels))


class DescriptionCategoryMenu(discord.ui.Select):
    def __init__(self, guild):
        options = [
            discord.SelectOption(label=name[:100], value=str(category_id))
            for category_id, name in groups(guild)
        ]
        super().__init__(
            placeholder="説明を追加・変更するカテゴリー",
            options=options[:25],
        )

    async def callback(self, interaction):
        if not can_edit_descriptions(interaction):
            return await interaction.response.send_message(
                "説明文を編集できるのは、しおちゃんとサーバーオーナーだけです。",
                ephemeral=True,
            )
        category_id = int(self.values[0])
        channels = channels_for_category(
            interaction.guild, category_id, interaction.user
        )
        if not channels:
            return await interaction.response.send_message(
                "このカテゴリーに編集できるチャンネルがありません。",
                ephemeral=True,
            )
        await interaction.response.send_message(
            "説明を追加・変更するチャンネルを選んでな。",
            view=DescriptionChannelView(channels),
            ephemeral=True,
        )


class DescriptionCategoryView(discord.ui.View):
    def __init__(self, guild):
        super().__init__(timeout=180)
        self.add_item(DescriptionCategoryMenu(guild))


class DescriptionEditButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="説明文を追加・変更",
            style=discord.ButtonStyle.primary,
            custom_id="dawn:description:edit",
        )

    async def callback(self, interaction):
        if not can_edit_descriptions(interaction):
            return await interaction.response.send_message(
                "説明文を編集できるのは、しおちゃんとサーバーオーナーだけです。",
                ephemeral=True,
            )
        await interaction.response.send_message(
            "説明を追加・変更するカテゴリーを選んでな。",
            view=DescriptionCategoryView(interaction.guild),
            ephemeral=True,
        )


class GuideView(discord.ui.View):
    def __init__(self, guild, page=0):
        super().__init__(timeout=None)
        self.add_item(CategoryMenu(guild, page))
        self.add_item(DescriptionEditButton())
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
