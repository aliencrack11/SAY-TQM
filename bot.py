# main.py
"""
Femb-Paradise bot - reconstrucción de servidor + sistema de tickets con embeds y reacciones.
Requisitos: discord.py v2.x, python-dotenv
Crea un .env con BOT_TOKEN=tu_token y opcionalmente LOG_CHANNEL_ID (int) o STAFF_ROLE_NAME.
"""

import os
import asyncio
import logging
import json
import re
import time
import unicodedata
import random
from collections import deque
from typing import Optional, Dict, List

import discord
from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime, timedelta


# ---------------- Config & env ----------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
# Opcional: puedes poner el ID numérico del canal de logs en .env (ej: 1443306834906845387)
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID")) if os.getenv("LOG_CHANNEL_ID") else None
LOG_CHANNEL_NAME = os.getenv("LOG_CHANNEL_NAME", "logs-bot")
STAFF_ROLE_NAME = os.getenv("STAFF_ROLE_NAME", "Staff")
DEFAULT_PREFIX_EMOJI = "🎇"
TICKET_MESSAGES_FILE = "ticket_messages.json"
WARNS_FILE = "warns.json"

# SUPERUSER (zapatoortopedicoizquierdo) - cambia si necesitas otro
SUPERUSER_ID = 1382693027600007200

if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN missing - configura tu .env")

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s",
                    handlers=[logging.FileHandler("femb_paradise_bot.log", encoding="utf-8"),
                              logging.StreamHandler()])
logger = logging.getLogger("FembParadise")

# ---------------- Intents & Bot ----------------
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.reactions = True
intents.messages = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ---------------- Utilities (stylize / names) ----------------
NORMAL = "abcdefghijklmnopqrstuvwxyz"
STYLIZED = "𝙖𝙗𝙘𝙙𝙚𝙛𝙜𝙝𝙞𝙟𝙠𝙡𝙢𝙣𝙤𝙥𝙦𝙧𝙨𝙩𝙪𝙫𝙬𝙭𝙮𝙯"
TRANSL = {ord(n): s for n, s in zip(NORMAL, STYLIZED)}

def stylize(text: str) -> str:
    result = []
    for ch in text:
        if ch.isalpha():
            lower = ch.lower()
            if lower in NORMAL:
                result.append(TRANSL[ord(lower)])
            else:
                result.append(ch)
        else:
            result.append(ch)
    return "".join(result)

def decorate_name(name: str, fallback_emoji: str = DEFAULT_PREFIX_EMOJI) -> str:
    if name.startswith("「") and "」" in name:
        return name
    # intentar extraer emoji al inicio
    m = re.match(r"^(?P<emoji>[\U0001F000-\U0001FFFF\u2600-\u26FF\u2700-\u27BF])(?:[・\-\s]?)(?P<rest>.+)$", name)
    if m:
        emoji = m.group("emoji")
        rest = m.group("rest").strip()
    else:
        parts = re.split(r"[・\-\s]", name, maxsplit=1)
        if len(parts) == 2 and len(parts[0]) <= 2:
            emoji = parts[0]
            rest = parts[1]
        else:
            emoji = fallback_emoji
            rest = name
    styled = stylize(rest)
    return f"「{emoji}」{styled}"

def strip_decor(name: str) -> str:
    if name.startswith("「") and "」" in name:
        return name.split("」", 1)[1]
    return name

def normalize_name_for_matching(name: str) -> str:
    if not name:
        return ""
    name = name.replace("「", "").replace("」", "").strip().lower()
    name = unicodedata.normalize("NFKD", name)
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    name = name.replace("—", "-").replace("–", "-")
    return name

def is_ticket_channel_name(name: str) -> bool:
    norm = normalize_name_for_matching(name)
    return "ticket" in norm

# ---------------- Structure & tickets ----------------
STRUCTURE = [
    {
        "category_name": "🏠・INFORMACIÓN",
        "text_channels": [
            "👋・bienvenida", "📜・reglas", "📢・anuncios", "🛠️・actualizaciones", "🎭・roles-info", "❓・faq"
        ],
        "voice_channels": []
    },
    {
        "category_name": "💬・COMUNIDAD",
        "text_channels": [
            "💬・chat-general", "🤣・memes", "🙋・presentaciones", "📸・clips-y-fotos", "🎨・arte-de-la-comunidad", "❔・preguntas"
        ],
        "voice_channels": ["🔊・General", "🗣️・Charla-casual", "🎵・Música-(con-bot)", "🎮・Juegos"]
    },
    {
        "category_name": "🎮・JUEGO",
        "text_channels": [
            "📰・game-news", "📘・tutoriales", "⚔️・builds-y-estrategias", "🐞・reportes-bugs", "💡・sugerencias", "🤝・matchmaking", "🤖・comandos-bot"
        ],
        "voice_channels": []
    },
    {
        "category_name": "🛠️・STAFF",
        "text_channels": [
            "🛠️・staff-chat", "🚨・reportes-internos", "🔨・ban-logs", "⚠️・warn-logs", "🧠・ideas-staff", "📌・pendientes", "🎫・soporte-tickets"
        ],
        "voice_channels": []
    },
    {
        "category_name": "🎟️・TICKETS",
        "text_channels": [
            "🎟️・ticket-ayuda-general", "🚫・ticket-reportar-jugador", "🎮・ticket-problemas-con-el-juego",
            "🖥️・ticket-problemas-técnicos", "⚖️・ticket-apelar-sanción", "💰・ticket-donaciones"
        ],
        "voice_channels": []
    },
    {
        "category_name": "🎉・EVENTOS",
        "text_channels": ["🎉・eventos-activos", "🏆・ganadores", "🎁・giveaways"],
        "voice_channels": []
    },
    {
        "category_name": "🤖・BOTS",
        "text_channels": ["📡・comandos", "📈・niveles", "🗂️・logs-bot"],
        "voice_channels": []
    },
    {
        "category_name": "🧾・ARCHIVOS-Y-RECURSOS",
        "text_channels": ["⬇️・descargas", "📄・documentación", "📜・historial-del-proyecto",
                          "📚・lore-cakeverso", "🚧・progreso-del-juego", "👀・sneak-peeks", "🗳️・votaciones"],
        "voice_channels": []
    }
]

TICKET_TEMPLATES: Dict[str, Dict] = {
    "ticket-ayuda-general": {
        "title": "🆘 Ayuda General",
        "description": "Antes de abrir un ticket asegúrate de que tu duda no esté respondida en los canales informativos.\nProporciona información clara para que podamos ayudarte rápidamente.",
        "fields": [("📄 Información necesaria", "• Explica tu duda o problema de forma detallada.\n• Adjunta capturas, ejemplos o contexto relevante.\n• Indica si probaste alguna solución previamente.")],
        "footer": "⚠️ Nota: El uso indebido del sistema de tickets puede causar advertencias o sanciones.",
        "reaction": "🎟️"
    },
    "ticket-reportar-jugador": {
        "title": "🚫 Reportar a un Usuario",
        "description": "Antes de reportar, asegúrate de que realmente se haya incumplido una norma del servidor o de Discord.\nNo incluyas pruebas falsificadas o podrás recibir una sanción.",
        "fields": [
            ("📄 Información necesaria", "• Tag / ID / usuario a reportar.\n• Canal donde ocurrió el incidente.\n• Razón del reporte.\n• Pruebas (capturas, vídeos, grabaciones de voz)."),
            ("🆔 Obtener ID", "Activa el modo desarrollador en Ajustes > Avanzado > Modo Desarrollador.\nLuego clic derecho en el usuario → Copiar ID.")
        ],
        "footer": None,
        "reaction": "🚫"
    },
    "ticket-problemas-con-el-juego": {
        "title": "🎮 Problemas con el Juego",
        "description": "Si tienes inconvenientes dentro del juego, aporta toda la información posible para acelerar la asistencia.",
        "fields": [("📄 Información necesaria", "• Describe el problema con detalle (error, bug, crasheos).\n• Nombre del juego.\n• Plataforma (PC, móvil, consola).\n• Capturas, grabaciones o mensajes de error.\n• Pasos realizados antes del fallo.")],
        "footer": "ℹ️ Nota: Si el problema es general y ya está siendo investigado, te informaremos en el ticket.",
        "reaction": "🎮"
    },
    "ticket-problemas-técnicos": {
        "title": "🖥️ Problemas Técnicos",
        "description": "Usa este ticket para problemas con Discord o con el juego.",
        "fields": [("📄 Información necesaria", "• Explica tu problema detalladamente.\n• Adjunta capturas o vídeos del problema.\n• Acciones que ya intentaste.")],
        "footer": None,
        "reaction": "🖥️"
    },
    "ticket-apelar-sanción": {
        "title": "⚖️ Apelar Sanción",
        "description": "Proporciona información real y completa. Manipular datos resultará en apelación rechazada.",
        "fields": [("📄 Información necesaria", "• Tu Tag / ID de usuario.\n• Tipo de sanción (mute, ban, warn…).\n• Fecha aproximada.\n• Motivo por el cual crees que la sanción fue injusta.\n• Pruebas o contexto adicional.")],
        "footer": "⚠️ Importante: No abras múltiples apelaciones por el mismo caso.",
        "reaction": "⚖️"
    },
    "ticket-donaciones": {
        "title": "💰 Donaciones",
        "description": "Usa este ticket para resolver dudas o aportar a las donaciones del proyecto.",
        "fields": [("📄 Información necesaria", "• Método de donación que usarás o usaste.\n• Cantidad donada o a donar.\n• Captura del comprobante (si aplica).\n• Dudas sobre beneficios o roles.")],
        "footer": "💎 Nota: Las donaciones son voluntarias y no reembolsables.",
        "reaction": "💰"
    }
}

# ---------------- Persistence helpers ----------------
def load_ticket_messages() -> Dict[str, str]:
    if os.path.exists(TICKET_MESSAGES_FILE):
        try:
            with open(TICKET_MESSAGES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logger.exception("No se pudo leer ticket_messages.json")
    return {}

def save_ticket_messages(mapping: Dict[str, str]):
    try:
        with open(TICKET_MESSAGES_FILE, "w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2)
    except Exception:
        logger.exception("No se pudo guardar ticket_messages.json")

ticket_message_map: Dict[str, str] = load_ticket_messages()

def load_warns() -> Dict[str, List[Dict]]:
    if not os.path.exists(WARNS_FILE):
        with open(WARNS_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)
    try:
        with open(WARNS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("No se pudo leer warns.json")
        return {}

def save_warns(data: Dict[str, List[Dict]]):
    try:
        with open(WARNS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        logger.exception("No se pudo guardar warns.json")

# ---------------- Logging helper ----------------
async def get_log_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    # Prioriza ID si fue configurado
    if LOG_CHANNEL_ID:
        ch = guild.get_channel(LOG_CHANNEL_ID)
        if isinstance(ch, discord.TextChannel):
            return ch
    # Buscar por nombre
    ch = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
    return ch

async def log_action(guild: discord.Guild, title: str, description: str, color: int = 0x00ffcc):
    try:
        target = await get_log_channel(guild)
        embed = discord.Embed(title=title, description=description, color=color)
        embed.set_footer(text=f"Servidor: {guild.name} • ID: {guild.id}")
        embed.timestamp = discord.utils.utcnow()
        if target:
            await target.send(embed=embed)
        else:
            logger.info(f"[LOG NO CHANNEL] {guild.name}: {title} - {description}")
    except Exception:
        logger.exception("Error al enviar log")

# ---------------- Purge & create ----------------
async def purge_server(guild: discord.Guild, invoking_user: discord.Member, keep_channel_ids: Optional[List[int]] = None):
    if keep_channel_ids is None:
        keep_channel_ids = []
    for ch in list(guild.channels):
        try:
            if ch.id in keep_channel_ids:
                continue
            await ch.delete(reason=f"Rebuilding server by {invoking_user} via !Femb-Paradise")
        except Exception:
            logger.exception("No se pudo eliminar %s", getattr(ch, "name", str(ch)))
    await asyncio.sleep(1)

async def create_structure(guild: discord.Guild):
    global ticket_message_map
    for block in STRUCTURE:
        cat_name = block["category_name"]
        try:
            category = await guild.create_category(cat_name, reason="Creación estructura Femb-Paradise")
        except Exception:
            # si falla con emoji, usa texto simple
            safe_cat = re.sub(r"[^\w\s-]", "", cat_name)[:90]
            category = await guild.create_category(safe_cat, reason="Creación estructura Femb-Paradise (fallback)")
        # crear text channels
        for t in block["text_channels"]:
            decorated = decorate_name(t)
            try:
                ch = await guild.create_text_channel(decorated, category=category, reason="Creación estructura Femb-Paradise")
            except Exception:
                alt = decorated.replace(" ", "-")[:100]
                ch = await guild.create_text_channel(alt, category=category, reason="Creación estructura Femb-Paradise (fallback)")
            # extraer key original (después del separator ・)
            raw = t
            if "・" in raw:
                key = raw.split("・", 1)[1].strip().lower()
            else:
                key = re.sub(r"^[^\w]+", "", raw).strip().lower()
            key = key.replace(" ", "-").replace("_", "-")
            if key in TICKET_TEMPLATES:
                template = TICKET_TEMPLATES[key]
                embed = discord.Embed(title=template["title"], description=template["description"], color=0x99ccff)
                for fname, fval in template["fields"]:
                    embed.add_field(name=fname, value=fval, inline=False)
                if template["footer"]:
                    embed.set_footer(text=template["footer"])
                embed.add_field(name="\u200b", value="🔽 **PARA ABRIR UN TICKET REACCIONA**", inline=False)
                try:
                    msg = await ch.send(embed=embed)
                    await msg.add_reaction(template["reaction"])
                    ticket_message_map[str(msg.id)] = key
                    save_ticket_messages(ticket_message_map)
                except Exception:
                    logger.exception("No se pudo enviar embed en %s", ch.name)
        # crear voice channels
        for v in block.get("voice_channels", []):
            decorated_v = decorate_name(v)
            try:
                await guild.create_voice_channel(decorated_v, category=category, reason="Creación estructura Femb-Paradise")
            except Exception:
                alt = decorated_v.replace(" ", "-")[:100]
                await guild.create_voice_channel(alt, category=category, reason="Creación estructura Femb-Paradise (fallback)")
    return ticket_message_map

# ---------------- Ticket creation ----------------
async def create_ticket_channel(guild: discord.Guild, owner: discord.Member, template_key: str):
    tickets_cat = discord.utils.find(lambda c: (isinstance(c, discord.CategoryChannel) and (c.name.upper().startswith("🎟️") or "TICKETS" in c.name.upper())), guild.categories)
    if not tickets_cat:
        tickets_cat = await guild.create_category("🎟️・TICKETS", reason="Crear categoría de tickets dinámica")
    base_name = f"ticket-{owner.name}".lower()
    base_styl = stylize(base_name)
    existing_stripped = [strip_decor(c.name).lower() for c in tickets_cat.channels]
    counter = 1
    proposed = base_styl
    while proposed in existing_stripped:
        counter += 1
        proposed = stylize(f"{base_name}-{counter}")
    template = TICKET_TEMPLATES.get(template_key)
    emoji = template["reaction"] if template else DEFAULT_PREFIX_EMOJI
    final_name = decorate_name(proposed, emoji)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        owner: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_messages=True)
    }
    staff_role = discord.utils.get(guild.roles, name=STAFF_ROLE_NAME)
    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_messages=True, manage_messages=True)
    channel = await guild.create_text_channel(final_name, category=tickets_cat, overwrites=overwrites, reason=f"Ticket creado por {owner} tipo {template_key}")
    embed = discord.Embed(title=f"Ticket — {template['title'] if template else 'Ticket'}",
                          description=(f"Hola {owner.mention}! Este canal ha sido creado para atender tu solicitud.\n\n"
                                       "Staff: para cerrar el ticket usad `!close`.\n"
                                       "Owner: describe aquí tu problema con la mayor cantidad de detalle posible."),
                          color=0x88ffcc)
    await channel.send(content=owner.mention, embed=embed)
    await log_action(guild, "Ticket creado", f"{channel.name} creado por {owner} ({owner.id}) tipo {template_key}")
    return channel

# ---------------- Commands ----------------
@bot.command(name="Femb-Paradise")
@commands.guild_only()
async def femb_paradise(ctx: commands.Context):
    invoker = ctx.author
    guild = ctx.guild
    # permiso: admin o superuser
    if not (ctx.author.guild_permissions.administrator or ctx.author.id == SUPERUSER_ID):
        await ctx.reply("❌ Necesitas permisos de **Administrador** para ejecutar este comando.", mention_author=False)
        return
    # confirmación si no es superuser
    if ctx.author.id != SUPERUSER_ID:
        confirm_message = await ctx.send(embed=discord.Embed(
            title="Confirmación requerida",
            description=(f"Has solicitado reconstruir completamente el servidor **{guild.name}**.\n"
                         "Esto **ELIMINARÁ TODOS LOS CANALES** actuales y creará una nueva estructura.\n\n"
                         "Si estás seguro, reacciona con ✅ en los próximos 10 segundos."),
            color=0xff66aa
        ))
        await confirm_message.add_reaction("✅")
        def check(reaction, user):
            return user == invoker and str(reaction.emoji) == "✅" and reaction.message.id == confirm_message.id
        try:
            await bot.wait_for("reaction_add", timeout=10.0, check=check)
        except asyncio.TimeoutError:
            await ctx.send("⏱️ Tiempo de confirmación agotado. Operación cancelada.", delete_after=8)
            return
    # asegurar logs antes de purge
    log_ch = await get_log_channel(guild)
    if not log_ch:
        try:
            log_ch = await guild.create_text_channel(LOG_CHANNEL_NAME, topic="Canal de logs del bot", reason="Crear canal de logs antes de reconstrucción")
        except Exception:
            log_ch = None
    # progreso (DM preferente)
    progress_msg = None
    try:
        dm = await invoker.create_dm()
        progress_msg = await dm.send("🔧 Iniciando reconstrucción del servidor... Esto puede tardar unos segundos.")
    except Exception:
        if log_ch:
            try:
                progress_msg = await log_ch.send("🔧 Iniciando reconstrucción del servidor... Esto puede tardar unos segundos.")
            except Exception:
                progress_msg = None
    try:
        keep_ids = [log_ch.id] if log_ch else []
        await purge_server(guild, invoker, keep_channel_ids=keep_ids)
        created_map = await create_structure(guild)
        await log_action(guild, "Servidor reconstruido", f"Reconstrucción ejecutada por {invoker} ({invoker.id})")
        if progress_msg:
            try:
                await progress_msg.edit(content="✅ Reconstrucción completa. Estructura creada correctamente.")
            except Exception:
                if log_ch:
                    await log_ch.send("✅ Reconstrucción completa. Estructura creada correctamente.")
    except Exception as e:
        logger.exception("Error durante la reconstrucción")
        if progress_msg:
            try:
                await progress_msg.edit(content=f"❌ Ocurrió un error durante la reconstrucción: `{e}`")
            except Exception:
                pass
        if log_ch:
            try:
                await log_ch.send(f"❌ Error durante la reconstrucción: `{e}`")
            except Exception:
                pass
        await log_action(guild, "Error reconstrucción", f"Error: {e}")

@bot.command(name="love")
async def love_cmd(ctx, user: discord.Member):
    import random
    porcentaje = random.randint(0, 100)
    await ctx.send(f"💘 **{ctx.author.mention} y {user.mention} tienen un {porcentaje}% de compatibilidad amorosa!**")

@bot.command(name="ship")
async def ship_cmd(ctx, user1: discord.Member, user2: discord.Member):
    import random
    porcentaje = random.randint(0, 100)
    heart = "💖" if porcentaje > 70 else "💛" if porcentaje > 40 else "💔"
    await ctx.send(f"{heart} **{user1.display_name} ❤️ {user2.display_name} = {porcentaje}%** {heart}")

@bot.command(name="banana")
async def banana_cmd(ctx, user: discord.Member = None):
    import random
    user = user or ctx.author

    # Si es el usuario especial (ID 1382693027600007200)
    if user.id == 1382693027600007200:
        tamaño = random.randint(40, 45)
    else:
        tamaño = random.randint(1, 45)

    # Crear barra visual proporcional
    bloques = tamaño // 2  # 1 bloque por cada 2 cm
    barra = "▮" * bloques
    if barra == "":
        barra = "▯"  # por si toca 1 cm, queda gracioso

    # Embed
    embed = discord.Embed(
        title="🍌 Medidor de Banana",
        description=(
            f"**La banana de {user.mention} mide `{tamaño} cm`** 😳\n\n"
            f"`{barra}` **{tamaño} cm** 🍌"
        ),
        color=0xffd500
    )

    embed.set_image(
        url="https://th.bing.com/th/id/OIP.ncj3Jg9FoK27NzLNvS31eAHaNI?w=115&h=180&c=7&r=0&o=7&pid=1.7&rm=3"
    )

    await ctx.send(embed=embed)

AMORPROPIO_GIFS = [
    "https://media.giphy.com/media/1BXa2alBjrCXC/giphy.gif",
    "https://media.giphy.com/media/26ufdipQqU2lhNA4g/giphy.gif"
]

@bot.command()
async def amorpropio(ctx):
    gif = random.choice(AMORPROPIO_GIFS)
    embed = discord.Embed(
        description=f"💖 {ctx.author.mention} se da amor a sí mismo",
        color=0xffddaa
    )
    embed.set_image(url=gif)
    await ctx.send(embed=embed)
    

@bot.command(name="ticket")
@commands.guild_only()
async def ticket_cmd(ctx: commands.Context, *, tipo: Optional[str] = "general"):
    channel = ctx.channel
    if not is_ticket_channel_name(channel.name):
        await ctx.reply("Este comando sólo puede usarse dentro de los canales de **Tickets** designados.", mention_author=False)
        return
    stripped = normalize_name_for_matching(strip_decor(channel.name))
    template_key = None
    for key in TICKET_TEMPLATES.keys():
        if key.replace("-", "_") in stripped or key in stripped:
            template_key = key
            break
    if not template_key:
        template_key = "ticket-ayuda-general"
    try:
        ticket_chan = await create_ticket_channel(ctx.guild, ctx.author, template_key)
        await ctx.reply(f"✅ He creado tu ticket: {ticket_chan.mention}", mention_author=False)
    except Exception as e:
        logger.exception("Error al crear ticket")
        await ctx.reply(f"❌ Error al crear el ticket: `{e}`", mention_author=False)

@bot.command(name="clear")
@commands.guild_only()
async def clear_cmd(ctx, amount: int=None, member: discord.Member=None):

    # SUPERUSER bypass
    if ctx.author.id != SUPERUSER_ID:
        if not ctx.author.guild_permissions.manage_messages:
            return await ctx.reply("❌ No tienes permisos para borrar mensajes.", mention_author=False)

    if amount is None or amount < 1:
        return await ctx.reply("❌ Uso correcto: `!clear cantidad` o `!clear cantidad @usuario`", mention_author=False)

    def check_msg(msg):
        if member:
            return msg.author.id == member.id
        return True

    deleted = await ctx.channel.purge(limit=amount + 1, check=check_msg)

    # Mensaje de confirmación
    confirm = await ctx.send(
        f"🧹 **Borrados `{len(deleted)-1}` mensajes** "
        f"{f'de {member.mention}' if member else ''}"
    )

    await asyncio.sleep(3)
    await confirm.delete()

    # Log al canal de moderación (usa el canal de logs configurado)
    log_channel = await get_log_channel(ctx.guild)
    if log_channel:
        embed = discord.Embed(
            title="🧹 Mensajes Borrados",
            color=0xff0000
        )
        embed.add_field(name="Moderador", value=ctx.author.mention, inline=False)
        embed.add_field(name="Cantidad", value=str(len(deleted)-1), inline=False)
        if member:
            embed.add_field(name="Mensajes de", value=member.mention, inline=False)
        embed.add_field(name="Canal", value=ctx.channel.mention, inline=False)
        await log_channel.send(embed=embed)

@bot.command(name="lamer")
async def lick_cmd(ctx, member: discord.Member = None):
    bot_id = bot.user.id

    if not member:
        return await ctx.reply("Menciona a alguien para lamer: `!lamer @user`", mention_author=False)

    gifs = [
        "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExbnZ4dmxtdjlyOW90bDZvZ2pqaWlxMWs0ODVieWlocWMwcXJuaG53YyZlcD12MV9naWZzX3NlYXJjaCZjdD1n/vPzbDN4rBxuvtpSpzF/giphy.gif",
        "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExbnZ4dmxtdjlyOW90bDZvZ2pqaWlxMWs0ODVieWlocWMwcXJuaG53YyZlcD12MV9naWZzX3NlYXJjaCZjdD1n/VFZDuY0nePXry/giphy.gif"
    ]

    if member.id == bot_id:
        return await ctx.send(f"😳 {ctx.author.mention} ¿me... lames? ¿estás bien? 👀")

    embed = discord.Embed(
        title="👅 Lamer",
        description=f"{ctx.author.mention} **lamió a** {member.mention} 😳",
        color=0xffcc66
    )
    embed.set_image(url=random.choice(gifs))

    await ctx.send(embed=embed)

# (Se eliminó la definición duplicada de AMORPROPIO_GIFS y del comando `amorpropio`
#  porque ya están definidos anteriormente en el archivo; mantener solo una definición
#  evita el CommandRegistrationError al arrancar el bot.)
@bot.command(name="close")
@commands.guild_only()
async def close_ticket(ctx: commands.Context):
    channel = ctx.channel
    # superuser bypass
    bypass = (ctx.author.id == SUPERUSER_ID)
    if not is_ticket_channel_name(channel.name) and not bypass:
        await ctx.reply("Este comando sólo funciona dentro de un canal de ticket.", mention_author=False)
        return
    owner = None
    for target, ow in channel.overwrites.items():
        if isinstance(target, discord.Member):
            try:
                if ow.view_channel:
                    owner = target
                    break
            except Exception:
                continue
    staff_role = discord.utils.get(ctx.guild.roles, name=STAFF_ROLE_NAME)
    is_staff = (staff_role in ctx.author.roles) if staff_role else ctx.author.guild_permissions.manage_messages
    if bypass or (owner and ctx.author.id == owner.id) or is_staff:
        try:
            await log_action(ctx.guild, "Ticket cerrado", f"{channel.name} cerrado por {ctx.author} ({ctx.author.id})")
            await channel.delete(reason=f"Cerrado por {ctx.author}")
        except Exception as e:
            logger.exception("Error al cerrar ticket")
            await ctx.reply(f"❌ No pude cerrar el ticket: `{e}`", mention_author=False)
    else:
        await ctx.reply("Sólo el creador del ticket, Staff o el SuperUser pueden cerrar este ticket.", mention_author=False)

@bot.command(name="help")
async def help_command(ctx: commands.Context):
    embed = discord.Embed(title="Femb-Paradise Bot — Ayuda", color=0xffaacc, description="Comandos disponibles y descripción breve.")
    embed.add_field(name="!Femb-Paradise", value="(Admin) Reconstruir TODO el servidor con la estructura predeterminada. Requiere confirmación (salvo SuperUser).", inline=False)
    embed.add_field(name="!ticket", value="Crear un ticket manualmente (si estás en un canal de tickets).", inline=False)
    embed.add_field(name="!close", value="Cerrar el ticket actual (Staff, creador o SuperUser).", inline=False)
    embed.add_field(name="Comandos extra", value="Reglas, 8ball, kiss, hug, slap, informacion, server, embed, encuesta, warn(s).", inline=False)
    await ctx.send(embed=embed)

# ---------------- Reaction handler (abrir tickets) ----------------
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return
    msg_id = str(payload.message_id)
    if msg_id not in ticket_message_map:
        return
    template_key = ticket_message_map[msg_id]
    expected_emoji = TICKET_TEMPLATES.get(template_key, {}).get("reaction")
    emoji_repr = str(payload.emoji)
    if expected_emoji and emoji_repr != expected_emoji:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    member = guild.get_member(payload.user_id)
    if not member:
        try:
            member = await guild.fetch_member(payload.user_id)
        except Exception:
            logger.exception("No se pudo obtener miembro que reaccionó")
            return
    try:
        await create_ticket_channel(guild, member, template_key)
        try:
            await member.send(f"✅ Se ha creado tu ticket en **{guild.name}**. Revisa el canal en el servidor.")
        except Exception:
            pass
    except Exception:
        logger.exception("Error creando ticket por reacción")

# ---------------- Anti-Nuke ----------------
NUKE_THRESHOLD = 2
NUKE_TIME_WINDOW = 8
nuke_logs = deque()
NUKE_LOCK = False
OWNER_PROTECT = SUPERUSER_ID

async def activate_nuke_lock(guild: discord.Guild, executor: discord.abc.User):
    global NUKE_LOCK
    if NUKE_LOCK:
        return
    NUKE_LOCK = True
    log_ch = await get_log_channel(guild)
    # revocar permisos peligrosos (intento prudente)
    for role in guild.roles:
        try:
            perms = role.permissions
            # desactivar permisos críticos
            perms = perms.replace(manage_channels=False, manage_roles=False, administrator=False)
            await role.edit(permissions=perms, reason="Anti-Nuke activado")
        except Exception:
            continue
    # intentar banear atacante (si no es owner protect)
    try:
        if executor.id != OWNER_PROTECT:
            await guild.ban(executor, reason="Ataque detectado — Anti-Nuke")
    except Exception:
        pass
    if log_ch:
        await log_ch.send(f"🚨 **ANTI–NUKE ACTIVADO** 🚨\nUsuario detectado: **{executor}** (`{executor.id}`)\nSe removieron permisos críticos y se bloqueó el servidor.")

@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    global nuke_logs
    try:
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
            executor = entry.user
            break
        else:
            return
    except Exception:
        return
    if executor.id == bot.user.id or executor.id == OWNER_PROTECT:
        return
    now = time.time()
    nuke_logs.append((executor.id, now))
    while nuke_logs and now - nuke_logs[0][1] > NUKE_TIME_WINDOW:
        nuke_logs.popleft()
    count = sum(1 for uid, t in nuke_logs if uid == executor.id)
    if count >= NUKE_THRESHOLD:
        await activate_nuke_lock(channel.guild, executor)

# ---------------- Anti-Spam & bot-new detection (unificado) ----------------
message_cache: Dict[int, List[float]] = {}
SPAM_LIMIT = 6
SPAM_WINDOW = 4
SPAM_MUTE_TIME = 60

NEW_BOTS: Dict[int, float] = {}

@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        NEW_BOTS[member.id] = time.time()

@bot.event
async def on_message(message: discord.Message):
    # always allow commands processing at the end
    if message.author.bot:
        # if bot is newly added and acts quickly -> ban
        if message.author.id in NEW_BOTS:
            elapsed = time.time() - NEW_BOTS[message.author.id]
            if elapsed < 120:
                try:
                    await message.guild.ban(message.author, reason="Bot malicioso detectado (auto)")
                    await log_action(message.guild, "Bot malicioso baneado", f"{message.author} fue baneado automáticamente ({message.author.id})")
                except Exception:
                    logger.exception("No se pudo banear bot malicioso")
                return
        return

    uid = message.author.id
    now = time.time()
    if uid not in message_cache:
        message_cache[uid] = []
    message_cache[uid].append(now)
    # limpiar
    while message_cache[uid] and now - message_cache[uid][0] > SPAM_WINDOW:
        message_cache[uid].pop(0)
    if len(message_cache[uid]) >= SPAM_LIMIT:
        # aplicar mute role
        mute_role = discord.utils.get(message.guild.roles, name="Muted")
        if not mute_role:
            try:
                mute_role = await message.guild.create_role(name="Muted", reason="Crear rol Muted automático")
                for ch in message.guild.channels:
                    try:
                        await ch.set_permissions(mute_role, send_messages=False, add_reactions=False)
                    except Exception:
                        continue
            except Exception:
                mute_role = None
        try:
            if mute_role:
                await message.author.add_roles(mute_role, reason="AutoMute por spam")
                await message.channel.send(f"🚫 **{message.author.mention} muteado por spam!** (AutoMod)")
                await log_action(message.guild, "AutoMute por spam", f"{message.author} muteado por spam (detected {SPAM_LIMIT} msgs en {SPAM_WINDOW}s).")
        except Exception:
            logger.exception("Error aplicando mute por spam")
    # Process commands after automod logic
    await bot.process_commands(message)

# ---------------- Anti-bots: keep simple handler ----------------
# (already handled in on_message + on_member_join)

# ---------------- Moderation commands (ban/kick/mute/unmute) ----------------
@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="Sin razón"):
    await member.ban(reason=reason)
    await ctx.send(f"🔨 Usuario baneado: {member} — {reason}")

@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="Sin razón"):
    await member.kick(reason=reason)
    await ctx.send(f"👢 Usuario expulsado: {member} — {reason}")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def mute(ctx, member: discord.Member):
    mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not mute_role:
        mute_role = await ctx.guild.create_role(name="Muted")
        for ch in ctx.guild.channels:
            try:
                await ch.set_permissions(mute_role, send_messages=False, add_reactions=False)
            except Exception:
                continue
    await member.add_roles(mute_role)
    await ctx.send(f"🔇 {member.mention} ha sido muteado.")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def unmute(ctx, member: discord.Member):
    mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if mute_role:
        await member.remove_roles(mute_role)
    await ctx.send(f"🔊 {member.mention} ahora puede hablar.")

# ---------------- Warns system ----------------
@bot.command(name="warn")
@commands.guild_only()
async def warn_cmd(ctx, member: discord.Member = None, *, reason: str = "Sin razón especificada"):
    warns = load_warns()
    # permiso: kick_members o superuser
    if ctx.author.id != SUPERUSER_ID and not ctx.author.guild_permissions.kick_members:
        return await ctx.reply("❌ No tienes permisos para usar este comando.", mention_author=False)
    if not member:
        return await ctx.reply("❌ Debes mencionar a un usuario: `!warn @usuario razón`", mention_author=False)
    uid = str(member.id)
    warns.setdefault(uid, [])
    warn_entry = {"moderador": ctx.author.id, "razon": reason, "fecha": time.strftime("%d/%m/%Y %H:%M:%S")}
    warns[uid].append(warn_entry)
    save_warns(warns)
    embed = discord.Embed(title="⚠️ Usuario Advertido", color=0xff6600)
    embed.add_field(name="👤 Usuario", value=member.mention, inline=False)
    embed.add_field(name="🛡️ Moderador", value=ctx.author.mention, inline=False)
    embed.add_field(name="📄 Razón", value=reason, inline=False)
    embed.add_field(name="📚 Cantidad total de warns", value=str(len(warns[uid])), inline=False)
    embed.timestamp = discord.utils.utcnow()
    await ctx.send(embed=embed)
    log_ch = await get_log_channel(ctx.guild)
    if log_ch:
        await log_ch.send(embed=embed)

@bot.command(name="unwarn")
@commands.guild_only()
async def unwarn_cmd(ctx, member: discord.Member = None, warn_id: int = None):
    warns = load_warns()
    if ctx.author.id != SUPERUSER_ID and not ctx.author.guild_permissions.kick_members:
        return await ctx.reply("❌ No tienes permisos para usar esto.", mention_author=False)
    if not member:
        return await ctx.reply("❌ Ejemplo correcto: `!unwarn @usuario ID`", mention_author=False)
    uid = str(member.id)
    if uid not in warns or len(warns[uid]) == 0:
        return await ctx.reply("❌ Ese usuario no tiene warns.", mention_author=False)
    if warn_id is None or warn_id < 1 or warn_id > len(warns[uid]):
        return await ctx.reply("❌ ID de warn inválida.", mention_author=False)
    removed = warns[uid].pop(warn_id - 1)
    save_warns(warns)
    embed = discord.Embed(title="🟢 Warn removido", color=0x55ff55)
    embed.add_field(name="👤 Usuario", value=member.mention, inline=False)
    embed.add_field(name="🛠️ Moderador", value=ctx.author.mention, inline=False)
    embed.add_field(name="🗑️ Warn eliminado", value=f"**Razón:** {removed['razon']}", inline=False)
    embed.add_field(name="📦 Warns restantes", value=str(len(warns[uid])), inline=False)
    await ctx.send(embed=embed)
    log_ch = await get_log_channel(ctx.guild)
    if log_ch:
        await log_ch.send(embed=embed)

@bot.command(name="warns")
@commands.guild_only()
async def warns_cmd(ctx, member: discord.Member = None):
    warns = load_warns()
    if not member:
        member = ctx.author
    uid = str(member.id)
    if uid not in warns or len(warns[uid]) == 0:
        return await ctx.reply(f"🟢 **{member}** no tiene ninguna advertencia.", mention_author=False)
    embed = discord.Embed(title=f"📚 Warns de {member}", color=0xffcc00)
    for idx, w in enumerate(warns[uid], 1):
        embed.add_field(name=f"⚠️ Warn #{idx}", value=f"**Razón:** {w['razon']}\n**Fecha:** {w['fecha']}\n**Moderador:** <@{w['moderador']}>", inline=False)
    await ctx.send(embed=embed)

# ---------------- Reglas command ----------------
@bot.command(name="Reglas")
async def reglas_cmd(ctx: commands.Context):
    embed = discord.Embed(
        title="📜 Reglas del Servidor",
        description=(
            "ㅤ〔 **Reglas a tener en cuenta** 〕ㅤㅤㅤㅤ\n\n"
            "• **1)** El respeto es obligatorio. No se toleran faltas de respeto.\n"
            "• **2)** Ayuda a otros usuarios cuando sea necesario.\n"
            "• **3)** Evita spam y flood.\n"
            "• **4)** Prohibido contenido NSFW o gore.\n"
            "• **5)** No se permite publicidad sin autorización.\n"
            "• **6)** No uses nombres o fotos ofensivas.\n"
            "• **7)** Raids están totalmente prohibidos.\n"
            "• **8)** Prohibidas amenazas de cualquier tipo.\n"
            "• **9)** No hables mal de otros clanes o comunidades.\n"
            "• **10)** No divulgues información personal.\n"
            "• **11)** Prohibido contenido ilegal, hacks o software malicioso.\n"
            "• **12)** Usa cada canal correctamente.\n"
            "• **13)** No hagas menciones innecesarias.\n"
            "• **14)** No se permite lenguaje tóxico o discriminatorio.\n"
            "• **15)** Prohibido usar hacks o exploits.\n"
            "• **16)** No suplantes a otros usuarios o staff.\n\n"
            "➜ **TENER EN CUENTA**\n"
            "• El staff puede sancionar según gravedad.\n"
            "• Los canales tienen mensajes anclados.\n"
            "• Puedes acudir al equipo de staff.\n"
            "• Usa el sentido común.\n\n"
            "Si has leído todas las reglas, reacciona con **✅** para confirmar que las aceptas."
        ),
        color=0xffaa00
    )
    embed.set_image(url="https://i.pinimg.com/1200x/49/02/b2/4902b247b3797864c192454de45af835.jpg")
    msg = await ctx.send(embed=embed)
    await msg.add_reaction("✅")

# ---------------- Extra commands (fun / info / embed / poll) ----------------
@bot.command(name="8ball")
async def eight_ball(ctx, *, question: str = ""):
    answers = ["Sí.", "No.", "Tal vez.", "Definitivamente.", "Pregunta después.", "No puedo predecirlo."]
    if not question:
        return await ctx.reply("❓ Usa: `!8ball [pregunta]`", mention_author=False)
    await ctx.send(f"🎱 {random.choice(answers)}")

@bot.command(name="kiss")
async def kiss_cmd(ctx, member: discord.Member = None):
    if not member:
        return await ctx.reply("Menciona a alguien para besar: `!kiss @user`", mention_author=False)

    gifs = [
        "https://media.giphy.com/media/G3va31oEEnIkM/giphy.gif",
        "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExemdmbm1qdzgyMWRnejNyMndwb3VmZHE5dDNpdmdoOWQzY2k2NG03OCZlcD12MV9naWZzX3NlYXJjaCZjdD1n/11rWoZNpAKw8w/giphy.gif",
        "https://media.giphy.com/media/v1.Y2lkPWVjZjA1ZTQ3ZXRsZG5mOXhpMzJlZzJoZTg2NHZsbmplem5lOHM1eW9uejV1NDVydCZlcD12MV9naWZzX3NlYXJjaCZjdD1n/ZL0G3c9BDX9ja/giphy.gif",
        "https://media.giphy.com/media/hnNyVPIXgLdle/giphy.gif"
    ]

    embed = discord.Embed(
        title="💋 ¡Beso!",
        description=f"{ctx.author.mention} **le ha dado un beso a** {member.mention} 😳",
        color=0xff4d88
    )

    embed.set_image(url=random.choice(gifs))

    await ctx.send(embed=embed)


@bot.command(name="hug")
async def hug_cmd(ctx, member: discord.Member = None):
    if not member:
        return await ctx.reply("Menciona a alguien para abrazar: `!hug @user`", mention_author=False)

    gifs = [
        "https://media.giphy.com/media/l2QDM9Jnim1YVILXa/giphy.gif",
        "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExczU1bmliYnZuMjg0Z29jOWF2OHB0anJ0a3kzdm4xeDdvaWlzbTJwZCZlcD12MV9naWZzX3NlYXJjaCZjdD1n/42YlR8u9gV5Cw/giphy.gif",
        "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExdTV5Y2Nia2ZzdDJiczdrd2p5M21sYnhuNW5vODRtY2c2Znk0cnJqdCZlcD12MV9naWZzX3NlYXJjaCZjdD1n/Y8wCpaKI9PUBO/giphy.gif",
        "https://media.giphy.com/media/v1.Y2lkPWVjZjA1ZTQ3M2h1dnp1Zmp5Zml2YnlzbnkzNTk1a3BkYXN4YW1tOWMzcnlkcjEzMCZlcD12MV9naWZzX3NlYXJjaCZjdD1n/BXrwTdoho6hkQ/giphy.gif",
        "https://media.giphy.com/media/v1.Y2lkPWVjZjA1ZTQ3MTF3dmJyZ3Uwb2o0dDM1cGczNmwxc2lweWhzbGk5ZTlxYXgzZ2gybSZlcD12MV9naWZzX3NlYXJjaCZjdD1n/od5H3PmEG5EVq/giphy.gif",
        "https://media.giphy.com/media/v1.Y2lkPWVjZjA1ZTQ3MTF3dmJyZ3Uwb2o0dDM1cGczNmwxc2lweWhzbGk5ZTlxYXgzZ2gybSZlcD12MV9naWZzX3NlYXJjaCZjdD1n/f6y4qvdxwEDx6/giphy.gif",
        "https://media.giphy.com/media/v1.Y2lkPWVjZjA1ZTQ3MmhseDNubmpyYnZ0MGR0emp2eGx0OTVvcWN2YTU1bmVnbWFuN2x5ZyZlcD12MV9naWZzX3NlYXJjaCZjdD1n/FWBwZHGW2F0e4/giphy.gif",
        "https://media.giphy.com/media/od5H3PmEG5EVq/giphy.gif"
    ]

    # --- Si alguien abraza al bot ---
    if member.id == bot.user.id:
        embed_bot = discord.Embed(
            title="❤️ ¡Awww!",
            description=f"{ctx.author.mention} **l@ abraza de vuelta** 🤗",
            color=0x66ffcc
        )
        embed_bot.set_image(url=random.choice(gifs))
        return await ctx.send(embed=embed_bot)

    # --- Abrazos normales ---
    embed = discord.Embed(
        title="🤗 ¡Abrazo!",
        description=f"{ctx.author.mention} **abrazó fuertemente a** {member.mention} 🫂",
        color=0x66ccff
    )

    embed.set_image(url=random.choice(gifs))

    await ctx.send(embed=embed)


@bot.command(name="slap")
async def slap_cmd(ctx, member: discord.Member = None):
    if not member:
        return await ctx.reply("Menciona a alguien para pegar: `!slap @user`", mention_author=False)

    # GIFs para cuando el usuario pega a otro
    gifs_slap = [
        "https://media3.giphy.com/media/v1.Y2lkPTc5MGI3NjExN3JoZ3R1dG9peHV5a3N0aWl0aXdlMGs2dGRrbXk0bTl4cHdrYnljayZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/4R6EMXhNPz5WsJFEta/giphy.gif",
        "https://media.giphy.com/media/RXGNsyRb1hDJm/giphy.gif",
        "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExOGhrM3VjNDlyenUwZ2tiaG12ZmhmZHg4eW5rNW5xeHZjZzB5Yms4YyZlcD12MV9naWZzX3NlYXJjaCZjdD1n/DuVRadBbaX6A8/giphy.gif",
        "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExNnk2MGNlNXI5ZGF3eWZrMDBqMnBlOTJ6am55MXd6djJoN3RwOHpzciZlcD12MV9naWZzX3NlYXJjaCZjdD1n/Gf3AUz3eBNbTW/giphy.gif",
        "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExMDV1cWJoYmR2d2M5MDc4b2V5Yzc2a3ZvdGV1aXhvZnRmM2FhZG40eCZlcD12MV9naWZzX3NlYXJjaCZjdD1n/uqSU9IEYEKAbS/giphy.gif",
    ]

    # GIFs de contraataque del bot
    gifs_bot_counter = [
        "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExNnVzczc1bnY0aWZoa2ZpMWc0eTlwMGJuemFyOGpwNWR1NnNpZzc0eiZlcD12MV9naWZzX3NlYXJjaCZjdD1n/xIytx7kHpq74c/giphy.gif",
        "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExNnVzczc1bnY0aWZoa2ZpMWc0eTlwMGJuemFyOGpwNWR1NnNpZzc0eiZlcD12MV9naWZzX3NlYXJjaCZjdD1n/3oEduMlSdVYeI35kUo/giphy.gif",
        "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExZGJrdmE5Y3ZrcHZ6YmZucnl5ZjRsc3p2OTMwc2oybmZlMXJycHA0aCZlcD12MV9naWZzX3NlYXJjaCZjdD1n/dAC1oKY7OQzMQ/giphy.gif",
        "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExMXN0azFybWpyemRlZzFvZHFoeDZ5ZHFxZmNoYzRmYjZwaWt1ZG1wMiZlcD12MV9naWZzX3NlYXJjaCZjdD1n/bv7I7BKRBYOJLWoSlz/giphy.gif"
    ]

    # Si intentan pegarle al bot → contraataque
    if member.id == bot.user.id:
        embed = discord.Embed(
            title="💥 ¡*c enoja en robot*!",
            description=f"{ctx.author.mention}, ¿me pegaste? **¡te voy a violar!** 😠",
            color=0xff0000
        )
        embed.set_image(url=random.choice(gifs_bot_counter))
        return await ctx.send(embed=embed)

    # Slap normal entre usuarios
    embed = discord.Embed(
        title="👋 ¡TORTAZO!",
        description=f"{ctx.author.mention} **le pegó un tremendo cachetazo a** {member.mention} 😳",
        color=0xff6688
    )
    embed.set_image(url=random.choice(gifs_slap))
    
    await ctx.send(embed=embed)

from datetime import datetime, timedelta

@bot.command()
async def inactivos(ctx):
    await ctx.send("🔎 Buscando usuarios inactivos… esto puede tardar un poco.")

    limite = datetime.utcnow() - timedelta(days=14)
    ultima_actividad = {}

    # Revisa SOLO mensajes después del límite (mucho más rápido y no produce 429)
    async for msg in ctx.channel.history(after=limite, limit=None):
        if msg.author.bot:
            continue
        ultima_actividad[msg.author] = msg.created_at

    # Lista de usuarios inactivos
    inactivos = []
    for member in ctx.guild.members:
        if member.bot:
            continue

        # Nunca escribió recientemente
        if member not in ultima_actividad:
            inactivos.append(member)

    # Si no hay inactivos
    if not inactivos:
        return await ctx.send("✔ Todos han hablado en los últimos 14 días.")

    # Menciónalos
    lista_menciones = ", ".join(m.mention for m in inactivos)
    await ctx.send(f"⚠ Usuarios inactivos (+14 días):\n{lista_menciones}")


    # Respuesta
    if not inactivos:
        await ctx.send("✅ No hay usuarios inactivos (más de 2 semanas sin hablar).")
        return

@bot.command(name="informacion")
async def informacion_cmd(ctx, member: discord.Member = None):
    if not member:
        member = ctx.author
    joined = member.joined_at.strftime("%d/%m/%Y %H:%M:%S") if member.joined_at else "Desconocido"
    created = member.created_at.strftime("%d/%m/%Y %H:%M:%S")
    # messages count requeriría tracking; no contamos aquí (puedes implementar contador separado)
    warns = load_warns().get(str(member.id), [])
    embed = discord.Embed(title=f"Información de {member}", color=0x88ccff)
    embed.set_thumbnail(url=member.display_avatar.url if member.display_avatar else None)
    embed.add_field(name="ID", value=str(member.id))
    embed.add_field(name="Fecha de entrada", value=joined, inline=True)
    embed.add_field(name="Cuenta creada", value=created, inline=True)
    embed.add_field(name="Warns", value=str(len(warns)), inline=True)
    await ctx.send(embed=embed)

@bot.command(name="server")
async def server_cmd(ctx):
    guild = ctx.guild
    created = guild.created_at.strftime("%d/%m/%Y %H:%M:%S")
    members = guild.member_count
    embed = discord.Embed(title=f"Información de {guild.name}", color=0x88ccff)
    embed.add_field(name="Miembros", value=str(members))
    embed.add_field(name="Fecha de creación", value=created)
    embed.add_field(name="ID", value=str(guild.id))
    await ctx.send(embed=embed)

@bot.command(name="embed")
async def embed_cmd(ctx, title: str = None, *, description: str = None):
    # solo admins o superuser
    if ctx.author.id != SUPERUSER_ID and not ctx.author.guild_permissions.administrator:
        return await ctx.reply("❌ Solo administradores o SuperUser pueden usar este comando.", mention_author=False)
    if not title or not description:
        return await ctx.reply("Uso: `!embed \"Título\" \"Descripción\"`", mention_author=False)
    # permitir color hex opcional al final del description como #RRGGBB
    m = re.search(r"(#(?:[0-9a-fA-F]{6}))\s*$", description)
    color = 0x00ffcc
    if m:
        color = int(m.group(1).lstrip("#"), 16)
        description = description[:m.start()].strip()
    embed = discord.Embed(title=title, description=description, color=color)
    await ctx.send(embed=embed)

@bot.command(name="encuesta")
async def encuesta_cmd(ctx, *, rest: str = None):
    # usage: !encuesta Pregunta | opcion1 | opcion2 | opcion3 ...
    if not rest or "|" not in rest:
        return await ctx.reply("Uso: `!encuesta Pregunta | Opción1 | Opción2 | ...`", mention_author=False)
    parts = [p.strip() for p in rest.split("|") if p.strip()]
    pregunta = parts[0]
    opciones = parts[1:]
    if len(opciones) < 2 or len(opciones) > 10:
        return await ctx.reply("La encuesta necesita entre 2 y 10 opciones.", mention_author=False)
    description = ""
    emojis = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    for i, op in enumerate(opciones):
        description += f"{emojis[i]} {op}\n"
    embed = discord.Embed(title=f"📊 {pregunta}", description=description, color=0x99ccff)
    msg = await ctx.send(embed=embed)
    for i in range(len(opciones)):
        await msg.add_reaction(emojis[i])

# ---------------- Events & errors ----------------
@bot.event
async def on_ready():
    logger.info(f"Bot listo! Conectado como {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="Preparando Femb-Paradise"))

@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("❌ Falta un argumento requerido.", mention_author=False)
    elif isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.CheckFailure):
        await ctx.reply("❌ No tienes permisos para usar este comando.", mention_author=False)
    else:
        logger.exception("Error en comando: %s", error)
        try:
            await ctx.reply(f"❌ Ocurrió un error: `{error}`", mention_author=False)
        except Exception:
            pass

# ---------------- Run ----------------
if __name__ == "__main__":
    bot.run(TOKEN)


   


