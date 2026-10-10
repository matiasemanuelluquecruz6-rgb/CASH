import os
import json
import random
import time
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = 1385040014236454932
DATA_FILE = "cash_balances.json"
STARTING_BALANCE = 100
WORK_REWARD = 5
intents = discord.Intents.default()
intents.message_content = True  # Necesario para leer comandos con prefijo como ,work y ,help
bot = commands.Bot(command_prefix=",", intents=intents, help_command=None)
balances = {}
blocked_until = {}
msj_channels = {}
lock = asyncio.Lock()


def load_data():
    global balances, blocked_until, msj_channels
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        balances = saved.get("balances", {})
        blocked_until = saved.get("blocked_until", {})
        msj_channels = saved.get("msj_channels", {})
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        balances, blocked_until, msj_channels = {}, {}, {}


def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"balances": balances, "blocked_until": blocked_until, "msj_channels": msj_channels}, f, indent=2)


load_data()


def bal(uid):
    key = str(uid)
    if key not in balances:
        balances[key] = STARTING_BALANCE
        save_data()
    return int(balances[key])


def setbal(uid, amount):
    balances[str(uid)] = max(0, int(amount))
    save_data()


def embed(title, description):
    e = discord.Embed(title=title, description=description, color=0x2ECC71)
    e.set_footer(text="Cash • Economía virtual")
    return e


def blocked(uid):
    return int(max(0, float(blocked_until.get(str(uid), 0)) - time.time()))


async def prefix_block_check(ctx):
    remaining = blocked(ctx.author.id)
    if remaining:
        await ctx.reply(embed=embed("⏳ Comandos bloqueados", f"Espera **{remaining} segundos** más."))
        return True
    return False


@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Cash conectado como {bot.user}; comandos slash sincronizados: {len(synced)}")
    except Exception as e:
        print(f"Error sincronizando comandos: {e}")


# /work and ,work
@bot.tree.command(name="work", description="Trabaja y gana 5 monedas.")
async def work_slash(interaction: discord.Interaction):
    remaining = blocked(interaction.user.id)
    if remaining:
        await interaction.response.send_message(embed=embed("⏳ Comandos bloqueados", f"Espera **{remaining} segundos** más."), ephemeral=True)
        return
    async with lock:
        amount = bal(interaction.user.id) + WORK_REWARD
        setbal(interaction.user.id, amount)
    await interaction.response.send_message(embed=embed("🧰 Trabajo terminado", f"Ganaste **5 monedas**. Tu saldo es **{amount}**."))


@bot.command(name="work")
async def work_prefix(ctx):
    if await prefix_block_check(ctx): return
    async with lock:
        amount = bal(ctx.author.id) + WORK_REWARD
        setbal(ctx.author.id, amount)
    await ctx.reply(embed=embed("🧰 Trabajo terminado", f"Ganaste **5 monedas**. Tu saldo es **{amount}**."))


# /balance and ,balance
@bot.tree.command(name="balance", description="Consulta tu saldo o el de otra persona.")
@app_commands.describe(usuario="Usuario opcional")
async def balance_slash(interaction: discord.Interaction, usuario: discord.User | None = None):
    target = usuario or interaction.user
    await interaction.response.send_message(embed=embed("💰 Saldo", f"{target.mention} tiene **{bal(target.id)} monedas**."))


@bot.command(name="balance")
async def balance_prefix(ctx, usuario: discord.User = None):
    target = usuario or ctx.author
    await ctx.reply(embed=embed("💰 Saldo", f"{target.mention} tiene **{bal(target.id)} monedas**."))


# /pay and ,pay
@bot.tree.command(name="pay", description="Envía monedas a otra persona.")
@app_commands.describe(usuario="Quien recibirá las monedas", cantidad="Cantidad a enviar")
async def pay_slash(interaction: discord.Interaction, usuario: discord.User, cantidad: app_commands.Range[int, 1]):
    if blocked(interaction.user.id):
        await interaction.response.send_message(embed=embed("⏳ Bloqueado", "No puedes usar economía temporalmente."), ephemeral=True); return
    if usuario.bot or usuario.id == interaction.user.id:
        await interaction.response.send_message(embed=embed("❌ Usuario inválido", "Elige a otra persona, no un bot."), ephemeral=True); return
    async with lock:
        current = bal(interaction.user.id)
        if current < cantidad:
            await interaction.response.send_message(embed=embed("❌ Saldo insuficiente", f"Tienes **{current} monedas**."), ephemeral=True); return
        setbal(interaction.user.id, current-cantidad)
        setbal(usuario.id, bal(usuario.id)+cantidad)
    await interaction.response.send_message(embed=embed("💸 Transferencia", f"Enviaste **{cantidad} monedas** a {usuario.mention}."))


@bot.command(name="pay")
async def pay_prefix(ctx, usuario: discord.User, cantidad: int):
    if await prefix_block_check(ctx): return
    if cantidad < 1 or usuario.bot or usuario.id == ctx.author.id:
        await ctx.reply(embed=embed("❌ Datos inválidos", "Indica una cantidad positiva y otro usuario que no sea bot.")); return
    async with lock:
        current = bal(ctx.author.id)
        if current < cantidad:
            await ctx.reply(embed=embed("❌ Saldo insuficiente", f"Tienes **{current} monedas**.")); return
        setbal(ctx.author.id, current-cantidad)
        setbal(usuario.id, bal(usuario.id)+cantidad)
    await ctx.reply(embed=embed("💸 Transferencia", f"Enviaste **{cantidad} monedas** a {usuario.mention}."))


# /crime and ,crime — 25% success; failed attempt blocks economy for one minute
async def do_crime(actor, target, send):
    if target.id == actor.id or target.bot:
        await send(embed=embed("❌ Objetivo inválido", "No puedes robarte a ti mismo ni a un bot.")); return
    async with lock:
        victim = bal(target.id)
        thief = bal(actor.id)
        if victim <= 0:
            await send(embed=embed("❌ Sin saldo", "Ese usuario no tiene monedas para robar.")); return
        if random.random() < 0.25:
            stolen = min(victim, max(1, int(victim * 0.20)))
            setbal(target.id, victim-stolen); setbal(actor.id, thief+stolen)
            result = embed("🦹 Robo exitoso", f"Robaste **{stolen} monedas** a {target.mention}.")
        else:
            blocked_until[str(actor.id)] = time.time()+60
            save_data()
            result = embed("🚨 Robo fallido", "Fallaste. Tus comandos de economía se bloquean durante **1 minuto**.")
    await send(embed=result)


@bot.tree.command(name="crime", description="Intenta robarle monedas a otro usuario.")
@app_commands.describe(usuario="Usuario al que intentas robar")
async def crime_slash(interaction: discord.Interaction, usuario: discord.User):
    if blocked(interaction.user.id):
        await interaction.response.send_message(embed=embed("⏳ Bloqueado", "No puedes usar economía temporalmente."), ephemeral=True); return
    await do_crime(interaction.user, usuario, interaction.response.send_message)


@bot.command(name="crime")
async def crime_prefix(ctx, usuario: discord.User):
    if await prefix_block_check(ctx): return
    await do_crime(ctx.author, usuario, ctx.reply)


def odds(bet):
    if bet <= 25: return 0.60, 1.5
    if bet <= 100: return 0.50, 1.9
    if bet <= 250: return 0.40, 2.4
    return 0.30, 3.2


class RollView(discord.ui.View):
    def __init__(self, uid, bet, chance, multiplier):
        super().__init__(timeout=45)
        self.uid, self.bet, self.chance, self.multiplier = uid, bet, chance, multiplier
        self.done = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.uid:
            await interaction.response.send_message("Este tablero no es tuyo.", ephemeral=True); return False
        return True

    @discord.ui.button(label="Confirmar apuesta", style=discord.ButtonStyle.success)
    async def confirm(self, interaction, button):
        if self.done:
            await interaction.response.send_message("Esta apuesta terminó.", ephemeral=True); return
        self.done = True
        async with lock:
            current = bal(self.uid)
            if current < self.bet:
                result = embed("❌ Saldo insuficiente", "Tu saldo ya no alcanza para esta apuesta.")
            elif random.random() < self.chance:
                winnings = int(self.bet*self.multiplier)
                setbal(self.uid, current-self.bet+winnings)
                result = embed("🎉 ¡Ganaste!", f"Premio: **{winnings} monedas**. Saldo final: **{current-self.bet+winnings}**.")
            else:
                setbal(self.uid, current-self.bet)
                result = embed("💸 Perdiste", f"Perdiste **{self.bet} monedas**. Saldo final: **{current-self.bet}**.")
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(embed=result, view=self)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction, button):
        if self.done: return
        self.done = True
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(embed=embed("Apuesta cancelada", "No se descontaron monedas."), view=self)

    async def on_timeout(self):
        for item in self.children: item.disabled = True


async def send_roll_board(user, amount, send):
    current = bal(user.id)
    if amount < 1 or amount > current:
        await send(embed=embed("❌ Apuesta inválida", f"Tu saldo es **{current} monedas**. Elige una apuesta positiva que puedas pagar.")); return
    chance, mult = odds(amount)
    text = (f"Usuario: {user.mention}\nSaldo: **{current}**\nApuesta: **{amount}**\n"
            f"Probabilidad de ganar: **{int(chance*100)} %**\nProbabilidad de perder: **{int((1-chance)*100)} %**\n"
            f"Premio total si ganas: **{int(amount*mult)}**\n\nConfirma o cancela.")
    await send(embed=embed("🎲 Roll — tablero de apuesta", text), view=RollView(user.id, amount, chance, mult))


@bot.tree.command(name="roll", description="Apuesta monedas con probabilidades según la cantidad.")
@app_commands.describe(cantidad="Cantidad que quieres apostar")
async def roll_slash(interaction: discord.Interaction, cantidad: app_commands.Range[int, 1]):
    if blocked(interaction.user.id):
        await interaction.response.send_message(embed=embed("⏳ Bloqueado", "No puedes usar economía temporalmente."), ephemeral=True); return
    await send_roll_board(interaction.user, cantidad, interaction.response.send_message)


@bot.command(name="roll")
async def roll_prefix(ctx, cantidad: int):
    if await prefix_block_check(ctx): return
    await send_roll_board(ctx.author, cantidad, ctx.reply)


# /top and ,top
@bot.tree.command(name="top", description="Muestra los 10 usuarios con más monedas.")
async def top_slash(interaction: discord.Interaction):
    await show_top(interaction.guild, interaction.response.send_message)


@bot.command(name="top")
async def top_prefix(ctx):
    await show_top(ctx.guild, ctx.reply)


async def show_top(guild, send):
    rows = sorted(((int(uid), int(value)) for uid, value in balances.items()), key=lambda x: x[1], reverse=True)[:10]
    lines = []
    for rank, (uid, value) in enumerate(rows, 1):
        member = guild.get_member(uid) if guild else None
        user = member or bot.get_user(uid)
        name = member.display_name if member else (user.name if user else f"Usuario {str(uid)[-4:]}")
        lines.append(f"**{rank}.** {name} — **{value} monedas**")
    await send(embed=embed("🏆 Top 10", "\n".join(lines) if lines else "Aún no hay datos."))


# /cashmoney — only the bot creator ID; not based on server roles
@bot.tree.command(name="cashmoney", description="Comando exclusivo del creador de Cash.")
@app_commands.describe(usuario="Usuario que recibirá las monedas", cantidad="Cantidad de monedas a crear")
async def cashmoney(interaction: discord.Interaction, usuario: discord.User, cantidad: app_commands.Range[int, 1]):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message(embed=embed("🔒 Acceso denegado", "Solo el creador de Cash puede usar este comando."), ephemeral=True); return
    async with lock:
        new_amount = bal(usuario.id) + cantidad
        setbal(usuario.id, new_amount)
    await interaction.response.send_message(embed=embed("♾️ Dinero generado", f"Se añadieron **{cantidad} monedas** a {usuario.mention}. Nuevo saldo: **{new_amount}**."))




# /msj — activa/desactiva avisos de mensajes eliminados en el canal actual
@bot.tree.command(name="msj", description="Activa o desactiva avisos de mensajes eliminados en este canal.")
@app_commands.checks.has_permissions(manage_messages=True)
async def msj(interaction: discord.Interaction):
    if interaction.guild is None or interaction.channel is None:
        await interaction.response.send_message(
            embed=embed("❌ No disponible", "Usa este comando dentro de un servidor."),
            ephemeral=True,
        )
        return

    guild_key = str(interaction.guild.id)
    channel_id = str(interaction.channel.id)
    channels = msj_channels.setdefault(guild_key, [])

    if channel_id in channels:
        channels.remove(channel_id)
        enabled = False
    else:
        channels.append(channel_id)
        enabled = True
    save_data()

    if enabled:
        description = (
            f"Los avisos de mensajes eliminados están **activados** en {interaction.channel.mention}.\\n"
            "El bot intentará indicar quién borró el mensaje y quién lo había enviado. "
            "Para identificar al autor de la eliminación, necesita el permiso **Ver registro de auditoría**."
        )
        title = "🟢 Registro activado"
    else:
        description = f"Los avisos de mensajes eliminados están **desactivados** en {interaction.channel.mention}."
        title = "⚪ Registro desactivado"

    await interaction.response.send_message(embed=embed(title, description), ephemeral=True)


@bot.event
async def on_message_delete(message: discord.Message):
    if message.guild is None:
        return
    configured = msj_channels.get(str(message.guild.id), [])
    if str(message.channel.id) not in configured:
        return

    # Los mensajes sin autor conocido o de bots no necesitan aviso.
    if message.author is None:
        return

    deleter_text = "No se pudo identificar quién lo eliminó"
    try:
        now = discord.utils.utcnow()
        async for entry in message.guild.audit_logs(
            limit=8,
            action=discord.AuditLogAction.message_delete,
        ):
            if entry.target and entry.target.id == message.author.id:
                extra_channel = getattr(entry.extra, "channel", None)
                age = (now - entry.created_at).total_seconds()
                if extra_channel and extra_channel.id == message.channel.id and age <= 8:
                    deleter_text = f"{entry.user.mention} eliminó el mensaje"
                    break
    except (discord.Forbidden, discord.HTTPException):
        pass

    content = message.content.strip() if message.content else ""
    if not content:
        content = "(sin texto; podría contener una imagen, archivo o inserción)"
    if len(content) > 900:
        content = content[:900] + "…"

    await message.channel.send(
        embed=embed(
            "🗑️ Mensaje eliminado",
            f"**Quién lo eliminó:** {deleter_text}\\n"
            f"**Autor del mensaje:** {message.author.mention}\\n"
            f"**Canal:** {message.channel.mention}\\n"
            f"**Contenido:**\\n> {content}",
        )
    )


# /help and ,help
HELP_TEXT = ("**/work** o **,work** — ganas 5 monedas.\n"
             "**/balance** o **,balance** — consulta saldo.\n"
             "**/pay** o **,pay** — envía monedas.\n"
             "**/roll** o **,roll** — apuestas con tablero.\n"
             "**/crime** o **,crime** — intentas robar.\n"
             "**/top** o **,top** — top 10.\n"
             "**/msj** — activa/desactiva avisos de mensajes eliminados en el canal; requiere Gestionar mensajes.\n"
             "**/help** o **,help** — muestra esta ayuda.\n"
             "**/cashmoney** — genera monedas; solo el creador puede usarlo.")


@bot.tree.command(name="help", description="Muestra los comandos de Cash.")
async def help_slash(interaction: discord.Interaction):
    await interaction.response.send_message(embed=embed("💚 Ayuda de Cash", HELP_TEXT), ephemeral=True)


@bot.command(name="help")
async def help_prefix(ctx):
    await ctx.reply(embed=embed("💚 Ayuda de Cash", HELP_TEXT))


if not TOKEN:
    raise RuntimeError("Falta la variable de entorno DISCORD_TOKEN en Railway.")
bot.run(TOKEN)
