import discord
from discord.ext import commands, tasks
import aiosqlite
import asyncio
import re
from datetime import datetime, timedelta

DATABASE = "admin_system.db"
PREFIX = "!"
WARN_CHANNEL_ID = 123456789012345678  # UYARI KANALI
MUTED_ROLE_NAME = "Muted"
LINK_PERMISSION_ROLE = "link"

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.spam_cache = {}
        self.link_regex = re.compile(r"(https?://|www\.)")

    # ================= DATABASE =================

    async def init_db(self):
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute("""
            CREATE TABLE IF NOT EXISTS warns (
                user_id INTEGER,
                guild_id INTEGER,
                warn_count INTEGER DEFAULT 0
            )
            """)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS records (
                user_id INTEGER,
                guild_id INTEGER,
                moderator_id INTEGER,
                reason TEXT,
                date TEXT
            )
            """)
            await db.commit()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.init_db()
        print("Admin sistemi aktif.")

    # ================= EMBED FACTORY =================

    def embed_template(self, title, description, color=0x2f3136):
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="Advanced Moderation System")
        return embed

    # ================= ANTISPAM =================

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        # Anti Spam
        user_id = message.author.id
        now = datetime.utcnow()

        if user_id not in self.spam_cache:
            self.spam_cache[user_id] = []

        self.spam_cache[user_id].append(now)

        self.spam_cache[user_id] = [
            t for t in self.spam_cache[user_id]
            if (now - t).seconds < 5
        ]

        if len(self.spam_cache[user_id]) >= 6:
            await message.delete()
            await self.add_warn(message.guild, message.author, None, "Spam tespit edildi.")
            return

        # Link Protection
        if self.link_regex.search(message.content):
            if not any(role.name == LINK_PERMISSION_ROLE for role in message.author.roles):
                await message.delete()
                embed = self.embed_template(
                    "🔗 Link Engellendi",
                    "Link paylaşmak için gerekli role sahip değilsin.",
                    0xff0000
                )
                await message.channel.send(embed=embed, delete_after=5)

        await self.bot.process_commands(message)

    # ================= WARN CORE =================

    async def get_warn(self, guild_id, user_id):
        async with aiosqlite.connect(DATABASE) as db:
            cursor = await db.execute(
                "SELECT warn_count FROM warns WHERE user_id=? AND guild_id=?",
                (user_id, guild_id)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def set_warn(self, guild_id, user_id, amount):
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute("""
            INSERT INTO warns (user_id, guild_id, warn_count)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, guild_id)
            DO UPDATE SET warn_count=?
            """, (user_id, guild_id, amount, amount))
            await db.commit()

    async def add_record(self, guild_id, user_id, moderator_id, reason):
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute("""
            INSERT INTO records (user_id, guild_id, moderator_id, reason, date)
            VALUES (?, ?, ?, ?, ?)
            """, (user_id, guild_id, moderator_id if moderator_id else 0, reason, datetime.utcnow().isoformat()))
            await db.commit()

    async def add_warn(self, guild, user, moderator, reason):
        current = await self.get_warn(guild.id, user.id)
        new_warn = current + 1
        await self.set_warn(guild.id, user.id, new_warn)
        await self.add_record(guild.id, user.id, moderator.id if moderator else 0, reason)

        await self.handle_warn_actions(guild, user, new_warn)

    # ================= WARN ACTION SYSTEM =================

    async def handle_warn_actions(self, guild, user, warn_count):
        muted_role = discord.utils.get(guild.roles, name=MUTED_ROLE_NAME)

        if warn_count == 1:
            role = discord.utils.get(guild.roles, name="warn 1")
            if role:
                await user.add_roles(role)

        if warn_count == 3:
            if muted_role:
                await user.add_roles(muted_role)
                await asyncio.sleep(60)
                await user.remove_roles(muted_role)

        if warn_count == 5:
            channel = guild.get_channel(WARN_CHANNEL_ID)
            if channel:
                embed = self.embed_template(
                    "⚠️ Kritik Uyarı",
                    f"{user.mention} kullanıcısı 5 warn seviyesine ulaştı.",
                    0xff9900
                )
                await channel.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Admin(bot))
        # ================= PERMISSION CHECK =================

    async def is_admin(self, ctx):
        return ctx.author.guild_permissions.administrator

    # ================= WARN COMMAND =================

    @commands.command(name="warn")
    async def warn_command(self, ctx, member: discord.Member, *, reason="Sebep belirtilmedi"):
        if not await self.is_admin(ctx):
            return await ctx.send(embed=self.embed_template(
                "❌ Yetki Hatası",
                "Bu komutu kullanmak için yönetici olmalısın.",
                0xff0000
            ))

        await self.add_warn(ctx.guild, member, ctx.author, reason)
        warn_count = await self.get_warn(ctx.guild.id, member.id)

        embed = self.embed_template(
            "⚠️ Kullanıcı Uyarıldı",
            f"{member.mention} kullanıcısı uyarıldı.",
            0xffcc00
        )
        embed.add_field(name="Toplam Warn", value=str(warn_count))
        embed.add_field(name="Sebep", value=reason)
        embed.add_field(name="Yetkili", value=ctx.author.mention)

        await ctx.send(embed=embed)

    # ================= REMOVE WARN =================

    @commands.command(name="removewarn")
    async def remove_warn(self, ctx, member: discord.Member, amount: int):
        if not await self.is_admin(ctx):
            return

        current = await self.get_warn(ctx.guild.id, member.id)
        new_warn = max(current - amount, 0)
        await self.set_warn(ctx.guild.id, member.id, new_warn)

        embed = self.embed_template(
            "🧹 Warn Silindi",
            f"{member.mention} kullanıcısının warn sayısı güncellendi.",
            0x00ff99
        )
        embed.add_field(name="Yeni Warn", value=str(new_warn))

        await ctx.send(embed=embed)

    # ================= RESET WARN =================

    @commands.command(name="resetwarn")
    async def reset_warn(self, ctx, member: discord.Member):
        if not await self.is_admin(ctx):
            return

        await self.set_warn(ctx.guild.id, member.id, 0)

        embed = self.embed_template(
            "♻️ Warn Sıfırlandı",
            f"{member.mention} kullanıcısının tüm warnları temizlendi.",
            0x0099ff
        )

        await ctx.send(embed=embed)

    # ================= SICIL =================

    @commands.command(name="sicil")
    async def sicil(self, ctx, member: discord.Member):
        async with aiosqlite.connect(DATABASE) as db:
            cursor = await db.execute("""
            SELECT moderator_id, reason, date
            FROM records
            WHERE user_id=? AND guild_id=?
            ORDER BY date DESC
            """, (member.id, ctx.guild.id))
            rows = await cursor.fetchall()

        warn_count = await self.get_warn(ctx.guild.id, member.id)

        embed = self.embed_template(
            "📜 Kullanıcı Sicili",
            f"{member.mention} kullanıcısının detaylı sicili",
            0x5865F2
        )
        embed.add_field(name="Toplam Warn", value=str(warn_count), inline=False)

        if not rows:
            embed.add_field(name="Kayıt", value="Temiz sicil.", inline=False)
        else:
            for i, row in enumerate(rows[:10], start=1):
                moderator = ctx.guild.get_member(row[0])
                moderator_name = moderator.mention if moderator else "Bilinmiyor"
                embed.add_field(
                    name=f"#{i}",
                    value=f"👮 {moderator_name}\n📌 {row[1]}\n🕒 {row[2]}",
                    inline=False
                )

        await ctx.send(embed=embed)

    # ================= ADMIN PANEL =================

    @commands.command(name="adminpanel")
    async def admin_panel(self, ctx):
        if not await self.is_admin(ctx):
            return

        embed = self.embed_template(
            "🎛️ Admin Kontrol Paneli",
            "Sunucu yönetim komutları aşağıda listelenmiştir.",
            0x2ecc71
        )

        embed.add_field(
            name="⚠️ Moderasyon",
            value="""
`!warn @kullanıcı sebep`
`!removewarn @kullanıcı sayı`
`!resetwarn @kullanıcı`
`!sicil @kullanıcı`
""",
            inline=False
        )

        embed.add_field(
            name="🛡️ Güvenlik",
            value="""
Anti-Spam aktif
Link Koruma aktif
Warn escalation aktif
""",
            inline=False
        )

        embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else discord.Embed.Empty)

        await ctx.send(embed=embed)
            # ================= AUTO ROLE SETUP =================

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.ensure_roles(guild)

    async def ensure_roles(self, guild):
        muted_role = discord.utils.get(guild.roles, name=MUTED_ROLE_NAME)
        if not muted_role:
            muted_role = await guild.create_role(
                name=MUTED_ROLE_NAME,
                reason="Auto-created mute role"
            )

            for channel in guild.channels:
                await channel.set_permissions(
                    muted_role,
                    send_messages=False,
                    speak=False,
                    add_reactions=False
                )

        warn1_role = discord.utils.get(guild.roles, name="warn 1")
        if not warn1_role:
            await guild.create_role(name="warn 1", reason="Warn 1 Role")

    # ================= SMART WARN DECAY =================

    @tasks.loop(minutes=30)
    async def warn_decay_task(self):
        async with aiosqlite.connect(DATABASE) as db:
            cursor = await db.execute("SELECT user_id, guild_id, warn_count FROM warns")
            rows = await cursor.fetchall()

            for user_id, guild_id, warn_count in rows:
                if warn_count > 0:
                    new_warn = warn_count - 1
                    await db.execute("""
                    UPDATE warns
                    SET warn_count=?
                    WHERE user_id=? AND guild_id=?
                    """, (new_warn, user_id, guild_id))

            await db.commit()

    @warn_decay_task.before_loop
    async def before_warn_decay(self):
        await self.bot.wait_until_ready()

    # ================= ADVANCED ANTISPAM =================

    async def advanced_spam_check(self, message):
        user_id = message.author.id
        now = datetime.utcnow()

        if user_id not in self.spam_cache:
            self.spam_cache[user_id] = []

        self.spam_cache[user_id].append(now)

        window = 7
        threshold = 8

        self.spam_cache[user_id] = [
            t for t in self.spam_cache[user_id]
            if (now - t).seconds < window
        ]

        if len(self.spam_cache[user_id]) >= threshold:
            await message.delete()
            await self.add_warn(message.guild, message.author, None, "Advanced spam detection.")
            return True

        return False

    # ================= SYSTEM LOGGER =================

    async def system_log(self, guild, title, description):
        channel = guild.get_channel(WARN_CHANNEL_ID)
        if channel:
            embed = self.embed_template(title, description, 0x95a5a6)
            await channel.send(embed=embed)

    # ================= RATE LIMIT PROTECTION =================

    command_usage = {}

    @commands.Cog.listener()
    async def on_command(self, ctx):
        user_id = ctx.author.id
        now = datetime.utcnow()

        if user_id not in self.command_usage:
            self.command_usage[user_id] = []

        self.command_usage[user_id].append(now)

        self.command_usage[user_id] = [
            t for t in self.command_usage[user_id]
            if (now - t).seconds < 10
        ]

        if len(self.command_usage[user_id]) > 10:
            await ctx.send(embed=self.embed_template(
                "🚫 Rate Limit",
                "Çok hızlı komut kullanıyorsun. Lütfen yavaşla.",
                0xff0000
            ))
            raise commands.CommandOnCooldown(
                ctx.command._buckets,
                10,
                commands.BucketType.user
            )

    # ================= SYSTEM HEALTH =================

    @commands.command(name="sistem")
    async def system_status(self, ctx):
        embed = self.embed_template(
            "🖥️ Sistem Durumu",
            "Bot stabil şekilde çalışıyor.",
            0x1abc9c
        )

        embed.add_field(name="Latency", value=f"{round(self.bot.latency * 1000)}ms")
        embed.add_field(name="Sunucu Sayısı", value=str(len(self.bot.guilds)))
        embed.add_field(name="Aktif Kullanıcı Cache", value=str(len(self.spam_cache)))

        await ctx.send(embed=embed)

    # ================= START BACKGROUND TASK =================

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.warn_decay_task.is_running():
            self.warn_decay_task.start()
        print("Professional upgrade aktif.")
