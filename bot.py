# === Red Louisiana RP — Bot utilitaires (Cartes, Économie, Sessions RP) ===
# /ping • /style_carte • /generer_carte • /afficher_carte • /fiche_personnage • /bal • /coma
# Économie: /add_money • /remove_money • /crime • /robb • /blanchiment • /leaderboard
# Inventaire: /add_armes • /remove_armes • /add_horse • /remove_horse • /add_property • /remove_property
# Permis: /add_permit • /remove_permit
# Outils: /sync
# Sessions RP: /session (embed + boutons + modale "retard", @everyone auto)

import os, io, asyncio, mimetypes, json, time, random, math, zipfile
from typing import Optional, Dict, List, Tuple
from datetime import datetime
from zoneinfo import ZoneInfo

PARIS_TZ = ZoneInfo("Europe/Paris")


import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

# ---------- Pillow ----------
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

# ---------- Chemins ----------
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
CARDS_DIR  = os.path.join(BASE_DIR, "cards")
PROFILES_DIR = os.path.join(BASE_DIR, "profiles")
os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs(CARDS_DIR,  exist_ok=True)
os.makedirs(PROFILES_DIR, exist_ok=True)

# ---------- Sauvegardes automatiques ----------
# Salon #backup-louisiana
BACKUP_CHANNEL_ID = 1440672653294960650

# Dossiers qui contiennent les données importantes du bot
BACKUP_PATHS = [
    CARDS_DIR,
    PROFILES_DIR,
]

FONT_PATH  = os.path.join(ASSETS_DIR, "EBGaramond-Regular.ttf")  # optionnel
WM_PATH    = os.path.join(ASSETS_DIR, "armoiries.png")           # image d'armoiries
WM_OPACITY = 70

# ---------- .env ----------
load_dotenv()
TOKEN    = os.getenv("TOKEN")
GUILD_ID = os.getenv("GUILD_ID")

# ---------- Keep-alive POUR RENDER UNIQUEMENT ----------
import threading
try:
    from flask import Flask
except Exception:
    Flask = None  # si Flask n'est pas installé en local

def _start_keepalive_if_needed():
    # Sur Render, la variable d'env PORT est présente.
    port = os.environ.get("PORT")
    if not port or not Flask:
        return

    app = Flask(__name__)

    @app.get("/")
    def _health():
        return "bot alive"

    def _run():
        app.run(host="0.0.0.0", port=int(port))

    threading.Thread(target=_run, daemon=True).start()

_start_keepalive_if_needed()

# ---------- Bot ----------
intents = discord.Intents.default()
# NÉCESSAIRE pour recevoir on_member_remove (purge des données à la sortie)
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

def embed(t: str, d: str=""):
    return discord.Embed(title=t, description=d, color=discord.Color.dark_gold())

# ---------- Tâche de sauvegarde automatique vers Discord ----------

def build_backup_bytes() -> io.BytesIO:
    """Crée un ZIP en mémoire avec les cartes + profils."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in BACKUP_PATHS:
            if not os.path.exists(path):
                continue
            if os.path.isdir(path):
                for root, dirs, files in os.walk(path):
                    for fname in files:
                        full = os.path.join(root, fname)
                        # on enregistre un chemin relatif propre dans le zip
                        arcname = os.path.relpath(full, BASE_DIR)
                        z.write(full, arcname)
            else:
                arcname = os.path.relpath(path, BASE_DIR)
                z.write(path, arcname)
    buf.seek(0)
    return buf

@tasks.loop(minutes=60)  # une sauvegarde toutes les heures
async def auto_backup():
    """Envoie régulièrement un ZIP des données dans #backup-louisiana."""
    if BACKUP_CHANNEL_ID == 0:
        return

    channel = bot.get_channel(BACKUP_CHANNEL_ID)
    if channel is None:
        # si le cache n'est pas encore prêt, on attend le prochain tour
        return

    buf = build_backup_bytes()
    ts = datetime.utcnow().strftime("%Y-%m-%d_%H-%M")
    await channel.send(
        content=f"Backup automatique Red Louisiana — {ts} (UTC)",
        file=discord.File(buf, filename=f"backup_red_louisiana_{ts}.zip"),
        allowed_mentions=discord.AllowedMentions.none(),
    )

@auto_backup.before_loop
async def before_auto_backup():
    await bot.wait_until_ready()

# ---------- Paramètres carte ----------
CANVAS_W, CANVAS_H = 1600, 1000
THEMES = {
    "classique": {"parchment": (239,232,220), "panel": (186,170,154), "frame": (120,100,70), "ink": (45,45,45), "subtitle": (60,60,60)},
    "sobre":     {"parchment": (246,243,240), "panel": (210,205,196), "frame": (100,100,100), "ink": (30,30,30), "subtitle": (50,50,50)},
    "fonce":     {"parchment": (226,220,210), "panel": (130,118,104), "frame": (80,70,60),  "ink": (25,25,25), "subtitle": (40,40,40)},
}
CURRENT_THEME = {"name": "classique"}

LAYOUT = {
    "margin": 26,
    "header_h": 145,
    "photo_box": (1030, 185, 460, 520),
    "sign": { "x": 1030, "y": 735, "w": 460, "h": 150 },
    "title_pos_y": 40,
    "subtitle_pos": (90, 240),
    "labels_x": 120,
    "values_x": 420,
    "first_row_y": 360,
    "row_step": 80,
    "font_title": 84,
    "font_subtitle": 42,
    "font_label": 35,
    "font_value": 35,
    "font_job_label": 30,
    "font_job_value": 38,
}

# ---------- Fonts ----------
def _font(size: int) -> "ImageFont.FreeTypeFont":
    if not PIL_AVAILABLE:
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()

# ---------- Cartes : helpers dessin ----------
def _draw_parchment(draw: "ImageDraw.ImageDraw", theme: dict, W: int, H: int):
    draw.rectangle([0,0, W, H], fill=theme["parchment"])
    m = LAYOUT["margin"]
    draw.rectangle([m, m, W-m, H-m], outline=theme["frame"], width=4)
    header_h = LAYOUT["header_h"]
    draw.rectangle([m, m, W-m, m+header_h], fill=theme["panel"])

def _paste_cover(bg: "Image.Image", img: "Image.Image", x: int, y: int, w: int, h: int):
    sw, sh = img.size
    scale = max(w/sw, h/sh)
    new_w, new_h = int(sw*scale), int(sh*scale)
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - w)//2; top = (new_h - h)//2
    cropped = resized.crop((left, top, left+w, top+h))
    bg.paste(cropped, (x, y), cropped.convert("RGBA"))

def _paste_with_opacity(bg: "Image.Image", overlay: "Image.Image", x: int, y: int, opacity: int):
    overlay = overlay.convert("RGBA")
    if opacity < 255:
        r,g,b,a = overlay.split()
        a = a.point(lambda p: p * opacity // 255)
        overlay.putalpha(a)
    bg.paste(overlay, (x, y), overlay)

def _compose_id_card(data: dict, style_name: str="classique") -> "Image.Image":
    theme = THEMES.get(style_name, THEMES["classique"])
    W, H = CANVAS_W, CANVAS_H
    from PIL import Image, ImageDraw  # sûreté
    img = Image.new("RGBA", (W, H), theme["parchment"])
    draw = ImageDraw.Draw(img)

    _draw_parchment(draw, theme, W, H)

    # Armoiries en bas-gauche (redimensionnées)
    if os.path.exists(WM_PATH):
        try:
            wm = Image.open(WM_PATH).convert("RGBA")
            wm = wm.resize((int(wm.width * 0.42), int(wm.height * 0.42)), Image.LANCZOS)
            wm_x = 85
            wm_y = H - 6 - wm.height
            _paste_with_opacity(img, wm, wm_x, wm_y, WM_OPACITY)
        except Exception:
            pass

    # Cadres
    px, py, pw, ph = LAYOUT["photo_box"]
    draw.rectangle([px, py, px+pw, py+ph], outline=theme["frame"], width=5)
    s = LAYOUT["sign"]
    draw.rectangle([s["x"], s["y"], s["x"]+s["w"], s["y"]+s["h"]], outline=theme["frame"], width=5)

    # Titres
    ft  = _font(LAYOUT["font_title"])
    fst = _font(LAYOUT["font_subtitle"])
    title_text = "ROYAUME DE FRANCE"
    try:
        bbox = draw.textbbox((0,0), title_text, font=ft)
        title_w = bbox[2]-bbox[0]
    except Exception:
        title_w, _ = draw.textsize(title_text, font=ft)
    title_x = (W - title_w) // 2
    title_y = LAYOUT["title_pos_y"]
    draw.text((title_x, title_y), title_text, fill=theme["ink"], font=ft)
    draw.text(LAYOUT["subtitle_pos"], "CARTE D’IDENTITÉ", fill=theme["subtitle"], font=fst)

    # Libellés
    fl = _font(LAYOUT["font_label"])
    labels = ["Prénom", "Nom", "Titre(s)", "Genre", "Date de naissance", "Lieu de naissance", "Nationalité"]
    y = LAYOUT["first_row_y"]
    for lab in labels:
        draw.text((LAYOUT["labels_x"], y), lab, fill=theme["ink"], font=fl)
        y += LAYOUT["row_step"]

    # Valeurs
    fv = _font(LAYOUT["font_value"])
    values = [
        data.get("prenom", "—"),
        data.get("nom", "—"),
        data.get("titres", "—"),
        data.get("genre", "—"),
        data.get("date_naissance", "—"),
        data.get("lieu_naissance", "—"),
        data.get("nationalite", "—"),
    ]
    y = LAYOUT["first_row_y"]
    for val in values:
        draw.text((LAYOUT["values_x"], y), str(val), fill=theme["ink"], font=fv)
        y += LAYOUT["row_step"]

    # Photo
    photo_path = data.get("photo_path")
    if photo_path and os.path.exists(photo_path):
        try:
            src = Image.open(photo_path).convert("RGBA")
            _paste_cover(img, src, px, py, pw, ph)
        except Exception:
            pass

    # Métier
    job_label_font = _font(LAYOUT["font_job_label"])
    job_value_font = _font(LAYOUT["font_job_value"])
    metier = str(data.get("metier", "—"))
    draw.text((s["x"]+12, s["y"]+8), "Métier", fill=theme["subtitle"], font=job_label_font)
    try:
        jb = draw.textbbox((0,0), metier, font=job_value_font)
        jw, jh = jb[2]-jb[0], jb[3]-jb[1]
    except Exception:
        jw, jh = draw.textsize(metier, font=job_value_font)
    jx = s["x"] + (s["w"]-jw)//2
    jy = s["y"] + (s["h"]-jh)//2 + 10
    draw.text((jx, jy), metier, fill=theme["ink"], font=job_value_font)

    return img

def generate_png_bytes(data: dict, style_name: str="classique") -> bytes:
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow n'est pas installé (pip install Pillow).")
    from io import BytesIO
    card = _compose_id_card(data, style_name=style_name)
    bio = BytesIO(); card.save(bio, "PNG"); bio.seek(0)
    return bio.read()

def card_path_for(user_id: int) -> str:
    return os.path.join(CARDS_DIR, f"{user_id}.png")

def profile_path_for(user_id: int) -> str:
    return os.path.join(PROFILES_DIR, f"{user_id}.json")

def load_profile(user_id: int) -> Optional[dict]:
    p = profile_path_for(user_id)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None

def save_profile(user_id: int, data: dict) -> None:
    """Enregistre/merge la fiche. Conserve inventaires, propriétés et argent s’ils existent."""
    p = profile_path_for(user_id)
    existing = load_profile(user_id) or {}
    ex_inv   = existing.get("inventaire", {})
    armes    = ex_inv.get("armes", {}) or {}
    chevaux  = ex_inv.get("chevaux", {}) or {}
    permis   = ex_inv.get("permis", {}) or {}
    argent   = existing.get("argent_total", 0)
    props    = existing.get("proprietes", {}) or {}

    data.setdefault("inventaire", {})
    data["inventaire"].setdefault("armes", armes)
    data["inventaire"].setdefault("chevaux", chevaux)
    data["inventaire"].setdefault("permis", permis)
    data["argent_total"] = argent if isinstance(argent, (int, float)) else 0
    data.setdefault("proprietes", props)

    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ========= HELPERS ÉCONOMIE / PROFIL =========

def _ensure_profile_skeleton(user_id: int) -> dict:
    prof = load_profile(user_id) or {}
    if "inventaire" not in prof:
        prof["inventaire"] = {}
    prof["inventaire"].setdefault("armes", {})
    prof["inventaire"].setdefault("chevaux", {})
    prof["inventaire"].setdefault("permis", {})
    prof.setdefault("proprietes", {})
    prof.setdefault("argent_total", 0)
    return prof

def _set_arme_count(armes_dict: Dict[str, int], item: str, new_count: int):
    if new_count <= 0:
        if item in armes_dict:
            del armes_dict[item]
    else:
        armes_dict[item] = new_count

COOLDOWN_CRIME_SECONDS = 4 * 3600
COOLDOWN_ROBB_SECONDS  = 4 * 3600
COOLDOWN_BLCH_SECONDS  = 4 * 3600  # blanchiment

def _ensure_economy_fields(prof: dict) -> dict:
    if prof.get("cash") is None:
        prof["cash"] = 0
    if prof.get("bank") is None:
        prof["bank"] = 0
    if prof.get("dirty") is None:
        prof["dirty"] = 0
    cds = prof.get("cooldowns")
    if not isinstance(cds, dict):
        prof["cooldowns"] = {}
    return prof

def _cooldown_left(prof: dict, key: str, period_sec: int) -> int:
    cds = prof.get("cooldowns") or {}
    last = cds.get(key)
    if not last:
        return 0
    left = int(last + period_sec - time.time())
    return left if left > 0 else 0

def _touch_cooldown(prof: dict, key: str):
    cds = prof.get("cooldowns") or {}
    cds[key] = int(time.time())
    prof["cooldowns"] = cds

def _fmt_money(n: int) -> str:
    s = f"{int(n):,}".replace(",", " ")
    return f"{s} ₣"

# ========= COMMANDES DE BASE =========

@bot.tree.command(name="ping", description="Test : vérifie que le bot répond.")
async def ping_cmd(itx: discord.Interaction):
    await itx.response.send_message("Ça fonctionne.")

@bot.tree.command(name="style_carte", description="Choisir le style visuel (classique/sobre/fonce).")
@app_commands.describe(style="Style: classique, sobre ou fonce")
async def style_carte(itx: discord.Interaction, style: str):
    style = style.lower().strip()
    if style not in THEMES:
        await itx.response.send_message("Styles disponibles : classique, sobre, fonce.")
        return
    CURRENT_THEME["name"] = style
    await itx.response.send_message(f"Style défini sur **{style}**.")

@bot.tree.command(
    name="generer_carte",
    description="Créer la carte d'identité (pour vous ou @cible). Photo jointe si possible, sinon avatar."
)
@app_commands.describe(
    prenom="Prénom (ex. Charles)",
    nom="Nom de famille (ex. Jones)",
    titres="Titre(s) (ex. Comte/général)",
    genre="Genre (ex. M / F )",
    date_naissance="Date (ex. 25/02/1875)",
    lieu_naissance="Lieu (ex. Paris)",
    nationalite="Nationalité (ex. Française)",
    metier="Métier (ex. fermier)",
    photo="Photo du titulaire (pièce jointe conseillée ; sinon l’avatar sera utilisé)",
    cible="Membre pour qui créer la carte (laisser vide pour vous-même)."

)
async def generer_carte(
    itx: discord.Interaction,
    prenom: str,
    nom: str,
    titres: str,
    genre: str,
    date_naissance: str,
    lieu_naissance: str,
    nationalite: str,
    metier: str,
    photo: Optional[discord.Attachment] = None,
    cible: Optional[discord.Member] = None
):
    await itx.response.defer()
    target = cible or itx.user

    # Pièce jointe -> avatar fallback
    img_bytes: Optional[bytes] = None
    ext = ".png"

    if photo is not None:
        try:
            img_bytes = await photo.read()
            ext_att = os.path.splitext(photo.filename)[1].lower()
            if ext_att in [".png", ".jpg", ".jpeg", ".webp"]:
                ext = ext_att
        except Exception:
            img_bytes = None

    if img_bytes is None:
        try:
            asset = target.display_avatar.replace(size=512, format="png")
            img_bytes = await asset.read()
            ext = ".png"
        except Exception:
            await itx.followup.send(embed=embed(
                "Photo manquante",
                "Impossible d’obtenir une image (pièce jointe et avatar ont échoué). "
                "Réessayez avec une pièce jointe PNG/JPG/WEBP."
            ))
            return

    temp_path = os.path.join(ASSETS_DIR, f"photo_{target.id}{ext}")
    try:
        with open(temp_path, "wb") as f:
            f.write(img_bytes)
    except Exception as e:
        await itx.followup.send(embed=embed("Erreur", f"Impossible d'écrire l'image temporaire : `{e}`"))
        return

    data = {
        "prenom": prenom,
        "nom": nom,
        "titres": titres,
        "genre": genre,
        "date_naissance": date_naissance,
        "lieu_naissance": lieu_naissance,
        "nationalite": nationalite,
        "metier": metier,
        "photo_path": temp_path
    }

    try:
        png_bytes = generate_png_bytes(data, style_name=CURRENT_THEME["name"])
    except Exception as e:
        await itx.followup.send(embed=embed("Erreur", f"Impossible de générer la carte : `{e}`"))
        try:
            if os.path.exists(temp_path): os.remove(temp_path)
        except Exception: pass
        return

    save_path = card_path_for(target.id)
    with open(save_path, "wb") as f:
        f.write(png_bytes)

    # Sauvegarder la fiche personnage (identité de base)
    profile_data = {
        "user_id": target.id,
        "prenom": data["prenom"],
        "nom": data["nom"],
        "titres": data["titres"],
        "genre": data["genre"],
        "date_naissance": data["date_naissance"],
        "lieu_naissance": data["lieu_naissance"],
        "nationalite": data["nationalite"],
        "metier": data["metier"]
    }
    save_profile(target.id, profile_data)

    # --- RESET COMPLET + ITEMS DE DÉPART ---
    try:
        prof = _ensure_profile_skeleton(target.id)
        prof = _ensure_economy_fields(prof)

        # RESET inventaire
        prof["inventaire"]["armes"] = {}
        prof["inventaire"]["chevaux"] = {}
        prof["inventaire"]["permis"] = {}

        # ITEMS DE DÉPART
        prof["inventaire"]["armes"]["Revolver Cattleman"] = 1
        prof["inventaire"]["armes"]["Couteau de chasse"] = 1

        # RESET propriétés
        prof["proprietes"] = {}

        # RESET économie
        prof["cash"] = 0
        prof["bank"] = 500  # Bonus de départ
        prof["dirty"] = 0

        # RESET cooldowns
        prof["cooldowns"] = {}

        save_profile(target.id, prof)

    except Exception as e:
        print(f"Erreur reset inventaire de {target.id} : {e}")

    # Nettoyage de la photo temporaire
    try:
        if os.path.exists(temp_path): os.remove(temp_path)
    except Exception:
        pass

    await itx.followup.send(embed=embed(
        "Carte enregistrée",
        f"Carte de **{prenom} {nom}** enregistrée.\n"
        f"_Fichier :_ `cards/{target.id}.png`\n"
        f"💰 **Bonus de bienvenue : +500 ₣** (compte bancaire)."
    ))

@bot.tree.command(name="afficher_carte", description="Afficher la carte enregistrée (pour vous ou @cible).")
@app_commands.describe(cible="Membre dont on veut montrer la carte (laisser vide pour la vôtre).")
async def afficher_carte(itx: discord.Interaction, cible: Optional[discord.Member]):
    target = cible or itx.user
    save_path = card_path_for(target.id)

    display = target.display_name
    await itx.response.send_message(f"**{display}** est en train de chercher sa carte…")
    await asyncio.sleep(1.2)

    if not os.path.exists(save_path):
        await itx.followup.send(embed=embed("Carte introuvable",
            f"Aucune carte enregistrée pour **{display}**. Utilisez `/generer_carte`.")); return

    await itx.followup.send(embed=embed("Carte d'identité", f"Carte de **{display}**"),
                            file=discord.File(save_path, filename=os.path.basename(save_path)))

@bot.tree.command(
    name="modifier_identite",
    description="Mettre à jour Nom/Prénom/Titres/Métier et régénérer la carte (sans toucher à l’inventaire/économie)."
)
@app_commands.describe(
    cible="Membre dont on modifie l'identité (laisser vide pour vous-même).",
    prenom="Nouveau prénom (laisser vide pour ne pas changer)",
    nom="Nouveau nom (laisser vide pour ne pas changer)",
    titres="Nouveaux titres (laisser vide pour ne pas changer)",
    metier="Nouveau métier (laisser vide pour ne pas changer)",
    photo="Nouvelle photo optionnelle (PNG/JPG/WEBP). Sinon avatar actuel."
)
async def modifier_identite(
    itx: discord.Interaction,
    cible: Optional[discord.Member],
    prenom: Optional[str] = None,
    nom: Optional[str] = None,
    titres: Optional[str] = None,
    metier: Optional[str] = None,
    photo: Optional[discord.Attachment] = None
):
    """
    Met à jour uniquement les champs d'identité indiqués et régénère la carte PNG.
    Ne réinitialise NI l'inventaire, NI l'économie, NI les propriétés, NI les cooldowns.
    """
    await itx.response.defer()

    target = cible or itx.user
    prof = load_profile(target.id)
    if not prof:
        await itx.followup.send(
            embed=embed("Fiche introuvable", "Aucune fiche trouvée. Utilisez d’abord `/generer_carte`."),
            ephemeral=True
        )
        return

    # --- Appliquer les modifications demandées, sans toucher au reste ---
    if prenom is not None and prenom.strip() != "":
        prof["prenom"] = prenom.strip()
    if nom is not None and nom.strip() != "":
        prof["nom"] = nom.strip()
    if titres is not None and titres.strip() != "":
        prof["titres"] = titres.strip()
    if metier is not None and metier.strip() != "":
        prof["metier"] = metier.strip()

    # Valeurs d’identité pour la génération d’image
    data_img = {
        "prenom":        prof.get("prenom", "—"),
        "nom":           prof.get("nom", "—"),
        "titres":        prof.get("titres", "—"),
        "genre":         prof.get("genre", "—"),
        "date_naissance":prof.get("date_naissance", "—"),
        "lieu_naissance":prof.get("lieu_naissance", "—"),
        "nationalite":   prof.get("nationalite", "—"),
        "metier":        prof.get("metier", "—"),
    }

    # Préparer une image source : pièce jointe > avatar
    img_bytes: Optional[bytes] = None
    ext = ".png"
    if photo is not None:
        try:
            img_bytes = await photo.read()
            ext_att = os.path.splitext(photo.filename)[1].lower()
            if ext_att in [".png", ".jpg", ".jpeg", ".webp"]:
                ext = ext_att
        except Exception:
            img_bytes = None

    if img_bytes is None:
        try:
            asset = target.display_avatar.replace(size=512, format="png")
            img_bytes = await asset.read()
            ext = ".png"
        except Exception:
            img_bytes = None  # on générera la carte sans photo si vraiment rien

    temp_path = None
    if img_bytes is not None:
        try:
            temp_path = os.path.join(ASSETS_DIR, f"photo_{target.id}{ext}")
            with open(temp_path, "wb") as f:
                f.write(img_bytes)
            data_img["photo_path"] = temp_path
        except Exception:
            temp_path = None

    # Générer la nouvelle carte
    try:
        png_bytes = generate_png_bytes(data_img, style_name=CURRENT_THEME["name"])
        save_path = card_path_for(target.id)
        with open(save_path, "wb") as f:
            f.write(png_bytes)
    except Exception as e:
        # Nettoyage éventuel
        if temp_path and os.path.exists(temp_path):
            try: os.remove(temp_path)
            except Exception: pass
        await itx.followup.send(embed=embed("Erreur", f"Impossible de régénérer la carte : `{e}`"))
        return

    # Nettoyage de la photo temporaire (si utilisée)
    if temp_path and os.path.exists(temp_path):
        try: os.remove(temp_path)
        except Exception: pass

    # ÉCRITURE SÛRE DU PROFIL : on ne passe pas par save_profile() pour ne rien écraser
    try:
        with open(profile_path_for(target.id), "w", encoding="utf-8") as f:
            json.dump(prof, f, ensure_ascii=False, indent=2)
    except Exception as e:
        await itx.followup.send(embed=embed("Avertissement", f"Carte régénérée, mais échec de sauvegarde du profil : `{e}`"))
        return

    await itx.followup.send(embed=embed(
        "Identité mise à jour",
        f"Carte régénérée pour **{prof.get('prenom','—')} {prof.get('nom','—')}**.\n"
        f"_Fichier :_ `cards/{target.id}.png`\n"
        f"ℹ️ Inventaire, propriétés, économie et cooldowns **inchangés**."
    ))


@bot.tree.command(name="fiche_personnage", description="Afficher la fiche (identité, inventaires et propriétés).")
@app_commands.describe(cible="Membre dont on veut afficher la fiche (laisser vide pour la vôtre).")
async def fiche_personnage(itx: discord.Interaction, cible: Optional[discord.Member]):
    target = cible or itx.user
    prof = load_profile(target.id)
    if not prof:
        await itx.response.send_message(
            f"Aucune fiche trouvée pour **{target.display_name}**.\n"
            f"Générez d’abord une carte avec `/generer_carte`.",
            ephemeral=True
        )
        return

    # Assure les champs d'économie
    def _ensure_economy_fields_local(p: dict) -> dict:
        ch = False
        if p.get("cash")  is None: p["cash"]  = 0; ch = True
        if p.get("bank")  is None: p["bank"]  = 0; ch = True
        if p.get("dirty") is None: p["dirty"] = 0; ch = True
        if ch: save_profile(target.id, p)
        return p

    prof = _ensure_economy_fields_local(prof)

    # Identité
    nom    = prof.get("nom", "—")
    prenom = prof.get("prenom", "—")
    date   = prof.get("date_naissance", "—")
    genre  = prof.get("genre", "—")
    nat    = prof.get("nationalite", "—")
    metier = prof.get("metier", "—")

    # Économie
    cash  = int(prof.get("cash", 0) or 0)
    bank  = int(prof.get("bank", 0) or 0)
    dirty = int(prof.get("dirty", 0) or 0)

    def fmt_money(n: int) -> str:
        return f"{int(n):,}".replace(",", " ") + " ₣"

    # Inventaires
    inv        = prof.get("inventaire", {}) or {}
    armes      = inv.get("armes", {}) or {}
    chevaux    = inv.get("chevaux", {}) or {}
    permis     = inv.get("permis", {}) or {}
    proprietes = prof.get("proprietes", {}) or {}

    def fmt_dict_qty(d: dict) -> str:
        if not d: return "— vide"
        return "\n".join(f"• {k} × {v}" for k, v in sorted(d.items(), key=lambda kv: kv[0].lower()))

    def fmt_dict_flag(d: dict) -> str:
        if not d: return "— vide"
        parts = []
        for k, v in sorted(d.items(), key=lambda kv: kv[0].lower()):
            parts.append(f"• {k}" + (f" : {v}" if v not in (None, True, 1, "", "acquise", "valide") else ""))
        return "\n".join(parts)

    # Prépare l’embed
    emb = discord.Embed(
        title=f"Fiche Personnage — {prenom} {nom}",
        color=discord.Color.dark_gold()
    )

    ident_txt = (
        f"**Nom :** {nom}\n"
        f"**Prénom :** {prenom}\n"
        f"**Date de naissance :** {date}\n"
        f"**Sexe :** {genre}\n"
        f"**Nationalité :** {nat}\n"
        f"**Métier :** {metier}"
    )
    emb.add_field(name="Identité", value=ident_txt, inline=False)

    eco_txt = (
        f"💰 **Espèces (cash)** : {fmt_money(cash)}\n"
        f"🏦 **Compte (banque)** : {fmt_money(bank)}\n"
        f"⚖️ **Argent sale** : {fmt_money(dirty)}"
    )
    emb.add_field(name="Économie", value=eco_txt, inline=False)

    emb.add_field(name="🗡️ Armes", value=fmt_dict_qty(armes), inline=True)
    emb.add_field(name="🐎 Chevaux", value=fmt_dict_qty(chevaux), inline=True)
    emb.add_field(name="📜 Permis", value=fmt_dict_flag(permis), inline=False)
    emb.add_field(name="🏠 Propriétés", value=fmt_dict_flag(proprietes), inline=False)

    # Armoiries en miniature si dispo
    file_to_send = None
    if os.path.exists(WM_PATH):
        try:
            file_to_send = discord.File(WM_PATH, filename="armoiries.png")
            emb.set_thumbnail(url="attachment://armoiries.png")
        except Exception:
            file_to_send = None

    if file_to_send:
        await itx.response.send_message(embed=emb, file=file_to_send)
    else:
        await itx.response.send_message(embed=emb)

@bot.tree.command(name="bal", description="Afficher l'extrait de compte bancaire (cash / compte / argent sale).")
@app_commands.describe(cible="Membre dont on veut afficher le solde (laisser vide pour la vôtre).")
async def bal(itx: discord.Interaction, cible: Optional[discord.Member] = None):
    target = cible or itx.user
    prof = load_profile(target.id)
    if not prof:
        await itx.response.send_message(
            f"Aucune fiche trouvée pour **{target.display_name}**.\nGénérez d’abord une carte avec `/generer_carte`.",
            ephemeral=True
        )
        return

    changed = False
    if prof.get("cash") is None:
        prof["cash"] = 0; changed = True
    if prof.get("bank") is None:
        prof["bank"] = 0; changed = True
    if prof.get("dirty") is None:
        prof["dirty"] = 0; changed = True
    if changed:
        save_profile(target.id, prof)

    cash  = int(prof.get("cash", 0))
    bank  = int(prof.get("bank", 0))
    dirty = int(prof.get("dirty", 0))
    total = cash + bank + dirty

    # Rang (leaderboard)
    def ordinal_en(n: int) -> str:
        if n is None: return "–"
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1:"st", 2:"nd", 3:"rd"}.get(n % 10, "th")
        return f"{n}{suffix}"

    try:
        ranks: List[Tuple[int,int]] = []
        for fname in os.listdir(PROFILES_DIR):
            if not fname.endswith(".json"):
                continue
            pth = os.path.join(PROFILES_DIR, fname)
            try:
                with open(pth, "r", encoding="utf-8") as f:
                    d = json.load(f)
            except Exception:
                continue
            uid = int(d.get("user_id") or os.path.splitext(fname)[0])
            ranks.append((uid, int(d.get("cash",0)) + int(d.get("bank",0)) + int(d.get("dirty",0))))
        ranks.sort(key=lambda t: t[1], reverse=True)
        rank_pos = next((i+1 for i,(uid,_) in enumerate(ranks) if uid == target.id), None)
        rank_str = f"({ordinal_en(rank_pos)})"
    except Exception:
        rank_str = "(–)"

    # Préparer l'embed
    titre = "BANQUE ROYALE DE FRANCE"
    desc  = "Extrait de compte"

    embed_msg = discord.Embed(
        title=titre,
        description=desc,
        color=discord.Color.dark_gold()
    )

    prenom = prof.get("prenom", "—")
    nom    = prof.get("nom", "—")
    metier = prof.get("metier", "—")

    embed_msg.add_field(name="Nom", value=f"{prenom} {nom}", inline=True)
    embed_msg.add_field(name="Métier", value=metier, inline=True)
    embed_msg.add_field(name="Leaderboard", value=rank_str, inline=True)

    embed_msg.add_field(name="\u200b", value="━━━━━━━━━━━━━━━━━━━━━━", inline=False)

    embed_msg.add_field(name="💰 Espèces (cash)", value=_fmt_money(cash), inline=True)
    embed_msg.add_field(name="🏦 Compte bancaire", value=_fmt_money(bank), inline=True)
    embed_msg.add_field(name="⚖️ Argent sale", value=_fmt_money(dirty), inline=True)

    embed_msg.add_field(name="\u200b", value=f"**Total : {_fmt_money(total)}**", inline=False)

    # Logo en haut à droite
    files = []
    logo_path = os.path.join(ASSETS_DIR, "banque.png")
    if os.path.exists(logo_path):
        files = [discord.File(logo_path, filename="banque.png")]
        embed_msg.set_thumbnail(url="attachment://banque.png")

    try:
        await itx.response.send_message(embed=embed_msg, file=files[0] if files else None)
    except Exception:
        await itx.response.send_message(embed=embed_msg)

# ========= COMMANDES ÉCONOMIE =========

WALLETS_CHOICES = [
    app_commands.Choice(name="Banque", value="bank"),
    app_commands.Choice(name="Cash", value="cash"),
    app_commands.Choice(name="Argent sale", value="dirty"),
]

@bot.tree.command(name="add_money", description="Créditer un joueur (banque/cash/argent sale).")
@app_commands.describe(
    cible="Membre à créditer",
    montant="Montant (>0)",
    sur="Poche à créditer (défaut : Banque)"
)
@app_commands.choices(sur=WALLETS_CHOICES)
async def add_money(
    itx: discord.Interaction,
    cible: discord.Member,
    montant: int,
    sur: Optional[app_commands.Choice[str]] = None
):
    if montant <= 0:
        await itx.response.send_message("Le montant doit être > 0.", ephemeral=True)
        return
    wallet = (sur.value if sur else "bank")
    if wallet not in ("bank", "cash", "dirty"):
        await itx.response.send_message("Poche invalide (bank, cash, dirty).", ephemeral=True)
        return

    prof = _ensure_profile_skeleton(cible.id)
    prof = _ensure_economy_fields(prof)
    prof[wallet] = int(prof.get(wallet, 0)) + int(montant)
    save_profile(cible.id, prof)

    total = int(prof.get("cash", 0)) + int(prof.get("bank", 0)) + int(prof.get("dirty", 0))
    await itx.response.send_message(
        f"✅ **+{_fmt_money(montant)}** sur **{wallet}** pour {cible.mention}\n"
        f"→ Nouveau solde {wallet} : **{_fmt_money(int(prof[wallet]))}**\n"
        f"→ Total (cash+banque+sale) : **{_fmt_money(total)}**"
    )

@bot.tree.command(name="remove_money", description="Débiter un joueur (banque/cash/argent sale). Solde négatif autorisé.")
@app_commands.describe(
    cible="Membre à débiter",
    montant="Montant (>0)",
    sur="Poche à débiter (défaut : Banque)"
)
@app_commands.choices(sur=WALLETS_CHOICES)
async def remove_money(
    itx: discord.Interaction,
    cible: discord.Member,
    montant: int,
    sur: Optional[app_commands.Choice[str]] = None
):
    if montant <= 0:
        await itx.response.send_message("Le montant doit être > 0.", ephemeral=True)
        return
    wallet = (sur.value if sur else "bank")
    if wallet not in ("bank", "cash", "dirty"):
        await itx.response.send_message("Poche invalide (bank, cash, dirty).", ephemeral=True)
        return

    prof = _ensure_profile_skeleton(cible.id)
    prof = _ensure_economy_fields(prof)
    prof[wallet] = int(prof.get(wallet, 0)) - int(montant)  # peut devenir négatif
    save_profile(cible.id, prof)

    total = int(prof.get("cash", 0)) + int(prof.get("bank", 0)) + int(prof.get("dirty", 0))
    await itx.response.send_message(
        f"➖ **−{_fmt_money(montant)}** sur **{wallet}** pour {cible.mention}\n"
        f"→ Nouveau solde {wallet} : **{_fmt_money(int(prof[wallet]))}**\n"
        f"→ Total (cash+banque+sale) : **{_fmt_money(total)}**"
    )

# ---------- ÉCONOMIE : WITH / DEP / PAY / PAYCRIME ----------

def _parse_amount_input(txt: str, available: int) -> Optional[int]:
    """
    Accepte un entier > 0 ou 'all'/'tout'/'toute' -> renvoie un int.
    Retourne None si invalide.
    """
    if not isinstance(txt, str):
        return None
    t = txt.strip().lower()
    if t in ("all", "tout", "toute"):
        return int(max(0, available))
    try:
        n = int(t)
        if n <= 0:
            return None
        return n
    except Exception:
        return None

@bot.tree.command(name="with", description="Retirer de la banque vers le cash.")
@app_commands.describe(montant='Montant (>0) ou "all"')
async def with_cmd(itx: discord.Interaction, montant: str):
    user = itx.user
    prof = _ensure_profile_skeleton(user.id)
    prof = _ensure_economy_fields(prof)

    bank = int(prof.get("bank", 0))
    amt = _parse_amount_input(montant, bank)
    if amt is None:
        await itx.response.send_message('Montant invalide. Utilisez un entier > 0 ou "all".', ephemeral=True)
        return
    if bank <= 0:
        await itx.response.send_message("Votre compte bancaire est vide.", ephemeral=True)
        return
    if amt > bank:
        await itx.response.send_message(f"Solde insuffisant : {_fmt_money(bank)} disponibles.", ephemeral=True)
        return

    prof["bank"] = bank - amt
    prof["cash"] = int(prof.get("cash", 0)) + amt
    save_profile(user.id, prof)

    await itx.response.send_message(
        f"🏦 ➜ 💵 **Retrait** : +{_fmt_money(amt)} en cash\n"
        f"➡️ Banque : {_fmt_money(int(prof['bank']))} • Cash : {_fmt_money(int(prof['cash']))}"
    )

@bot.tree.command(name="dep", description="Déposer du cash vers la banque.")
@app_commands.describe(montant='Montant (>0) ou "all"')
async def dep_cmd(itx: discord.Interaction, montant: str):
    user = itx.user
    prof = _ensure_profile_skeleton(user.id)
    prof = _ensure_economy_fields(prof)

    cash = int(prof.get("cash", 0))
    amt = _parse_amount_input(montant, cash)
    if amt is None:
        await itx.response.send_message('Montant invalide. Utilisez un entier > 0 ou "all".', ephemeral=True)
        return
    if cash <= 0:
        await itx.response.send_message("Vous n'avez pas de cash à déposer.", ephemeral=True)
        return
    if amt > cash:
        await itx.response.send_message(f"Cash insuffisant : {_fmt_money(cash)} disponibles.", ephemeral=True)
        return

    prof["cash"] = cash - amt
    prof["bank"] = int(prof.get("bank", 0)) + amt
    save_profile(user.id, prof)

    await itx.response.send_message(
        f"💵 ➜ 🏦 **Dépôt** : +{_fmt_money(amt)} en banque\n"
        f"➡️ Banque : {_fmt_money(int(prof['bank']))} • Cash : {_fmt_money(int(prof['cash']))}"
    )

@bot.tree.command(name="pay", description="Payer un joueur (cash -> cash).")
@app_commands.describe(beneficiaire="Membre à payer", montant="Montant (>0)")
async def pay_cmd(itx: discord.Interaction, beneficiaire: discord.Member, montant: int):
    payeur = itx.user
    if payeur.id == beneficiaire.id:
        await itx.response.send_message("On ne se paie pas soi-même…", ephemeral=True)
        return
    if montant is None or not isinstance(montant, int) or montant <= 0:
        await itx.response.send_message("Montant invalide (entier > 0).", ephemeral=True)
        return

    prof_p = _ensure_profile_skeleton(payeur.id)
    prof_p = _ensure_economy_fields(prof_p)
    prof_b = _ensure_profile_skeleton(beneficiaire.id)
    prof_b = _ensure_economy_fields(prof_b)

    cash_p = int(prof_p.get("cash", 0))
    if montant > cash_p:
        await itx.response.send_message(f"Cash insuffisant. Vous avez {_fmt_money(cash_p)}.", ephemeral=True)
        return

    prof_p["cash"] = cash_p - montant
    prof_b["cash"] = int(prof_b.get("cash", 0)) + montant
    save_profile(payeur.id, prof_p)
    save_profile(beneficiaire.id, prof_b)

    await itx.response.send_message(
        f"🤝 **Paiement envoyé** : {beneficiaire.mention} reçoit {_fmt_money(montant)} (cash).\n"
        f"Votre nouveau cash : {_fmt_money(int(prof_p['cash']))}"
    )

@bot.tree.command(name="paycrime", description="Payer un joueur en argent sale (dirty -> dirty).")
@app_commands.describe(beneficiaire="Membre à payer", montant="Montant (>0)")
async def paycrime_cmd(itx: discord.Interaction, beneficiaire: discord.Member, montant: int):
    payeur = itx.user
    if payeur.id == beneficiaire.id:
        await itx.response.send_message("On ne se paie pas soi-même…", ephemeral=True)
        return
    if montant is None or not isinstance(montant, int) or montant <= 0:
        await itx.response.send_message("Montant invalide (entier > 0).", ephemeral=True)
        return

    prof_p = _ensure_profile_skeleton(payeur.id)
    prof_p = _ensure_economy_fields(prof_p)
    prof_b = _ensure_profile_skeleton(beneficiaire.id)
    prof_b = _ensure_economy_fields(prof_b)

    dirty_p = int(prof_p.get("dirty", 0))
    if montant > dirty_p:
        await itx.response.send_message(f"Argent sale insuffisant. Vous avez {_fmt_money(dirty_p)}.", ephemeral=True)
        return

    prof_p["dirty"] = dirty_p - montant
    prof_b["dirty"] = int(prof_b.get("dirty", 0)) + montant
    save_profile(payeur.id, prof_p)
    save_profile(beneficiaire.id, prof_b)

    await itx.response.send_message(
        f"🕶️ **Paiement clandestin envoyé** : {beneficiaire.mention} reçoit {_fmt_money(montant)} (argent sale).\n"
        f"Votre nouveau dirty : {_fmt_money(int(prof_p['dirty']))}"
    )

# ========= INVENTAIRE : ARMES =========

ARMES_LISTE = [
    "Revolver Cattleman", "Revolver Double-Action", "Revolver Schofield", "Revolver LeMat",
    "Revolver Navy", "Pistolet Mauser", "Pistolet semi-automatique", "Pistolet Volcanic",
    "Carabine à répétition", "Lancaster", "Litchfield", "Evans",
    "Fusil à verrou", "Fusil Springfield", "Fusil Rolling Block", "Fusil Carcano",
    "Fusil à double canon", "Fusil semi-automatique", "Fusil à pompe",
    "Couteau de chasse", "Machette", "Hache", "Epée", "Couteau de lancée", "Tomahawk",
]
ARMES_CHOICES = [app_commands.Choice(name=nom, value=nom) for nom in ARMES_LISTE]

@bot.tree.command(name="add_armes", description="Ajouter une arme à l'inventaire.")
@app_commands.describe(cible="Membre (laisser vide pour vous-même)",
                       item="Arme à ajouter",
                       quantite="Quantité (entier > 0)")
@app_commands.choices(item=ARMES_CHOICES)
async def add_armes(itx: discord.Interaction,
                    cible: Optional[discord.Member],
                    item: app_commands.Choice[str],
                    quantite: str):
    try:
        q = int(quantite)
        if q <= 0:
            raise ValueError
    except Exception:
        await itx.response.send_message("La quantité doit être un entier strictement positif.", ephemeral=True)
        return

    target = cible or itx.user
    prof = _ensure_profile_skeleton(target.id)
    armes = prof["inventaire"]["armes"]
    current = int(armes.get(item.value, 0))
    new_val = current + q
    _set_arme_count(armes, item.value, new_val)
    save_profile(target.id, prof)

    await itx.response.send_message(
        f"✅ **{item.value}** ×{q} ajouté à l’inventaire de **{target.display_name}**. "
        f"(Total : {new_val})"
    )

@bot.tree.command(name="remove_armes", description="Retirer une arme de l'inventaire.")
@app_commands.describe(cible="Membre (laisser vide pour vous-même)",
                       item="Arme à retirer",
                       quantite="Entrez un entier (>0) ou all pour retirer tout (minuscule)")
@app_commands.choices(item=ARMES_CHOICES)
async def remove_armes(itx: discord.Interaction,
                       cible: Optional[discord.Member],
                       item: app_commands.Choice[str],
                       quantite: str):
    target = cible or itx.user
    prof = _ensure_profile_skeleton(target.id)
    armes = prof["inventaire"]["armes"]
    current = int(armes.get(item.value, 0))

    if quantite.strip().lower() == "all":
        _set_arme_count(armes, item.value, 0)
        save_profile(target.id, prof)
        await itx.response.send_message(
            f"🗑️ **{item.value}** retiré entièrement de l’inventaire de **{target.display_name}**."
        )
        return

    try:
        q = int(quantite)
        if q <= 0:
            raise ValueError
    except Exception:
        await itx.response.send_message("La quantité doit être un entier (>0) ou **all**.", ephemeral=True)
        return

    new_val = max(0, current - q)
    _set_arme_count(armes, item.value, new_val)
    save_profile(target.id, prof)

    await itx.response.send_message(
        f"➖ **{item.value}** −{q} pour **{target.display_name}**. "
        f"(Restant : {new_val})"
    )

# ========= INVENTAIRE : CHEVAUX =========

CHEVAUX_LISTE = [
    "Cheval du Kentucky","Morgan","Tennessee Walker","Suffolk Punch","Shire","Nokota",
    "Pur-sang","Trotteur américain","Chevaux de guerre","Ardennais","Demi-sang hongrois",
    "Andalou","Hollandais à sang chaud","Appaloosa","American Paint","Missouri Fox Trotter",
    "Mustang","Turkoman","Breton","Criollo","Kladruber","Cob Gypsy","Pur-sang arabe",
]
CHEVAUX_CHOICES = [app_commands.Choice(name=nom, value=nom) for nom in CHEVAUX_LISTE]

@bot.tree.command(name="add_horse", description="Ajouter un cheval (race) à l'inventaire.")
@app_commands.describe(cible="Membre (laisser vide pour vous-même)",
                       item="Race de cheval à ajouter",
                       quantite="Quantité (entier > 0)")
@app_commands.choices(item=CHEVAUX_CHOICES)
async def add_horse(itx: discord.Interaction,
                    cible: Optional[discord.Member],
                    item: app_commands.Choice[str],
                    quantite: str):

    try:
        q = int(quantite)
        if q <= 0:
            raise ValueError
    except Exception:
        await itx.response.send_message("La quantité doit être un entier strictement positif.", ephemeral=True)
        return

    target = cible or itx.user
    prof = _ensure_profile_skeleton(target.id)
    chevaux = prof["inventaire"]["chevaux"]
    current = int(chevaux.get(item.value, 0))
    new_val = current + q
    chevaux[item.value] = new_val
    save_profile(target.id, prof)

    await itx.response.send_message(
        f"✅ **{item.value}** ×{q} ajouté à l’inventaire de **{target.display_name}**. "
        f"(Total : {new_val})"
    )

@bot.tree.command(name="remove_horse", description="Retirer un cheval (race) de l'inventaire.")
@app_commands.describe(cible="Membre (laisser vide pour vous-même)",
                       item="Race de cheval à retirer",
                       quantite="Entrez un entier (>0) ou all pour retirer tout")
@app_commands.choices(item=CHEVAUX_CHOICES)
async def remove_horse(itx: discord.Interaction,
                       cible: Optional[discord.Member],
                       item: app_commands.Choice[str],
                       quantite: str):

    target = cible or itx.user
    prof = _ensure_profile_skeleton(target.id)
    chevaux = prof["inventaire"]["chevaux"]
    current = int(chevaux.get(item.value, 0))

    if quantite.strip().lower() == "all":
        chevaux.pop(item.value, None)
        save_profile(target.id, prof)
        await itx.response.send_message(
            f"🗑️ **{item.value}** retiré entièrement de l’inventaire de **{target.display_name}**."
        )
        return

    try:
        q = int(quantite)
        if q <= 0:
            raise ValueError
    except Exception:
        await itx.response.send_message("La quantité doit être un entier (>0) ou **all**.", ephemeral=True)
        return

    new_val = max(0, current - q)
    if new_val == 0:
        chevaux.pop(item.value, None)
    else:
        chevaux[item.value] = new_val

    save_profile(target.id, prof)

    await itx.response.send_message(
        f"➖ **{item.value}** −{q} pour **{target.display_name}**. "
        f"(Restant : {new_val})"
    )

# ========= PROPRIÉTÉS =========

PROPRIETES_LISTE = [
    "Shady Bell","Calliga Hall","Bourbon's Manor","Palais Royal de Saint Denis",
    "Manoir Bronte","Petite Maison","Moyenne Maison","Grande Maison","Emerald Ranch",
    "Saloon Saint Denis","Saloon Rhodes","Saloon Van Horn","Saloon Blackwater",
    "Armurerie Rhodes","Armurerie Saint Denis","Écurie Van Horn","Écurie Saint Denis","Distilerie","Entreprise",
]

@bot.tree.command(name="add_property", description="Ajouter une propriété au profil (sans quantité).")
@app_commands.describe(cible="Membre (laisser vide pour vous-même)",
                       item="Propriété à ajouter")
@app_commands.choices(item=[app_commands.Choice(name=p, value=p) for p in PROPRIETES_LISTE])
async def add_property(itx: discord.Interaction,
                       cible: Optional[discord.Member],
                       item: app_commands.Choice[str]):
    target = cible or itx.user
    prof = _ensure_profile_skeleton(target.id)
    props = prof.get("proprietes", {})
    props[item.value] = "acquise"
    prof["proprietes"] = props
    save_profile(target.id, prof)

    await itx.response.send_message(
        f"🏠 **{item.value}** ajoutée aux propriétés de **{target.display_name}**."
    )

@bot.tree.command(name="remove_property", description="Retirer une propriété du profil.")
@app_commands.describe(cible="Membre (laisser vide pour vous-même)",
                       item="Propriété à retirer")
@app_commands.choices(item=[app_commands.Choice(name=p, value=p) for p in PROPRIETES_LISTE])
async def remove_property(itx: discord.Interaction,
                          cible: Optional[discord.Member],
                          item: app_commands.Choice[str]):
    target = cible or itx.user
    prof = _ensure_profile_skeleton(target.id)
    props = prof.get("proprietes", {})
    existed = props.pop(item.value, None)
    prof["proprietes"] = props
    save_profile(target.id, prof)

    if existed is not None:
        msg = f"🗑️ **{item.value}** retirée des propriétés de **{target.display_name}**."
    else:
        msg = f"ℹ️ **{item.value}** n’était pas enregistrée pour **{target.display_name}**."
    await itx.response.send_message(msg)

# ========= PERMIS =========

PERMIS_LISTE = [
    "Armes d'épaules","Armes lourdes","Armes longue distance",
    "Permis de chasse","Licence de Chasseur de Prime",
    "Mandat Gouvernemental","Laisser Passez Gouvernemental",
]
PERMIS_CHOICES = [app_commands.Choice(name=nom, value=nom) for nom in PERMIS_LISTE]

@bot.tree.command(name="add_permit", description="Ajouter un permis au profil (sans quantité).")
@app_commands.describe(cible="Membre (laisser vide pour vous-même)",
                       item="Permis à ajouter")
@app_commands.choices(item=PERMIS_CHOICES)
async def add_permit(itx: discord.Interaction,
                     cible: Optional[discord.Member],
                     item: app_commands.Choice[str]):
    target = cible or itx.user
    prof = _ensure_profile_skeleton(target.id)
    per = prof["inventaire"].get("permis", {})
    per[item.value] = "valide"
    prof["inventaire"]["permis"] = per
    save_profile(target.id, prof)

    await itx.response.send_message(
        f"📜 **{item.value}** ajouté (valide) pour **{target.display_name}**."
    )

@bot.tree.command(name="remove_permit", description="Retirer un permis du profil.")
@app_commands.describe(cible="Membre (laisser vide pour vous-même)",
                       item="Permis à retirer")
@app_commands.choices(item=PERMIS_CHOICES)
async def remove_permit(itx: discord.Interaction,
                        cible: Optional[discord.Member],
                        item: app_commands.Choice[str]):
    target = cible or itx.user
    prof = _ensure_profile_skeleton(target.id)
    per = prof["inventaire"].get("permis", {})
    existed = per.pop(item.value, None)
    prof["inventaire"]["permis"] = per
    save_profile(target.id, prof)

    if existed is not None:
        msg = f"🗑️ **{item.value}** retiré des permis de **{target.display_name}**."
    else:
        msg = f"ℹ️ **{item.value}** n’était pas enregistré pour **{target.display_name}**."
    await itx.response.send_message(msg)

# ========= TRANSFERT D’ITEMS =========

GIVE_CATEGORIES = [
    app_commands.Choice(name="Armes", value="armes"),
    app_commands.Choice(name="Chevaux", value="chevaux"),
    app_commands.Choice(name="Permis", value="permis"),
    app_commands.Choice(name="Propriétés", value="proprietes"),
]

def _parse_qty_for_transfer(txt: Optional[str], available: int, default_if_missing: int = 1) -> Optional[int]:
    """
    Pour armes/chevaux uniquement.
    - None -> par défaut 1
    - 'all'/'tout'/'toute' -> tout ce qui est dispo
    - entier > 0
    Retourne None si invalide.
    """
    if txt is None or str(txt).strip() == "":
        return default_if_missing
    t = str(txt).strip().lower()
    if t in ("all", "tout", "toute"):
        return int(max(0, available))
    try:
        n = int(t)
        if n <= 0:
            return None
        return n
    except Exception:
        return None

@bot.tree.command(
    name="give_item",
    description="Donner un item de votre inventaire à un joueur (armes, chevaux, permis, propriétés)."
)
@app_commands.describe(
    beneficiaire="Membre qui reçoit l’item",
    categorie="Catégorie de l’item (armes/chevaux/permis/propriétés)",
    item="Nom exact de l’item (auto-complété selon votre inventaire)",
    quantite="(Armes/Chevaux) Entier > 0 ou 'all'. Ignorer pour Permis/Propriétés."
)
@app_commands.choices(categorie=GIVE_CATEGORIES)
async def give_item_cmd(
    itx: discord.Interaction,
    beneficiaire: discord.Member,
    categorie: app_commands.Choice[str],
    item: str,
    quantite: Optional[str] = None
):
    donneur = itx.user
    if donneur.id == beneficiaire.id:
        await itx.response.send_message("On ne se transfère pas un item à soi-même…", ephemeral=True)
        return

    cat = categorie.value  # 'armes' | 'chevaux' | 'permis' | 'proprietes'

    prof_d = _ensure_profile_skeleton(donneur.id)
    prof_b = _ensure_profile_skeleton(beneficiaire.id)

    inv_d = prof_d.get("inventaire", {}) or {}
    inv_b = prof_b.get("inventaire", {}) or {}

    # Normalise structures
    inv_d.setdefault("armes", {}); inv_b.setdefault("armes", {})
    inv_d.setdefault("chevaux", {}); inv_b.setdefault("chevaux", {})
    inv_d.setdefault("permis", {}); inv_b.setdefault("permis", {})
    prof_d["inventaire"] = inv_d; prof_b["inventaire"] = inv_b
    prof_d.setdefault("proprietes", {}); prof_b.setdefault("proprietes", {})

    # ----- Armes / Chevaux : transfert avec quantités -----
    if cat in ("armes", "chevaux"):
        source = inv_d[cat]
        if item not in source:
            await itx.response.send_message(f"L’item **{item}** n’est pas dans vos {cat}.", ephemeral=True)
            return

        dispo = int(source.get(item, 0))
        if dispo <= 0:
            await itx.response.send_message(f"Vous ne possédez plus de **{item}**.", ephemeral=True)
            return

        qty = _parse_qty_for_transfer(quantite, available=dispo, default_if_missing=1)
        if qty is None or qty <= 0:
            await itx.response.send_message("Quantité invalide (entier > 0 ou 'all').", ephemeral=True)
            return
        qty = min(qty, dispo)

        # Décrémente donneur
        reste = dispo - qty
        if reste <= 0:
            source.pop(item, None)
        else:
            source[item] = reste

        # Incrémente bénéficiaire
        inv_b[cat][item] = int(inv_b[cat].get(item, 0)) + qty

        save_profile(donneur.id, prof_d)
        save_profile(beneficiaire.id, prof_b)

        await itx.response.send_message(
            f"🎁 **Transfert** — {donneur.mention} ➜ {beneficiaire.mention}\n"
            f"• {cat[:-1].capitalize()} : **{item}** × {qty}\n"
            f"• Votre restant : {int(inv_d[cat].get(item, 0)) if item in inv_d[cat] else 0}"
        )
        return

    # ----- Permis : présence/absence (pas de quantité) -----
    if cat == "permis":
        if item not in inv_d["permis"]:
            await itx.response.send_message(f"Vous n’avez pas le permis **{item}**.", ephemeral=True)
            return
        if item in inv_b["permis"]:
            await itx.response.send_message(f"{beneficiaire.display_name} possède déjà le permis **{item}**.", ephemeral=True)
            return

        inv_b["permis"][item] = "valide"
        inv_d["permis"].pop(item, None)

        save_profile(donneur.id, prof_d)
        save_profile(beneficiaire.id, prof_b)

        await itx.response.send_message(
            f"🎁 **Transfert de permis** — {donneur.mention} ➜ {beneficiaire.mention}\n"
            f"• Permis : **{item}** (désormais *valide* pour le bénéficiaire)"
        )
        return

    # ----- Propriétés : présence/absence (pas de quantité) -----
    if cat == "proprietes":
        props_d = prof_d["proprietes"]
        props_b = prof_b["proprietes"]

        if item not in props_d:
            await itx.response.send_message(f"Vous ne possédez pas la propriété **{item}**.", ephemeral=True)
            return
        if item in props_b:
            await itx.response.send_message(f"{beneficiaire.display_name} possède déjà la propriété **{item}**.", ephemeral=True)
            return

        # Transfert : on conserve l’étiquette si elle existe, sinon 'acquise'
        label = props_d.get(item, "acquise")
        props_b[item] = label
        props_d.pop(item, None)

        save_profile(donneur.id, prof_d)
        save_profile(beneficiaire.id, prof_b)

        await itx.response.send_message(
            f"🎁 **Transfert de propriété** — {donneur.mention} ➜ {beneficiaire.mention}\n"
            f"• Propriété : **{item}**"
        )
        return

    await itx.response.send_message("Catégorie inconnue.", ephemeral=True)

# --- Autocomplete des items possédés par le donneur ---
@give_item_cmd.autocomplete("item")
async def give_item_item_autocomplete(interaction: discord.Interaction, current: str):
    # Récupère la catégorie déjà sélectionnée dans la commande
    cat = getattr(interaction.namespace, "categorie", None)
    # Lorsque c’est un Choice, discord.py range directement la valeur (str)
    if isinstance(cat, app_commands.Choice):
        cat = cat.value
    if cat not in ("armes", "chevaux", "permis", "proprietes"):
        return []

    prof = load_profile(interaction.user.id) or {}
    inv  = (prof.get("inventaire") or {})
    inv.setdefault("armes", {}); inv.setdefault("chevaux", {}); inv.setdefault("permis", {})
    props = prof.get("proprietes", {}) or {}

    if cat in ("armes", "chevaux"):
        keys = list((inv[cat] or {}).keys())
    elif cat == "permis":
        keys = list((inv["permis"] or {}).keys())
    else:  # proprietes
        keys = list(props.keys())

    cur = (current or "").lower()
    if cur:
        keys = [k for k in keys if cur in k.lower()]

    keys.sort()
    return [app_commands.Choice(name=k, value=k) for k in keys[:25]]


# ========= JEU / RISQUE =========

CRIME_CHOICES = [
    app_commands.Choice(name="calèche",  value="calèche"),
    app_commands.Choice(name="commerce", value="commerce"),
    app_commands.Choice(name="train",    value="train"),
    app_commands.Choice(name="banque",   value="banque"),
]

@bot.tree.command(name="crime", description="Commettre un braquage (calèche, commerce, train, banque). Cooldown 4h.")
@app_commands.describe(cible="Type de cible : caleche, commerce, train, banque")
@app_commands.choices(cible=CRIME_CHOICES)
async def crime_cmd(itx: discord.Interaction, cible: app_commands.Choice[str]):
    target = itx.user
    prof = _ensure_profile_skeleton(target.id)
    prof = _ensure_economy_fields(prof)

    left = _cooldown_left(prof, "crime", COOLDOWN_CRIME_SECONDS)
    if left > 0:
        h = left // 3600; m = (left % 3600) // 60; s = left % 60
        await itx.response.send_message(
            f"⏳ Vous devrez patienter **{h}h {m}m {s}s** avant un nouveau braquage.",
            ephemeral=True
        )
        return

    MAX_BY_TARGET = {"caleche": 300, "commerce": 500, "train": 600, "banque": 700}
    typ = cible.value
    max_amt = MAX_BY_TARGET[typ]

    forced_negative = (random.randint(1, 4) == 1)  # 1/4 perte
    amount = -random.randint(0, max_amt) if forced_negative else random.randint(0, max_amt)

    prof["dirty"] = int(prof.get("dirty", 0)) + int(amount)
    _touch_cooldown(prof, "crime")
    save_profile(target.id, prof)

    signe = "+" if amount >= 0 else "−"
    abs_amt = abs(amount)
    emoji = "💰" if amount >= 0 else "🚨"
    extra = " (perte 1/4)" if forced_negative and amount < 0 else ""

    await itx.response.send_message(
        f"{emoji} **Braquage : {typ}**\n"
        f"Résultat : {signe}{_fmt_money(abs_amt)}{extra}\n"
        f"Argent sale (dirty) : **{_fmt_money(int(prof['dirty']))}**"
    )

@bot.tree.command(name="robb", description="Voler une partie du cash d'un joueur (0% à 70%). Cooldown 4h.")
@app_commands.describe(victime="Membre à détrousser (cash visé)")
async def robb_cmd(itx: discord.Interaction, victime: discord.Member):
    voleur = itx.user
    if victime.id == voleur.id:
        await itx.response.send_message("On ne se vole pas soi-même…", ephemeral=True)
        return

    prof_v = _ensure_profile_skeleton(victime.id)
    prof_v = _ensure_economy_fields(prof_v)
    prof_x = _ensure_profile_skeleton(voleur.id)
    prof_x = _ensure_economy_fields(prof_x)

    left = _cooldown_left(prof_x, "robb", COOLDOWN_ROBB_SECONDS)
    if left > 0:
        h = left // 3600; m = (left % 3600) // 60; s = left % 60
        await itx.response.send_message(
            f"⏳ Vous devrez patienter **{h}h {m}m {s}s** avant un nouveau vol.",
            ephemeral=True
        )
        return

    cash_v = int(prof_v.get("cash", 0))
    if cash_v <= 0:
        _touch_cooldown(prof_x, "robb")
        save_profile(voleur.id, prof_x)
        await itx.response.send_message(f"💁 {victime.display_name} n’a pas de cash à voler.")
        return

    pct = random.randint(0, 70)  # %
    montant = math.floor(cash_v * pct / 100)

    # 1/3 le voleur perd au lieu de gagner (va dans dirty négatif)
    backfire = (random.randint(1, 3) == 1)

    if montant > 0:
        if backfire:
            prof_x["dirty"] = int(prof_x["dirty"]) - montant
            result_text = f"💥 Mauvais coup ! Vous perdez **{_fmt_money(montant)}** en argent sale."
        else:
            prof_v["cash"]  = cash_v - montant
            prof_x["dirty"] = int(prof_x["dirty"]) + montant
            result_text = (
                f"🕵️ Vous dérobez **{_fmt_money(montant)}** à {victime.mention}.\n"
                f"→ Ajouté à votre **argent sale**."
            )
    else:
        result_text = "😶 Rien volé cette fois (0%)."

    _touch_cooldown(prof_x, "robb")
    save_profile(victime.id, prof_v)
    save_profile(voleur.id,  prof_x)

    await itx.response.send_message(
        f"**Vol sur {victime.mention}** — {pct}% du cash visé.\n{result_text}\n\n"
        f"Votre argent sale : **{_fmt_money(int(prof_x['dirty']))}**"
    )

@bot.tree.command(name="blanchiment", description="Blanchir 50% à 100% d'argent sale en cash (1/3 risque de tout perdre). Cooldown 4h.")
async def blanchiment_cmd(itx: discord.Interaction):
    user = itx.user
    prof = _ensure_profile_skeleton(user.id)
    prof = _ensure_economy_fields(prof)

    left = _cooldown_left(prof, "blanchiment", COOLDOWN_BLCH_SECONDS)
    if left > 0:
        h = left // 3600; m = (left % 3600) // 60; s = left % 60
        await itx.response.send_message(
            f"⏳ Vous devrez patienter **{h}h {m}m {s}s** avant un nouveau blanchiment.",
            ephemeral=True
        )
        return

    dirty = int(prof.get("dirty", 0))
    if dirty <= 0:
        await itx.response.send_message("Rien à blanchir : votre argent sale est nul ou négatif.", ephemeral=True)
        return

    busted = (random.randint(1, 3) == 1)  # 1/3 tout perdu
    if busted:
        prof["dirty"] = 0
        _touch_cooldown(prof, "blanchiment")
        save_profile(user.id, prof)
        await itx.response.send_message(
            f"🚨 Coup de filet ! Vous perdez **tout** votre argent sale.\n"
            f"Argent sale maintenant : **{_fmt_money(0)}**"
        )
        return

    rate = random.randint(50, 100)  # %
    gain = math.floor(dirty * rate / 100)
    prof["dirty"] = dirty - gain
    prof["cash"]  = int(prof.get("cash", 0)) + gain

    _touch_cooldown(prof, "blanchiment")
    save_profile(user.id, prof)

    await itx.response.send_message(
        f"🧼 Blanchiment à **{rate}%** : +{_fmt_money(gain)} en cash.\n"
        f"Argent sale restant : **{_fmt_money(int(prof['dirty']))}** • Cash : **{_fmt_money(int(prof['cash']))}**"
    )

COOLDOWN_WORK_SECONDS = 4 * 3600

@bot.tree.command(name="work", description="Simuler une vente / un travail (100 à 500 ₣). Cooldown 4h.")
async def work_cmd(itx: discord.Interaction):
    user = itx.user
    prof = _ensure_profile_skeleton(user.id)
    prof = _ensure_economy_fields(prof)

    # Vérif cooldown
    left = _cooldown_left(prof, "work", COOLDOWN_WORK_SECONDS)
    if left > 0:
        h = left // 3600; m = (left % 3600) // 60; s = left % 60
        await itx.response.send_message(
            f"⏳ Vous devrez patienter **{h}h {m}m {s}s** avant un nouveau travail.",
            ephemeral=True
        )
        return

    # Gain aléatoire
    gain = random.randint(100, 500)
    prof["bank"] = int(prof.get("bank", 0)) + gain

    # Active cooldown
    _touch_cooldown(prof, "work")
    save_profile(user.id, prof)

    await itx.response.send_message(
        f"🪙 Travail accompli !\n"
        f"Gain : **{_fmt_money(gain)}** ajouté à votre compte bancaire.\n"
        f"Nouveau solde banque : **{_fmt_money(prof['bank'])}**"
    )

# ========= LEADERBOARD =========

def _iter_all_profiles() -> List[Tuple[int, dict]]:
    entries: List[Tuple[int, dict]] = []
    try:
        for name in os.listdir(PROFILES_DIR):
            if not name.endswith(".json"):
                continue
            try:
                uid = int(os.path.splitext(name)[0])
            except Exception:
                continue
            pth = os.path.join(PROFILES_DIR, name)
            try:
                with open(pth, "r", encoding="utf-8") as f:
                    d = json.load(f)
                entries.append((uid, d))
            except Exception:
                continue
    except Exception:
        pass
    return entries

def _total_wealth(p: dict) -> int:
    cash  = int(p.get("cash", 0) or 0)
    bank  = int(p.get("bank", 0) or 0)
    dirty = int(p.get("dirty", 0) or 0)
    return cash + bank + dirty

class LeaderboardView(discord.ui.View):
    def __init__(self, entries: List[Tuple[int, dict]], page_size: int = 10, start_page: int = 0):
        super().__init__(timeout=120)
        self.entries = entries
        self.page_size = page_size
        self.page = start_page

    def _render_page(self) -> str:
        start = self.page * self.page_size
        end   = start + self.page_size
        slice_entries = self.entries[start:end]

        lines = []
        rank_offset = start
        for i, (uid, prof) in enumerate(slice_entries, start=1):
            rank = rank_offset + i
            total = _total_wealth(prof)
            tag = f"<@{uid}>"
            lines.append(f"{rank:>2}. {tag} — {_fmt_money(total)}")
        if not lines:
            lines = ["(Aucun profil sur cette page)"]
        return "\n".join(lines)

    async def update_msg(self, interaction: discord.Interaction):
        content = self._render_page()
        await interaction.response.edit_message(content=content, view=self)

    @discord.ui.button(label="◀ Précédent", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        await self.update_msg(interaction)

    @discord.ui.button(label="Suivant ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        max_page = max(0, (len(self.entries) - 1) // self.page_size)
        if self.page < max_page:
            self.page += 1
        await self.update_msg(interaction)

@bot.tree.command(name="leaderboard", description="Classement des fortunes (Total = cash + banque + argent sale).")
async def leaderboard_cmd(itx: discord.Interaction):
    entries = _iter_all_profiles()
    entries.sort(key=lambda t: _total_wealth(t[1]), reverse=True)
    view = LeaderboardView(entries, page_size=10, start_page=0)
    await itx.response.send_message(view._render_page(), view=view)

# ========= /COMA =========

@bot.tree.command(name="coma", description="Jet de coma après mort RP : issue et mémoire perdue (tirage équitable).")
async def coma_cmd(itx: discord.Interaction):
    outcomes = [
        ("🧠 Perte de mémoire", "Le personnage oublie **30 minutes** de RP et se réveille."),
        ("🧠 Perte de mémoire", "Le personnage oublie **15 minutes** de RP et se réveille."),
        ("✅ Réveil",           "Le personnage n’oublie rien et se réveille immédiatement.")
    ]
    titre, texte = random.choice(outcomes)
    emb = discord.Embed(
        title="COMA — Décision",
        description=f"**{titre}**\n{texte}",
        color=discord.Color.dark_gold()
    )
    emb.set_footer(text="À n’utiliser que si l’auteur de la mise à terre accepte le coma.")
    await itx.response.send_message(embed=emb)

# ========= /SESSION =========

# État en mémoire vive : message_id -> dict de participants
SESSIONS: Dict[int, dict] = {}

def _session_build_embed(state: dict, guild_logo_bytes: Optional[bytes]) -> Tuple[discord.Embed, Optional[discord.File]]:
    """
    state = {
        "titre": str|None,
        "date_str": "JJ/MM/AAAA",
        "heure_str": "HH:MM",
        "organizer_id": int,
        "organizer_psn": str,
        "created_at": datetime,
        "present": set[int],
        "maybe": set[int],
        "absent": set[int],
        "late": dict[int, Optional[int]],
        "message_id": int|None,
        "channel_id": int,
    }
    """
    header = "🎭 | Nouvelle session RP"
    if state.get("titre"):
        header += f"\n« {state['titre']} »"
    emb = discord.Embed(title=header, color=discord.Color.dark_gold())
    emb.description = "Veuillez voter ci-dessous !"

    org_id = state.get("organizer_id")
    org_mention = f"<@{org_id}>" if org_id else "—"
    psn = state.get("organizer_psn") or "—"
    date_str = state.get("date_str", "—")
    heure_str = state.get("heure_str", "—")

   emb.add_field(
    name="\u200b",  # caractère invisible
    value=f"👑 **Organisateur** : {org_mention}\n"
          f"⚜️ **PSN** : {psn}\n"
          f"🗓️ **Date** : {date_str}\n"
          f"⏰ **Heure de lancement** : {heure_str}",
    inline=False
)

    def list_mentions(uids: List[int]) -> str:
        if not uids:
            return "• —"
        parts = [f"• <@{u}>" for u in uids]
        return "\n".join(parts)

    def list_late(late_map: Dict[int, Optional[int]]) -> str:
        if not late_map:
            return "• —"
        items = []
        for uid, mins in sorted(late_map.items(), key=lambda kv: kv[0]):
            if mins is None:
                items.append(f"• <@{uid}>")
            else:
                items.append(f"• <@{uid}> (≈{mins} min)")
        return "\n".join(items)

    present_ids = sorted(list(state.get("present", set())))
    maybe_ids   = sorted(list(state.get("maybe", set())))
    absent_ids  = sorted(list(state.get("absent", set())))
    late_map    = dict(state.get("late", {}))

    emb.add_field(name=f"Membres présents ({len(present_ids)}) :", value=list_mentions(present_ids), inline=False)
    emb.add_field(name=f"Membres en retard ({len(late_map)}) :", value=list_late(late_map), inline=False)
    emb.add_field(name=f"Membres indécis ({len(maybe_ids)}) :", value=list_mentions(maybe_ids), inline=False)
    emb.add_field(name=f"Membres absents ({len(absent_ids)}) :", value=list_mentions(absent_ids), inline=False)

    emb.set_footer(
        text=f"Dernière mise à jour : {now_paris.strftime('%H:%M')}  •  ID session : #{state.get('message_id') or '—'}"
)

    # Miniature : logo guilde si dispo, sinon fallback assets/banque.png
    file_obj = None
    if guild_logo_bytes:
        file_obj = discord.File(io.BytesIO(guild_logo_bytes), filename="guild_icon.png")
        emb.set_thumbnail(url="attachment://guild_icon.png")
    else:
        fallback = os.path.join(ASSETS_DIR, "banque.png")
        if os.path.exists(fallback):
            file_obj = discord.File(fallback, filename="guild_icon.png")
            emb.set_thumbnail(url="attachment://guild_icon.png")

    return emb, file_obj

class SessionView(discord.ui.View):
    def __init__(self, message_id: Optional[int], channel_id: int):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.channel_id = channel_id

    async def refresh(self, interaction: discord.Interaction):
        state = SESSIONS.get(self.message_id)
        if not state:
            for child in self.children:
                child.disabled = True
            try:
                await interaction.response.edit_message(view=self)
            except Exception:
                pass
            return

        logo_bytes = None
        try:
            if interaction.guild and interaction.guild.icon:
                logo_bytes = await interaction.guild.icon.read()
        except Exception:
            logo_bytes = None

        emb, file_obj = _session_build_embed(state, logo_bytes)
        if interaction.response.is_done():
            try:
                await interaction.message.edit(embed=emb, attachments=[file_obj] if file_obj else [], view=self)
            except Exception:
                await interaction.followup.edit_message(interaction.message.id, embed=emb, attachments=[file_obj] if file_obj else [], view=self)
        else:
            await interaction.response.edit_message(embed=emb, attachments=[file_obj] if file_obj else [], view=self)

    @discord.ui.button(label="🟩 Présent", style=discord.ButtonStyle.success)
    async def present_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = SESSIONS.get(self.message_id)
        if not state:
            return await interaction.response.send_message("Session expirée.", ephemeral=True)
        uid = interaction.user.id
        state["maybe"].discard(uid)
        state["absent"].discard(uid)
        state["late"].pop(uid, None)
        state["present"].add(uid)
        await self.refresh(interaction)

    @discord.ui.button(label="🟨 En retard", style=discord.ButtonStyle.secondary)
    async def late_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RetardModal(self))

    @discord.ui.button(label="🟪 Peut-être", style=discord.ButtonStyle.primary)
    async def maybe_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = SESSIONS.get(self.message_id)
        if not state:
            return await interaction.response.send_message("Session expirée.", ephemeral=True)
        uid = interaction.user.id
        state["present"].discard(uid)
        state["absent"].discard(uid)
        state["late"].pop(uid, None)
        state["maybe"].add(uid)
        await self.refresh(interaction)

    @discord.ui.button(label="🟥 Absent", style=discord.ButtonStyle.danger)
    async def absent_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = SESSIONS.get(self.message_id)
        if not state:
            return await interaction.response.send_message("Session expirée.", ephemeral=True)
        uid = interaction.user.id
        state["present"].discard(uid)
        state["maybe"].discard(uid)
        state["late"].pop(uid, None)
        state["absent"].add(uid)
        await self.refresh(interaction)

class RetardModal(discord.ui.Modal, title="Indiquer votre retard (≈ minutes)"):
    def __init__(self, parent_view: SessionView):
        super().__init__(timeout=None)
        self.parent_view = parent_view
        self.minutes = discord.ui.TextInput(
            label="Environ combien de minutes de retard ?",
            placeholder="Ex : 10",
            required=True,
            max_length=3
        )
        self.add_item(self.minutes)

    async def on_submit(self, interaction: discord.Interaction):
        state = SESSIONS.get(self.parent_view.message_id)
        if not state:
            await interaction.response.send_message("Session expirée.", ephemeral=True)
            return
        uid = interaction.user.id
        state["present"].discard(uid)
        state["maybe"].discard(uid)
        state["absent"].discard(uid)
        txt = (self.minutes.value or "").strip()
        try:
            mins = int(txt) if txt else None
            if mins is not None and mins < 0:
                mins = None
        except Exception:
            mins = None
        state["late"][uid] = mins
        await self.parent_view.refresh(interaction)

@bot.tree.command(name="session", description="Créer une annonce de session RP avec votes.")
@app_commands.describe(
    date="Date (JJ/MM/AAAA)",
    heure="Heure (HH:MM)",
    organisateur="Organisateur (membre Discord)",
    psn="PSN de l’organisateur",
    titre="Titre optionnel (ex. « Expédition à Blackwater »)"
)
async def session_cmd(
    itx: discord.Interaction,
    date: str,
    heure: str,
    organisateur: discord.Member,
    psn: str,
    titre: Optional[str] = None
):
    await itx.response.defer()

    # Prépare l'état
    state = {
        "titre": (titre.strip() if titre else None),
        "date_str": date.strip(),
        "heure_str": heure.strip(),
        "organizer_id": organisateur.id,
        "organizer_psn": psn.strip(),
        "created_at": datetime.now(PARIS_TZ),
        "present": set(),
        "maybe": set(),
        "absent": set(),
        "late": {},
        "message_id": None,
        "channel_id": itx.channel.id,
    }

    # Logo guilde
    logo_bytes = None
    try:
        if itx.guild and itx.guild.icon:
            logo_bytes = await itx.guild.icon.read()
    except Exception:
        logo_bytes = None

    emb, file_obj = _session_build_embed(state, logo_bytes)
    view = SessionView(message_id=None, channel_id=itx.channel.id)

    # Ping @everyone automatiquement
    allowed = discord.AllowedMentions(everyone=True, users=True, roles=True)
    content = "@everyone"

    if file_obj:
        msg = await itx.followup.send(content=content, embed=emb, file=file_obj, view=view, allowed_mentions=allowed)
    else:
        msg = await itx.followup.send(content=content, embed=emb, view=view, allowed_mentions=allowed)

    # Finalise état + vue
    state["message_id"] = msg.id
    SESSIONS[msg.id] = state
    view.message_id = msg.id

    # Rééditer pour afficher l'ID en footer
    emb2, file_obj2 = _session_build_embed(state, logo_bytes)
    try:
        await msg.edit(embed=emb2, attachments=[file_obj2] if file_obj2 else [], view=view)
    except Exception:
        pass

# ========= SYNC & DÉMARRAGE =========

@bot.tree.command(name="sync", description="Forcer la synchronisation des commandes (admin conseillé).")
async def sync_cmd(itx: discord.Interaction):
    try:
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            await itx.response.send_message(f"✅ Sync guilde ({GUILD_ID}) : {len(synced)} commande(s).", ephemeral=True)
        else:
            synced = await bot.tree.sync()
            await itx.response.send_message(f"✅ Sync global : {len(synced)} commande(s). (peut prendre quelques minutes)", ephemeral=True)
    except Exception as e:
        await itx.response.send_message(f"❌ Erreur de sync : `{e}`", ephemeral=True)

@bot.event
async def setup_hook():
    try:
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
            print(f"[SYNC] Commandes copiées et synchronisées pour la guilde {GUILD_ID}.")
        else:
            await bot.tree.sync()
            print("[SYNC] Commandes synchronisées globalement (quelques minutes).")
    except Exception as e:
        print("[SYNC][ERREUR]", e)

# ========= PURGE DES DONNÉES À LA SORTIE DU SERVEUR =========
@bot.event
async def on_member_remove(member: discord.Member):
    try:
        # 1) Supprimer le profil JSON (le retire de facto du leaderboard)
        prof_path = profile_path_for(member.id)
        if os.path.exists(prof_path):
            os.remove(prof_path)

        # 2) Supprimer la carte PNG
        carte_path = card_path_for(member.id)
        if os.path.exists(carte_path):
            os.remove(carte_path)

        # 3) Nettoyer d'éventuelles photos temporaires
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            temp_photo = os.path.join(ASSETS_DIR, f"photo_{member.id}{ext}")
            if os.path.exists(temp_photo):
                try:
                    os.remove(temp_photo)
                except Exception:
                    pass

        print(f"[CLEANUP] Données purgées pour l’ex-membre {member} (ID {member.id}).")
    except Exception as e:
        print(f"[CLEANUP][ERREUR] Impossible de purger {member.id} : {e}")

@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user} (ID: {bot.user.id})")
    # Démarre la sauvegarde automatique si ce n'est pas déjà le cas
    if not auto_backup.is_running():
        auto_backup.start()

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("TOKEN manquant dans .env (UTF-8)")
    bot.run(TOKEN)






