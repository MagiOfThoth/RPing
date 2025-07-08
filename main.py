import os
TOKEN = os.getenv("Discord_Bot_Token")
import discord
from discord.ext.commands import Bot, has_permissions
from discord import app_commands, Embed, Role, HTTPException
import json
import os

# === INTENTS ===
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.guilds = True
intents.members = True
intents.messages = True

# === BOT SETUP ===
bot = Bot(command_prefix="!", intents=intents)
tree = bot.tree
flagged_messages = {}
SETTINGS_FILE = "settings.json"
TARGET_EMOJI = "🛎"
RESOLVE_EMOJI = "✅"

# === SETTINGS LOAD/SAVE ===
def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {}
    with open(SETTINGS_FILE, "r") as f:
        return json.load(f)

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=4)

settings = load_settings()

# === BOT STARTUP ===
@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Bot is online as {bot.user}")

# === SLASH COMMANDS ===
@tree.command(name="setalertchannel", description="Set the admin alert channel")
@app_commands.checks.has_permissions(manage_guild=True)
async def set_alert_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.guild:
        await interaction.response.send_message("❌ Command must be used in a server.", ephemeral=True)
        return
    gid = str(interaction.guild.id)
    settings[gid] = settings.get(gid, {})
    settings[gid]["admin_channel_id"] = channel.id
    save_settings(settings)
    await interaction.response.send_message(f"✅ Alert channel set to {channel.mention}", ephemeral=True)

@tree.command(name="setalertrole", description="Set the role to ping for alerts")
@app_commands.checks.has_permissions(manage_guild=True)
async def set_alert_role(interaction: discord.Interaction, role: Role):
    if not interaction.guild:
        await interaction.response.send_message("❌ Command must be used in a server.", ephemeral=True)
        return
    gid = str(interaction.guild.id)
    settings[gid] = settings.get(gid, {})
    settings[gid]["role_id_to_ping"] = role.id
    save_settings(settings)
    await interaction.response.send_message(f"✅ Alert role set to {role.mention}", ephemeral=True)

@tree.command(name="viewalertsettings", description="View the current alert settings")
@app_commands.checks.has_permissions(manage_guild=True)
async def view_alert_settings(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("❌ Command must be used in a server.", ephemeral=True)
        return

    gid = str(interaction.guild.id)
    guild_settings = settings.get(gid)
    if not guild_settings:
        await interaction.response.send_message("⚠️ No alert settings set yet.", ephemeral=True)
        return

    admin_channel = interaction.guild.get_channel(guild_settings.get("admin_channel_id"))
    role = interaction.guild.get_role(guild_settings.get("role_id_to_ping"))

    channel_text = admin_channel.mention if admin_channel else "`[Deleted channel]`"
    role_text = role.mention if role else "`[Deleted role]`"

    embed = Embed(title="🔧 Alert Settings", color=discord.Color.green())
    embed.add_field(name="Admin Channel", value=channel_text, inline=False)
    embed.add_field(name="Ping Role", value=role_text, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# === EMOJI REACTION HANDLING ===
@bot.event
async def on_raw_reaction_add(payload):
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return

    user = guild.get_member(payload.user_id)
    if not user or user.bot:
        return

    gid = str(guild.id)
    if gid not in settings:
        return

    admin_channel_id = settings[gid].get("admin_channel_id")
    role_id_to_ping = settings[gid].get("role_id_to_ping")
    if not admin_channel_id or not role_id_to_ping:
        return

    if str(payload.emoji) == TARGET_EMOJI:
        if payload.message_id in flagged_messages:
            return

        channel = guild.get_channel(payload.channel_id)
        if not channel:
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return

        admin_channel = guild.get_channel(admin_channel_id)
        role = guild.get_role(role_id_to_ping)

        msg_preview = message.content[:1024] if message.content else (
            f"[Attachment: {message.attachments[0].filename}]" if message.attachments else "*[No text content]*")
        msg_link = f"https://discord.com/channels/{guild.id}/{channel.id}/{message.id}"

        embed = Embed(
            title="🔔 Message flagged!",
            description=f"{user.mention} reacted with 🛎 in {channel.mention}",
            color=discord.Color.orange()
        )
        embed.add_field(name="Quoted Message", value=msg_preview, inline=False)
        embed.add_field(name="Channel", value=channel.mention)
        embed.add_field(name="Jump to Message", value=f"[Click here to view]({msg_link})", inline=False)
        embed.set_footer(text=f"Message ID: {message.id}")

        try:
            bot_msg = await admin_channel.send(content=role.mention, embed=embed)
            await bot_msg.add_reaction(RESOLVE_EMOJI)
            flagged_messages[payload.message_id] = bot_msg.id
        except Exception as e:
            print(f"⚠️ Error sending alert: {e}")

    elif str(payload.emoji) == RESOLVE_EMOJI:
        mod_role = guild.get_role(role_id_to_ping)
        if mod_role not in user.roles:
            return

        original_msg_id = None
        for orig_id, bot_msg_id in flagged_messages.items():
            if bot_msg_id == payload.message_id:
                original_msg_id = orig_id
                break

        if not original_msg_id:
            return

        # Remove the 🛎 reaction
        for chan in guild.text_channels:
            try:
                msg = await chan.fetch_message(original_msg_id)
                await msg.clear_reaction(TARGET_EMOJI)
                break
            except Exception as e:
                print(f"❌ Could not clear reaction in {chan.name}: {e}")
                continue

        # Delete the admin alert message
        admin_channel = guild.get_channel(payload.channel_id)
        try:
            bot_msg = await admin_channel.fetch_message(payload.message_id)
            await bot_msg.delete()
        except Exception as e:
            print(f"⚠️ Error deleting admin alert: {e}")

        del flagged_messages[original_msg_id]

# === ERROR HANDLER ===
@set_alert_channel.error  # type: ignore
@set_alert_role.error  # type: ignore
@view_alert_settings.error  # type: ignore
async def permissions_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message("🚫 You don't have permission for this command.", ephemeral=True)
    else:
        print(f"Command error: {error}")

# === RUN THE BOT ===
try:
    TOKEN = os.getenv("Discord_Bot_Token")
    if not TOKEN:
        raise Exception("🔐 Please add your bot token under Secrets as Discord_Bot_Token")
    bot.run(TOKEN)
except HTTPException as e:
    if e.status == 429:
        print("⚠️ Discord rate-limited this connection.")
    else:
        print(f"Discord HTTP error: {e}")
        raise e
except Exception as e:
    print(f"Bot startup error: {e}")
    raise e
