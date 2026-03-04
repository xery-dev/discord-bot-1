import discord
from discord.ext import commands, tasks
import asyncio
import json
import os
from datetime import datetime, timedelta

# --- VERİ YÖNETİMİ ---
DATA_FILE = "server_management.json"


def load_db():
    if not os.path.exists(DATA_FILE):
        return {"users": {}, "guild_settings": {}, "stats": {"total_actions": 0}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

class AdminSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.spam_control = {}
        self.link_tag = "link"  # Link paylaşımı için gereken tag/rol ismi

    def create_embed(self, title, description, color=discord.Color.blue(), footer="Elite Management System"):


        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=footer, icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)

        return embed


    # --- MODERASYON: ANTISPAM & LINK GUARD ---
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return


        # 1. ULTRA LINK GUARD
        forbidden_links = ["http", "www.", ".com", ".net", ".org", "discord.gg"]
        if any(x in message.content.lower() for x in forbidden_links):
            # "link" permi kontrolü (Rol ismi veya perm kontrolü)
            has_link_perm = any(role.name.lower() == self.link_tag for role in message.author.roles)
            if not has_link_perm and not message.author.guild_permissions.administrator:
                await message.delete()
                warning = await message.channel.send(
                    embed=self.create_embed(
                        "⚠️ ERİŞİM ENGELİ", 
                        f"{message.author.mention}, link paylaşmak için gerekli yetkiye (`{self.link_tag}`) sahip değilsiniz!",
                        discord.Color.red()
                    )
                )
                await asyncio.sleep(4)
                return await warning.delete()


        # 2. PRO-LEVEL ANTI-SPAM
        user_id = message.author.id
        now = datetime.now()


        if user_id not in self.spam_control:
            self.spam_control[user_id] = []


        self.spam_control[user_id].append(now)
        # 5 saniye içindeki mesajları filtrele
        self.spam_control[user_id] = [t for t in self.spam_control[user_id] if (now - t).total_seconds() < 5]


        if len(self.spam_control[user_id]) > 5:
            if not message.author.guild_permissions.manage_messages:
                await message.channel.purge(limit=5, check=lambda m: m.author == message.author)
                try:
                    await message.author.timeout(timedelta(minutes=5), reason="Spam Filtresi")
                    embed = self.create_embed(
                        "🛡️ ANTİ-SPAM SİSTEMİ",
                        f"{message.author.mention} aşırı hızlı mesaj gönderdiği için **5 dakika** susturuldu.",
                        discord.Color.dark_red()
                    )
                    await message.channel.send(embed=embed)
                except:
                    pass
  
# --- GELİŞMİŞ KADEMELİ UYARI SİSTEMİ (ROLLÜ) ---
    @commands.command(name="warn", aliases=["uyar"])
    @commands.has_permissions(manage_messages=True)
    async def warn_user(self, ctx, member: discord.Member, *, reason="Kural İhlali"):
        if member.top_role >= ctx.author.top_role:
            return await ctx.send(embed=self.create_embed("❌ HATA", "Sizden üstte veya aynı roldeki birini uyaramazsınız!", discord.Color.red()))


        db = load_db()
        u_id = str(member.id)
        g_id = str(ctx.guild.id)


        if u_id not in db["users"]:
            db["users"][u_id] = {"warns": 0, "history": []}


        db["users"][u_id]["warns"] += 1
        warn_count = db["users"][u_id]["warns"]


        # Sicil Kaydı Detaylandırma
        log_entry = {
            "action": f"WARN {warn_count}",
            "reason": reason,
            "staff_id": ctx.author.id,
            "staff_name": str(ctx.author),
            "date": datetime.now().strftime("%d/%m/%Y %H:%M")
        }
        db["users"][u_id]["history"].append(log_entry)
        save_db(db)


        # --- KADEMELİ ROL VE CEZA MOTORU ---
        status_update = "İşlem Başarılı."


        # Her seviye için rol verme (Önceki warn rollerini temizlemez, üst üste biner)
        role_name = f"warn {warn_count}"
        target_role = discord.utils.get(ctx.guild.roles, name=role_name)


        if target_role:
            await member.add_roles(target_role)
            status_update = f"`{role_name}` rolü başarıyla tanımlandı."
        else:
            status_update = f"⚠️ `{role_name}` isimli bir rol sunucuda bulunamadı!"


        # Özel Eylem Tetikleyicileri
        if warn_count == 3:
            try:
                await member.timeout(timedelta(minutes=1), reason="3. Uyarı Sınırı")
                status_update += "\n⏳ **3. Uyarı:** 1 Dakika Mute atıldı."
            except:
                status_update += "\n❌ Mute atılamadı (Yetki yetersiz)."


        if warn_count >= 5:
            status_update += "\n🚨 **5. Uyarı:** Kritik seviye ulaşıldı!"
            log_ch = discord.utils.get(ctx.guild.channels, name="uyarı-log")
            if log_ch:
                alert_embed = self.create_embed(
                    "🚨 ÜST DÜZEY UYARI BİLDİRİMİ", 
                    f"**Kullanıcı:** {member.mention}\n**Durum:** 5. Uyarı (Kritik)\n**Son Sebep:** {reason}", 
                    discord.Color.dark_red()
                )
                await log_ch.send(embed=alert_embed)


        # Şık Onay Embed
        embed = self.create_embed("🛡️ MODERASYON İŞLEMİ", "Kullanıcıya ceza puanı ve rolü tanımlandı.", discord.Color.gold())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="👤 Kullanıcı", value=f"{member.mention}\n`ID: {member.id}`", inline=True)
        embed.add_field(name="👮 Yetkili", value=f"{ctx.author.mention}\n`İşlem No: #{len(db['users'][u_id]['history'])}`", inline=True)
        embed.add_field(name="📈 Güncel Uyarı", value=f"**{warn_count} / 5**", inline=False)
        embed.add_field(name="📜 İşlem Detayı", value=f"**{status_update}**", inline=False)
        embed.add_field(name="📄 Son Sebep", value=f"*{reason}*", inline=False)


        await ctx.send(embed=embed)


    # --- SİCİL GÖRÜNTÜLEME ---
    @commands.command(name="sicil", aliases=["records"])
    async def view_sicil(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        db = load_db()
        u_id = str(member.id)


        if u_id not in db["users"] or not db["users"][u_id]["history"]:
            return await ctx.send(embed=self.create_embed("📂 SİCİL TEMİZ", f"{member.mention} kullanıcısına ait geçmiş kayıt bulunamadı.", discord.Color.green()))


        history = db["users"][u_id]["history"]
        embed = self.create_embed(f"📂 {member.display_name} - Ceza Geçmişi", f"Toplam {len(history)} kayıt bulundu.", discord.Color.blue())


        # Son 10 kaydı göster (Embed sınırı için)
        for i, entry in enumerate(history[-10:], 1):
            embed.add_field(
                name=f"#{i} - {entry['action']}",
                value=f"📅 **Tarih:** {entry['date']}\n👮 **Yetkili:** {entry['staff_name']}\n📝 **Sebep:** {entry['reason']}",
                inline=False
            )


        await ctx.send(embed=embed)


    # --- UYARI SIFIRLAMA (ADMIN ONLY) ---
    @commands.command(name="unwarn", aliases=["uyarısil"])
    @commands.has_permissions(administrator=True)
    async def unwarn_user(self, ctx, member: discord.Member):
        db = load_db()
        u_id = str(member.id)


        if u_id in db["users"] and db["users"][u_id]["warns"] > 0:
            current_warn = db["users"][u_id]["warns"]
            # Rolü geri alma
            role_name = f"warn {current_warn}"
            role = discord.utils.get(ctx.guild.roles, name=role_name)
            if role: await member.remove_roles(role)


            db["users"][u_id]["warns"] -= 1
            save_db(db)
            await ctx.send(embed=self.create_embed("✨ UYARI SİLİNDİ", f"{member.mention} kullanıcısının bir uyarısı kaldırıldı.", discord.Color.green()))
        else:
            await ctx.send("Kullanıcının zaten uyarısı yok.")
# --- YETKİLİ İSTATİSTİK SİSTEMİ ---
    @commands.command(name="istatistik", aliases=["stat", "yetkilistat"])
    @commands.has_permissions(manage_messages=True)
    async def staff_stats(self, ctx, staff: discord.Member = None):
        staff = staff or ctx.author
        db = load_db()


        count = 0
        actions = []


        # Tüm kullanıcıların geçmişinde bu yetkiliyi ara
        for user_id in db["users"]:
            for entry in db["users"][user_id]["history"]:
                if str(entry.get("staff_id")) == str(staff.id):
                    count += 1
                    actions.append(f"• {entry['action']} (Kullanıcı ID: {user_id})")


        embed = self.create_embed(f"📊 Yetkili Performans: {staff.display_name}", "", discord.Color.purple())
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="✅ Toplam İşlem", value=f"`{count}`", inline=True)
        embed.add_field(name="🎖️ Rütbe", value=staff.top_role.mention, inline=True)


        # Son 5 işlemi listele
        recent_actions = "\n".join(actions[-5:]) if actions else "Henüz işlem kaydı yok."
        embed.add_field(name="📜 Son İşlemler", value=recent_actions, inline=False)


        await ctx.send(embed=embed)


    # --- OWNER ÖZEL PANEL (GELİŞMİŞ) ---
    @commands.command(name="panel", aliases=["adminpanel", "owner"])
    @commands.has_permissions(administrator=True)
    async def owner_panel(self, ctx):
        db = load_db()
        total_warns = sum(u["warns"] for u in db["users"].values())
        total_users_recorded = len(db["users"])


        embed = discord.Embed(
            title="👑 Üst Düzey Yönetim Paneli",
            description="Sunucu genelindeki tüm modülasyon verileri ve sistem durumu.",
            color=discord.Color.from_rgb(43, 45, 49), # Modern koyu renk
            timestamp=datetime.utcnow()

        )

        embed.add_field(name="📊 Genel Veriler", value=(
            f"**Kayıtlı Sabıkalı:** `{total_users_recorded}`\n"
            f"**Aktif Uyarı Sayısı:** `{total_warns}`\n"
            f"**Sistem Durumu:** `Aktif 🟢`"
        ), inline=True)


        embed.add_field(name="🛡️ Güvenlik Filtreleri", value=(
            "**Anti-Spam:** `Açık` (5msj/5sn)\n"
            "**Link Engel:** `Açık` (Sadece `link` permi)\n"
            "**Sicil Kaydı:** `Aktif`"
        ), inline=True)


        # Sunucu Teknik Bilgi
        embed.add_field(name="🖥️ Sunucu Bilgisi", value=(
            f"**Üye Sayısı:** {ctx.guild.member_count}\n"
            f"**Rol Sayısı:** {len(ctx.guild.roles)}\n"
            f"**Kanal Sayısı:** {len(ctx.guild.channels)}"
        ), inline=False)


        embed.set_footer(text=f"Sistem Komut Prefixi: {ctx.prefix}")
        embed.set_image(url="https://i.imgur.com/uGzH8v8.png") # Opsiyonel: Şık bir divider/banner


        await ctx.send(embed=embed)


    # --- ÖZEL TEMİZLİK KOMUTU (PROFESYONEL) ---
    @commands.command(name="clear", aliases=["sil", "purge"])
    @commands.has_permissions(manage_messages=True)
    async def clear_messages(self, ctx, amount: int = 10):
        if amount > 100: amount = 100
        deleted = await ctx.channel.purge(limit=amount + 1)


        embed = self.create_embed(
            "🧹 Temizlik Tamamlandı", 
            f"**{len(deleted)-1}** mesaj başarıyla imha edildi.", 
            discord.Color.light_grey()
        )
        msg = await ctx.send(embed=embed)
        await asyncio.sleep(3)
        await msg.delete()

    # --- SİSTEM AYARLARI (LİNK PERMİ DEĞİŞTİRME) ---
    @commands.command(name="linkayarla")
    @commands.has_permissions(administrator=True)
    async def set_link_tag(self, ctx, new_tag: str):
        self.link_tag = new_tag.lower()
        await ctx.send(embed=self.create_embed("⚙️ Ayar Güncellendi", f"Artık link paylaşmak için gereken rol/tag: `{new_tag}`", discord.Color.green()))


# --- DOSYA SONUNA EKLEME ---

async def setup(bot):
    await bot.add_cog(AdminSystem(bot))
