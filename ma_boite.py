"""
Ma Boîte — jeu de simulation de création d'entreprise, face à des concurrents.

Lancer :  python ma_boite.py      (rien à installer : tkinter est fourni avec Python)
Le fichier moteur.py doit être dans le même dossier.

Créez votre entreprise dans l'un des 8 secteurs (industrie, SaaS, biotech, jeu vidéo, luxe, aéronautique,
distribution, énergie), chacun avec son modèle économique, puis dirigez-la mois par mois pendant 3, 5 ou 8 ans
face à des concurrents pilotés par l'ordinateur. Raccourci : Entrée = mois suivant.
"""
import math
import os
import pickle
import re
import time
import tkinter as tk
import unicodedata
from datetime import datetime
from pathlib import Path
from tkinter import filedialog

import moteur as M

PIL_DISPONIBLE = False
Image = ImageDraw = ImageFont = ImageTk = None


def charger_pil():
    """Importe Pillow (bibliothèque d'images) s'il est installé ; renvoie True si c'est le cas."""
    global PIL_DISPONIBLE, Image, ImageDraw, ImageFont, ImageTk
    try:
        import importlib
        importlib.invalidate_caches()
        from PIL import Image, ImageDraw, ImageFont, ImageTk
        PIL_DISPONIBLE = True
    except ImportError:
        PIL_DISPONIBLE = False
    return PIL_DISPONIBLE


charger_pil()

DOSSIER_SAUVEGARDES = Path(__file__).resolve().parent / "sauvegardes"
VERSION_SAUVEGARDE = 6
DUREE_JEU = {"n": 36}      # durée de la partie en cours (mois)

# ---------------------------------------------------------------- thème sombre
FOND, BARRE = "#050505", "#000000"
PANNEAU, PANNEAU2, BORD = "#121212", "#1e1e1e", "#2a2a2a"
TXT, MUT, DISCRET = "#f2f2f2", "#9e9e9e", "#616161"
ACC, ACC_SURVOL = "#3b82f6", "#60a5fa"
VERT, ROUGE, AMBRE, VIOLET = "#34d399", "#f87171", "#fbbf24", "#22d3ee"
GRILLE = "#1f1f1f"
POLICE = "Segoe UI"


def police(taille=10, gras=False):
    return (POLICE, taille, "bold") if gras else (POLICE, taille)


def euros(x, signe=False):
    return M.fmt(x, signe)


def prix_txt(p, secteur=None):
    if p < 100 and abs(p - round(p)) > 1e-9:
        return f"{p:.2f} €".replace(".", ",")
    return M.fmt(p)


def court(x, signe=False):
    """Montant lisible : euros exacts jusqu'à 100 000 €, puis k€ / M€."""
    return M.fmt_c(x, signe) if abs(x) >= 100_000 else euros(x, signe)


def pas_montant(v, mini=1_000):
    """Pas de curseur adapté à l'ordre de grandeur d'un montant."""
    if v <= 0:
        return mini
    return int(max(mini, 10 ** max(0, int(math.log10(v)) - 2)))


def budgets_conseilles(j):
    """Budgets marketing / qualité qu'adopterait un concurrent « équilibré » à votre place."""
    st = j.strategie
    j.strategie = M.STRATEGIES["equilibre"]
    try:
        return j.act.budgets_ia(1.0)
    except Exception:
        return 0.0, 0.0
    finally:
        j.strategie = st


def pct(x, signe=False):
    s = f"{x * 100:+.0f} %" if signe else f"{x * 100:.0f} %"
    return s.replace("-", "−")


def couleur_note(v, inverse=False):
    if inverse:
        return ROUGE if v > 100 else AMBRE if v > 85 else VERT
    return ROUGE if v < 30 else AMBRE if v < 50 else VERT


def fichier_sauvegarde(nom, cle_secteur):
    base = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_") or "partie"
    return DOSSIER_SAUVEGARDES / f"{base}_{cle_secteur}.sav"


def lire_entete(fichier):
    """Lit seulement l'en-tête d'une sauvegarde (nom, secteur, mois…), sans charger toute la partie."""
    try:
        with open(fichier, "rb") as h:
            meta = pickle.load(h)
        return meta if isinstance(meta, dict) else None
    except Exception:
        return None


def lister_sauvegardes():
    if not DOSSIER_SAUVEGARDES.exists():
        return []
    res = []
    for f in DOSSIER_SAUVEGARDES.glob("*.sav"):
        meta = lire_entete(f)
        if meta:
            meta["fichier"] = f
            res.append(meta)
    return sorted(res, key=lambda m: m.get("horodatage", 0), reverse=True)


# ---------------------------------------------------------------- composants
class Bouton(tk.Label):
    STYLES = {"primaire": (ACC, ACC_SURVOL, "white"), "secondaire": (PANNEAU2, "#2c2c2c", TXT),
              "fantome": (PANNEAU, PANNEAU2, MUT), "vert": ("#1f9d6e", "#27b981", "white"),
              "danger": ("#2a1414", "#3d1a1a", ROUGE)}

    def __init__(self, parent, texte, commande=None, style="secondaire", taille=10, padx=14, pady=7, **kw):
        self.fond, self.survol, self.encre = self.STYLES[style]
        super().__init__(parent, text=texte, bg=self.fond, fg=self.encre, font=police(taille, True),
                         padx=padx, pady=pady, cursor="hand2", **kw)
        self.commande, self.actif = commande, True
        self.bind("<Enter>", lambda _: self.actif and self.config(bg=self.survol))
        self.bind("<Leave>", lambda _: self.config(bg=self.fond if self.actif else "#1a1a1a"))
        self.bind("<Button-1>", lambda _: self.actif and self.commande and self.commande())

    def activer(self, oui=True):
        self.actif = oui
        self.config(bg=self.fond if oui else "#1a1a1a", fg=self.encre if oui else DISCRET,
                    cursor="hand2" if oui else "arrow")


class Carte(tk.Frame):
    def __init__(self, parent, titre=None, sous_titre=None, padx=16, pady=12, **kw):
        super().__init__(parent, bg=PANNEAU, highlightthickness=1, highlightbackground=BORD, padx=padx, pady=pady, **kw)
        if titre:
            tk.Label(self, text=titre, font=police(12, True), bg=PANNEAU, fg=TXT).pack(anchor="w")
        if sous_titre:
            st = tk.Label(self, text=sous_titre, font=police(9), bg=PANNEAU, fg=MUT, wraplength=700, justify="left",
                          anchor="w")
            st.pack(anchor="w", fill="x")
            self.bind("<Configure>", lambda e: st.config(wraplength=max(200, e.width - 2 * padx - 6)), add="+")
        if titre or sous_titre:
            tk.Frame(self, bg=PANNEAU, height=8).pack()


class Tuile(tk.Frame):
    """Indicateur clé : titre, grande valeur, variation et mini-courbe."""

    def __init__(self, parent, titre):
        super().__init__(parent, bg=PANNEAU, highlightthickness=1, highlightbackground=BORD, padx=14, pady=10)
        self.l_titre = tk.Label(self, text=titre.upper(), font=police(8, True), bg=PANNEAU, fg=MUT, anchor="w")
        self.l_titre.pack(anchor="w", fill="x")
        self.valeur = tk.Label(self, font=police(16, True), bg=PANNEAU, fg=TXT, text="—")
        self.valeur.pack(anchor="w")
        bas = tk.Frame(self, bg=PANNEAU)
        bas.pack(fill="x")
        self.delta = tk.Label(bas, font=police(8, True), bg=PANNEAU, fg=MUT, text=" ")
        self.delta.pack(side="left")
        self.courbe = tk.Canvas(bas, width=70, height=26, bg=PANNEAU, highlightthickness=0)
        self.courbe.pack(side="right")

    def maj(self, valeur, couleur_valeur=TXT, delta="", couleur_delta=MUT, serie=(), couleur=ACC, titre=None):
        if titre:
            self.l_titre.config(text=titre.upper())
        self.valeur.config(text=valeur, fg=couleur_valeur)
        self.delta.config(text=delta or " ", fg=couleur_delta)
        c = self.courbe
        c.delete("all")
        serie = list(serie)[-14:]
        if len(serie) >= 2:
            lo, hi = min(serie), max(serie)
            ecart = (hi - lo) or 1
            pts = []
            for i, v in enumerate(serie):
                pts += [3 + i * 62 / (len(serie) - 1), 23 - (v - lo) / ecart * 20]
            c.create_line(*pts, fill=couleur, width=2, smooth=True)
            c.create_oval(pts[-2] - 2.5, pts[-1] - 2.5, pts[-2] + 2.5, pts[-1] + 2.5, fill=couleur, outline="")


class Anneau(tk.Canvas):
    """Jauge circulaire."""

    def __init__(self, parent, titre, taille=84):
        super().__init__(parent, width=taille + 44, height=taille + 20, bg=PANNEAU, highlightthickness=0)
        self.t, self.titre = taille, titre

    def maj(self, v, texte, couleur):
        self.delete("all")
        t, m, o = self.t, 8, 22
        self.create_oval(o + m, m, o + t - m, t - m, outline=PANNEAU2, width=8)
        part = max(0.0, min(1.0, v / 100))
        if part > 0:
            self.create_arc(o + m, m, o + t - m, t - m, start=90, extent=-359.9 * part, style="arc",
                            outline=couleur, width=8)
        self.create_text(o + t / 2, t / 2, text=texte, fill=TXT, font=police(12, True))
        self.create_text(o + t / 2, t + 9, text=self.titre, fill=MUT, font=police(9))


class Segments(tk.Frame):
    """Choix exclusif sous forme de boutons accolés."""

    def __init__(self, parent, options, valeur, commande=None):
        super().__init__(parent, bg=PANNEAU2, padx=3, pady=3)
        self.var, self.boutons, self.commande = valeur, {}, commande
        for val, lib in options:
            b = tk.Label(self, text=lib, font=police(10, True), padx=12, pady=5, cursor="hand2")
            b.pack(side="left", padx=1)
            b.bind("<Button-1>", lambda _, v=val: self.choisir(v))
            self.boutons[val] = b
        self.peindre()

    def choisir(self, v):
        self.var.set(v)
        self.peindre()
        if self.commande:
            self.commande()

    def peindre(self):
        for v, b in self.boutons.items():
            actif = v == self.var.get()
            b.config(bg=ACC if actif else PANNEAU2, fg="white" if actif else MUT)


def curseur(parent, titre, var, mini, maxi, pas, fmt, rappel=None, fond=PANNEAU):
    ligne = tk.Frame(parent, bg=fond)
    ligne.pack(fill="x", pady=(10, 0))
    tk.Label(ligne, text=titre, font=police(10, True), bg=fond, fg=TXT).pack(side="left")
    val = tk.Label(ligne, text=fmt(var.get()), font=police(11, True), bg=fond, fg=ACC)
    val.pack(side="right")

    def changer(v):
        val.config(text=fmt(v))
        if rappel:
            rappel()
    tk.Scale(parent, from_=mini, to=maxi, resolution=pas, orient="horizontal", variable=var, showvalue=False,
             bg=ACC, fg=TXT, troughcolor="#2c2c2c", activebackground=ACC_SURVOL, highlightthickness=0, bd=0,
             sliderrelief="flat", sliderlength=16, width=12, cursor="hand2", command=changer
             ).pack(fill="x", pady=(5, 0))
    return val


# ---------------------------------------------------------------- graphiques
def axes(c, w, h, g, d, t, b, vmin, vmax, fmt_val, n=None):
    n = n or DUREE_JEU["n"]
    y = lambda val: t + (h - t - b) * (vmax - val) / ((vmax - vmin) or 1)
    for k in range(5):
        val = vmin + (vmax - vmin) * k / 4
        c.create_line(g, y(val), w - d, y(val), fill=GRILLE)
        c.create_text(g - 8, y(val), text=fmt_val(val), anchor="e", fill=MUT, font=police(8))
    largeur = (w - g - d) / n
    for i in range(0, n, 6 if n <= 36 else 12):
        c.create_text(g + (i + 0.5) * largeur, h - b + 13, text=f"mois {i + 1}", fill=MUT, font=police(8))
    return y, largeur


def legende(c, x, y, items, w):
    x0 = x
    for coul, lib, gras in items:
        it = c.create_text(x + 16, y + 5, text=lib, anchor="w", fill=TXT, font=police(9, gras))
        x1 = c.bbox(it)[2]
        if x1 > w - 10 and x > x0:
            x, y = x0, y + 17
            c.coords(it, x + 16, y + 5)
            x1 = c.bbox(it)[2]
        c.create_oval(x, y, x + 10, y + 10, fill=coul, outline="")
        x = x1 + 18
    return y


def graphe_finances(c, hist):
    c.delete("all")
    w, h = max(c.winfo_width(), 300), max(c.winfo_height(), 180)
    if not hist:
        c.create_text(w / 2, h / 2, text="Vos courbes apparaîtront après le premier mois.", fill=MUT, font=police(10))
        return
    g, d, t, b = 84, 12, 34, 26
    cas = [x["ca"] for x in hist]
    res = [x["resultat"] for x in hist]
    tre = [x["tresorerie"] for x in hist]
    vmax = max(max(cas), max(tre), 1)
    vmin = min(0, min(tre), min(res))
    y, lg = axes(c, w, h, g, d, t, b, vmin, vmax, lambda v: M.fmt_c(v))
    c.create_line(g, y(0), w - d, y(0), fill="#474747")
    for i, (ca, r) in enumerate(zip(cas, res)):
        x0 = g + i * lg + 2
        c.create_rectangle(x0, y(ca), x0 + lg - 4, y(0), fill="#343434", outline="")
        c.create_rectangle(x0 + lg * 0.3, y(max(r, 0)), x0 + lg * 0.7 - 4, y(min(r, 0)),
                           fill=VERT if r >= 0 else ROUGE, outline="")
    pts = [v for i, x in enumerate(tre) for v in (g + (i + 0.5) * lg, y(x))]
    if len(pts) >= 4:
        c.create_line(*pts, fill=ACC, width=2.5, smooth=True)
    c.create_oval(pts[-2] - 4, pts[-1] - 4, pts[-2] + 4, pts[-1] + 4, fill=ACC, outline=PANNEAU, width=2)
    legende(c, g, 6, [("#343434", "Chiffre d'affaires", False), (VERT, "Résultat", False),
                      (ACC, "Trésorerie", False)], w)


def graphe_parts(c, entreprises):
    c.delete("all")
    w, h = max(c.winfo_width(), 300), max(c.winfo_height(), 160)
    if not entreprises[0].historique:
        c.create_text(w / 2, h / 2, text="Les parts de marché apparaîtront après le premier mois.", fill=MUT,
                      font=police(10))
        return
    items = [(e.couleur if e.actif else DISCRET, ("★ " if e.joueur else "") + e.nom, e.joueur) for e in entreprises]
    y_leg = legende(c, 54, 6, items, w)
    g, d, t, b = 54, 12, y_leg + 26, 26
    haut = max(0.5, max((x["part"] for e in entreprises for x in e.historique), default=0.5) * 1.1)
    y, lg = axes(c, w, h, g, d, t, b, 0, haut, lambda v: pct(v))
    for e in sorted(entreprises, key=lambda e: e.joueur):
        pts = []
        for i, x in enumerate(e.historique):
            if x.get("absent"):
                continue
            if not e.actif and x["ventes"] == 0 and x["part"] == 0 and pts:
                break
            pts += [g + (i + 0.5) * lg, y(x["part"])]
        if len(pts) >= 4:
            c.create_line(*pts, fill=e.couleur, width=3.5 if e.joueur else 2, smooth=True)
        if pts:
            c.create_oval(pts[-2] - 3.5, pts[-1] - 3.5, pts[-2] + 3.5, pts[-1] + 3.5, fill=e.couleur, outline="")


# ---------------------------------------------------------------- états financiers
COULEURS_NOTE = {"A": VERT, "B": "#86efac", "C": AMBRE, "D": "#fb923c", "E": ROUGE}

LIGNES_CR = [
    ("ca", "Chiffre d'affaires", "total"),
    ("achats", "Achats consommés", ""),
    ("marge_brute", "Marge brute", "total"),
    ("subventions", "Subventions d'exploitation", ""),
    ("salaires", "Salaires et charges (dont votre rémunération)", ""),
    ("loyer", "Loyer", ""),
    ("operations", "Coûts d'exploitation", ""),
    ("marketing", "Marketing", ""),
    ("qualite", "Qualité, R&D et développement", ""),
    ("credit_bail", "Loyers de crédit-bail", ""),
    ("divers", "Frais généraux (assurances, comptable, recrutement…)", ""),
    ("impayes", "Factures clients impayées", ""),
    ("ebe", "Excédent brut d'exploitation (EBE)", "total"),
    ("dotations", "Dotations aux amortissements", ""),
    ("rex", "Résultat d'exploitation", "total"),
    ("produits_fin", "Produits financiers (placements)", ""),
    ("charges_fin", "Charges financières (intérêts, agios, frais)", ""),
    ("rcai", "Résultat courant avant impôt", "total"),
    ("exceptionnel", "Résultat exceptionnel", ""),
    ("impot", "Impôt sur les sociétés (net du crédit d'impôt)", ""),
    ("net", "Résultat net", "grand"),
]
PRODUITS = {"ca", "subventions", "produits_fin", "exceptionnel"}

LIGNES_FLUX = [
    ("clients", "Encaissements clients"), ("fournisseurs", "Paiements fournisseurs"),
    ("salaires", "Salaires versés"), ("charges", "Loyers, exploitation, marketing, R&D et frais"),
    ("impots", "Impôt sur les sociétés"), ("financier", "Intérêts, agios et frais bancaires"),
    ("exceptionnel", "Opérations exceptionnelles"), ("subventions", "Subventions reçues"),
    ("investissements", "Investissements"), ("acquisitions", "Rachats d'entreprises (net de leur trésorerie)"),
    ("placements", "Placements (versés − récupérés)"),
    ("emprunts", "Emprunts obtenus"), ("remboursements", "Remboursements d'emprunts"),
    ("levees", "Apports et levées de fonds"), ("dividendes", "Dividendes versés"),
]


def valeurs_cr(pl):
    """Lignes du compte de résultat, charges en négatif."""
    sd = M.soldes(pl)
    v = {}
    for cle, _, _ in LIGNES_CR:
        if cle in sd:
            v[cle] = sd[cle]
        elif cle in PRODUITS:
            v[cle] = pl[cle]
        else:
            v[cle] = -pl[cle]
    return v


MOIS_COURTS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def date_courte(d):
    """« septembre 2028 » → « sept. 28 »."""
    try:
        mois, an = d.split()
        return f"{MOIS_COURTS[M.MOIS_NOMS.index(mois)]} {an[-2:]}"
    except ValueError:
        return d


def etoiles(talent):
    n = max(1, min(5, 1 + round((talent - 0.85) / 0.1)))
    return "★" * n + "☆" * (5 - n)


def montant_txt(v):
    return "—" if abs(v) < 0.5 else euros(v)


def tableau(parent, entetes, lignes, fond=PANNEAU):
    """Tableau de montants. lignes : (libellé, valeurs, style) avec style « », « total », « grand » ou « section » ;
    une valeur peut être un nombre (montant) ou un texte."""
    t = tk.Frame(parent, bg=fond)
    n = len(entetes)
    for c, e in enumerate(entetes):
        tk.Label(t, text=e, font=police(8, True), bg=fond, fg=MUT, justify="right").grid(
            row=0, column=c, sticky="w" if c == 0 else "e", padx=(0 if c == 0 else 16, 0), pady=(0, 4))
    t.columnconfigure(0, weight=1)
    r = 1
    for lib, vals, style in lignes:
        if style in ("total", "grand"):
            tk.Frame(t, bg=BORD if style == "total" else "#454545", height=1).grid(row=r, column=0, columnspan=n,
                                                                                  sticky="ew", pady=1)
            r += 1
        gras = style in ("total", "grand", "section")
        f = police(11 if style == "grand" else 10, gras)
        coul = MUT if style == "section" else TXT if gras else "#cfcfcf"
        tk.Label(t, text=lib, font=f, bg=fond, fg=coul, anchor="w").grid(row=r, column=0, sticky="w")
        for c, v in enumerate(vals, 1):
            if isinstance(v, (int, float)):
                txt = montant_txt(v)
                fg = (DISCRET if abs(v) < 0.5 else ROUGE if v < 0 and gras else
                      VERT if style == "grand" else coul)
            else:
                txt, fg = (v or ""), MUT
            tk.Label(t, text=txt, font=f, bg=fond, fg=fg, anchor="e").grid(row=r, column=c, sticky="e",
                                                                          padx=(16, 0))
        r += 1
    return t


def texte_libre(parent, texte, couleur=MUT, taille=9, largeur=900, fond=PANNEAU, **pack):
    l = tk.Label(parent, text=texte, font=police(taille), bg=fond, fg=couleur, justify="left", anchor="w",
                 wraplength=largeur)
    l.pack(anchor="w", **pack)
    return l


def graphe_bilan(c, b):
    """Deux colonnes empilées : ce que possède l'entreprise (actif) et comment c'est financé (passif)."""
    c.delete("all")
    w, h = max(c.winfo_width(), 220), max(c.winfo_height(), 260)
    a, p = b["actif"], b["passif"]
    cp = p["capital"] + p["reserves"] + p["resultat"]
    actif = [("Immobilisé", a["immos"] + a["goodwill"], "#6366f1"),
             ("Stocks et encours", a["stocks"] + a["encours"], "#a78bfa"),
             ("Créances", a["creances"] + a["etat"], AMBRE),
             ("Placements", a["placements"], VIOLET), ("Banque", a["disponibilites"], VERT)]
    passif = [("Fonds propres", max(0.0, cp), ACC), ("Emprunts", p["emprunts"] + p["decouvert"], ROUGE),
              ("Acomptes reçus", p["avances"], "#f9a8d4"),
              ("Fournisseurs", p["fournisseurs"] + p["fiscal"], "#a3a3a3")]
    tot = max(sum(v for _, v, _ in actif), sum(v for _, v, _ in passif), 1)
    haut, bas = 26, 30
    ech = (h - haut - bas) / tot
    larg = min(90, (w - 60) / 2)
    for k, (titre, parts) in enumerate((("ACTIF", actif), ("PASSIF", passif))):
        x0 = w / 2 - larg - 10 if k == 0 else w / 2 + 10
        c.create_text(x0 + larg / 2, 10, text=titre, fill=MUT, font=police(8, True))
        y = h - bas
        for lib, v, coul in parts:
            if v <= 0:
                continue
            y1 = y - v * ech
            c.create_rectangle(x0, y1, x0 + larg, y, fill=coul, outline=PANNEAU, width=2)
            if y - y1 >= 28:
                c.create_text(x0 + larg / 2, (y + y1) / 2 - 7, text=lib, fill="#0b0b0b", font=police(8, True),
                              width=larg - 6)
                c.create_text(x0 + larg / 2, (y + y1) / 2 + 8, text=M.fmt_c(v), fill="#0b0b0b",
                              font=police(8))
            elif y - y1 >= 13:
                c.create_text(x0 + larg / 2, (y + y1) / 2, text=lib, fill="#0b0b0b", font=police(7, True))
            y = y1
    if cp < 0:
        c.create_text(w / 2, h - 12, text=f"Capitaux propres négatifs : {euros(cp)}", fill=ROUGE, font=police(8, True))
    else:
        c.create_text(w / 2, h - 12, text=f"Total : {euros(b['total_actif'])} de chaque côté", fill=MUT,
                      font=police(8))


def graphe_cascade(c, h):
    """Cascade : de la trésorerie de début de mois à celle de fin de mois."""
    c.delete("all")
    w, ht = max(c.winfo_width(), 260), max(c.winfo_height(), 240)
    if not h:
        c.create_text(w / 2, ht / 2, text="La cascade apparaîtra après le premier mois.", fill=MUT, font=police(10))
        return
    f = h["flux"]
    etapes = [("Début", h["tresorerie_debut"], "base"), ("Clients", f["clients"], ""),
              ("Fourn.", f["fournisseurs"], ""), ("Salaires", f["salaires"], ""), ("Charges", f["charges"], ""),
              ("Autres", f["impots"] + f["financier"] + f["exceptionnel"] + f["subventions"], ""),
              ("Invest.", sum(f[k] for k in M.FLUX_INVESTISSEMENT), ""),
              ("Financ.", sum(f[k] for k in M.FLUX_FINANCEMENT), ""), ("Fin", h["tresorerie"], "base")]
    niveaux, cumul = [], 0.0
    for lib, v, t in etapes:
        if t == "base":
            niveaux.append((lib, 0.0, v, t))
            cumul = v
        else:
            niveaux.append((lib, cumul, cumul + v, t))
            cumul += v
    vmin = min(0.0, *(min(a, b) for _, a, b, _ in niveaux))
    vmax = max(1.0, *(max(a, b) for _, a, b, _ in niveaux))
    g, d, t_, b_ = 56, 8, 12, 34
    y = lambda v: t_ + (ht - t_ - b_) * (vmax - v) / ((vmax - vmin) or 1)
    for k in range(5):
        val = vmin + (vmax - vmin) * k / 4
        c.create_line(g, y(val), w - d, y(val), fill=GRILLE)
        c.create_text(g - 6, y(val), text=M.fmt_c(val), anchor="e", fill=MUT,
                      font=police(7))
    c.create_line(g, y(0), w - d, y(0), fill="#474747")
    lg = (w - g - d) / len(niveaux)
    for i, (lib, a, bb, t) in enumerate(niveaux):
        x0 = g + i * lg + 4
        coul = ACC if t == "base" else VERT if bb >= a else ROUGE
        if abs(bb - a) < 1 and t != "base":
            c.create_line(x0, y(a), x0 + lg - 8, y(a), fill=DISCRET)
        else:
            c.create_rectangle(x0, y(max(a, bb)), x0 + lg - 8, y(min(a, bb)), fill=coul, outline="")
        if i < len(niveaux) - 1:
            c.create_line(x0 + lg - 8, y(bb), x0 + lg + 4, y(bb), fill="#555555", dash=(2, 2))
        c.create_text(x0 + (lg - 8) / 2, ht - b_ + 10, text=lib, fill=MUT, font=police(7))


def graphe_prev(c, hist, proj, decouvert):
    """Trésorerie passée (6 derniers mois) et projetée (6 prochains mois)."""
    c.delete("all")
    w, h = max(c.winfo_width(), 300), max(c.winfo_height(), 200)
    passe = [(x.get("date", ""), x["tresorerie"]) for x in hist if "pl" in x][-6:]
    futur = [(x["date"], x["tresorerie"]) for x in proj]
    points = passe + futur
    if not points:
        c.create_text(w / 2, h / 2, text="Le prévisionnel apparaîtra après le premier mois.", fill=MUT, font=police(10))
        return
    vals = [v for _, v in points]
    vmin = min(0.0, min(vals), -decouvert) * 1.1
    vmax = max(1.0, max(vals)) * 1.1
    g, d, t, b = 70, 14, 30, 30
    y = lambda v: t + (h - t - b) * (vmax - v) / ((vmax - vmin) or 1)
    for k in range(5):
        val = vmin + (vmax - vmin) * k / 4
        c.create_line(g, y(val), w - d, y(val), fill=GRILLE)
        c.create_text(g - 8, y(val), text=M.fmt_c(val), anchor="e", fill=MUT,
                      font=police(8))
    n = max(12, len(points))
    lg = (w - g - d) / n
    x = lambda i: g + (i + 0.5) * lg
    if len(passe) < len(points):
        xs = x(len(passe) - 0.5)
        c.create_rectangle(xs, t, w - d, h - b, fill="#0d1526", outline="")
        c.create_text(xs + 6, t + 8, text="PRÉVISION", anchor="w", fill=ACC, font=police(8, True))
    c.create_line(g, y(0), w - d, y(0), fill="#474747")
    if decouvert > 0:
        c.create_line(g, y(-decouvert), w - d, y(-decouvert), fill=ROUGE, dash=(4, 3))
        c.create_text(w - d - 4, y(-decouvert) - 8, text="limite du découvert autorisé", anchor="e", fill=ROUGE,
                      font=police(8))
    for i, (date, v) in enumerate(points):
        if i % 2 == 0 or len(points) <= 8:
            c.create_text(x(i), h - b + 13, text=date_courte(date), fill=MUT, font=police(8))
    pts_p = [v for i, (_, val) in enumerate(passe) for v in (x(i), y(val))]
    if len(pts_p) >= 4:
        c.create_line(*pts_p, fill=ACC, width=2.5)
    if futur:
        depart = [x(len(passe) - 1), y(passe[-1][1])] if passe else []
        pts_f = depart + [v for i, (_, val) in enumerate(futur, len(passe)) for v in (x(i), y(val))]
        if len(pts_f) >= 4:
            c.create_line(*pts_f, fill=ACC_SURVOL, width=2.5, dash=(6, 4))
    for i, (_, val) in enumerate(points):
        coul = ROUGE if val < 0 else ACC
        c.create_oval(x(i) - 3.5, y(val) - 3.5, x(i) + 3.5, y(val) + 3.5, fill=coul, outline=PANNEAU)
    legende(c, g, 6, [(ACC, "Trésorerie réelle", False), (ACC_SURVOL, "Prévision (décisions actuelles)", False)], w)


# ---------------------------------------------------------------- petits composants des pages d'activité
COUL_K = {"vert": VERT, "rouge": ROUGE, None: TXT}


def mini_kpi(parent, titre, valeur, detail="", couleur=TXT, fond=PANNEAU):
    c = tk.Frame(parent, bg=fond, highlightthickness=1, highlightbackground=BORD, padx=12, pady=8)
    tk.Label(c, text=titre.upper(), font=police(8, True), bg=fond, fg=MUT).pack(anchor="w")
    tk.Label(c, text=valeur, font=police(14, True), bg=fond, fg=couleur).pack(anchor="w")
    if detail:
        tk.Label(c, text=detail, font=police(8), bg=fond, fg=MUT, wraplength=220, justify="left").pack(anchor="w")
    return c


def rangee_kpis(parent, items):
    """Une rangée d'indicateurs : items = [(titre, valeur, détail, couleur)]."""
    r = tk.Frame(parent, bg=FOND)
    for i, (titre, valeur, detail, couleur) in enumerate(items):
        mini_kpi(r, titre, valeur, detail, couleur).grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
        r.columnconfigure(i, weight=1, uniform="k")
    return r


def barre(parent, valeur, largeur=150, hauteur=8, couleur=ACC, fond=PANNEAU2, repere=None):
    """Barre de progression (valeur entre 0 et 1, au-delà : la barre déborde en vert)."""
    c = tk.Canvas(parent, width=largeur, height=hauteur, bg="#2c2c2c", highlightthickness=0)
    v = max(0.0, valeur)
    c.create_rectangle(0, 0, largeur * min(1.0, v), hauteur, fill=couleur if v < 1 else VERT, outline="")
    if repere is not None and 0 < repere < 1.5:
        x = largeur * min(1.0, repere)
        c.create_line(x, 0, x, hauteur, fill=AMBRE, width=2)
    return c


def graphe_series(c, series, fmt_val, ref=None, lib_ref="", barres=None, dates=None):
    """Courbes mensuelles : series = [(libellé, valeurs, couleur)] ; barres = (libellé, valeurs, couleur) en fond ;
    ref = valeur d'une ligne de repère en pointillés."""
    c.delete("all")
    w, h = max(c.winfo_width(), 300), max(c.winfo_height(), 160)
    toutes = [v for _, vals, _ in series for v in vals] + (list(barres[1]) if barres else [])
    if not toutes:
        c.create_text(w / 2, h / 2, text="Les courbes apparaîtront après le premier mois.", fill=MUT, font=police(10))
        return
    n = max(len(vals) for _, vals, _ in series) if series else len(barres[1])
    vmin = min(0.0, min(toutes), ref if ref is not None else 0)
    vmax = max(max(toutes), ref if ref is not None else 0, 1e-9) * 1.12
    items = [(coul, lib, False) for lib, _, coul in series] + ([(barres[2], barres[0], False)] if barres else [])
    y_leg = legende(c, 70, 6, items, w)
    g, d, t, b = 70, 12, y_leg + 24, 24
    y = lambda v: t + (h - t - b) * (vmax - v) / ((vmax - vmin) or 1)
    for k in range(5):
        val = vmin + (vmax - vmin) * k / 4
        c.create_line(g, y(val), w - d, y(val), fill=GRILLE)
        c.create_text(g - 8, y(val), text=fmt_val(val), anchor="e", fill=MUT, font=police(8))
    lg = (w - g - d) / max(1, n)
    if dates:
        pas = max(1, n // 8, math.ceil(58 / lg))
        for i in range(0, n, pas):
            c.create_text(g + (i + 0.5) * lg, h - b + 12, text=date_courte(dates[i]) if i < len(dates) else "",
                          fill=MUT, font=police(7))
    if barres:
        for i, v in enumerate(barres[1]):
            x0 = g + i * lg + 2
            c.create_rectangle(x0, y(max(v, 0)), x0 + lg - 4, y(min(v, 0)), fill=barres[2], outline="")
    if ref is not None:
        c.create_line(g, y(ref), w - d, y(ref), fill=AMBRE, dash=(4, 3))
        if lib_ref:
            c.create_text(w - d - 4, y(ref) - 8, text=lib_ref, anchor="e", fill=AMBRE, font=police(8))
    for lib, vals, coul in series:
        pts = [v for i, x in enumerate(vals) for v in (g + (i + 0.5) * lg, y(x))]
        if len(pts) >= 4:
            c.create_line(*pts, fill=coul, width=2.5)
        if pts:
            c.create_oval(pts[-2] - 3.5, pts[-1] - 3.5, pts[-2] + 3.5, pts[-1] + 3.5, fill=coul, outline=PANNEAU)


def ligne_tableau(parent, colonnes, fond=PANNEAU2, padx=10, pady=6):
    """Une ligne d'objets (usine, molécule, contrat…) : colonnes = [(widget_fabrique, poids)]."""
    l = tk.Frame(parent, bg=fond, padx=padx, pady=pady)
    l.pack(fill="x", pady=(0, 6))
    return l


# ---------------------------------------------------------------- carte de fin de partie (image à partager)
CARTE_W, CARTE_H = 1080, 1350
_POLICES_GRASSES = ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    "/System/Library/Fonts/Supplemental/Arial Bold.ttf")
_POLICES_NORMALES = ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                     "/System/Library/Fonts/Supplemental/Arial.ttf")
_cache_polices_carte = {}


def _police_carte(taille, gras=False):
    cle = (taille, gras)
    if cle not in _cache_polices_carte:
        police_trouvee = None
        for chemin in (_POLICES_GRASSES if gras else _POLICES_NORMALES):
            if Path(chemin).exists():
                try:
                    police_trouvee = ImageFont.truetype(chemin, taille)
                    break
                except OSError:
                    pass
        _cache_polices_carte[cle] = police_trouvee or ImageFont.load_default()
    return _cache_polices_carte[cle]


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _centre(d, texte, y, police, couleur, w=CARTE_W):
    bbox = d.textbbox((0, 0), texte, font=police)
    d.text(((w - (bbox[2] - bbox[0])) / 2 - bbox[0], y), texte, font=police, fill=couleur)


def _degrade_fond(img, haut, bas):
    d = ImageDraw.Draw(img)
    h = img.height
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (img.width, y)], fill=tuple(int(haut[i] + (bas[i] - haut[i]) * t) for i in range(3)))


def _rect_arrondi(d, boite, rayon, **kw):
    try:
        d.rounded_rectangle(boite, radius=rayon, **kw)
    except AttributeError:
        d.rectangle(boite, **kw)


def sans_emoji(t):
    return re.sub(r"[\U00010000-\U0010FFFF\uFE0F]", "", t).strip()


def legende_moic(m):
    if m.fin == "faillite":
        return f"faillite au mois {m.mois}"
    if m.fin == "rachat":
        return f"entreprise vendue au mois {m.mois}" + (f" à {m.acquereur}" if m.acquereur else "")
    return f"l'argent investi, multiplié en {M.DUREES_PARTIE.get(m.duree, f'{m.duree} mois')}"


def emoji_resultat(m, b):
    if m.fin == "faillite":
        return "💀"
    moic = b["moic"]
    return "📉" if moic < 1 else "✅" if moic < 2 else "🚀" if moic < 5 else "🏆" if moic < 15 else "🦄"


def resume_partage(m, b):
    """Résumé texte à coller dans un message ou un post (façon Wordle)."""
    s, j = m.s, m.joueur
    serie = [h.get("valorisation", 0.0) for h in j.historique if "valorisation" in h] or [0.0]
    if m.fin == "rachat":
        serie.append(b["valeur"])
    n = 12
    ech = [serie[min(len(serie) - 1, round(i * (len(serie) - 1) / (n - 1)))] for i in range(n)]
    haut = max(ech) or 1.0
    blocs = "▁▂▃▄▅▆▇█"
    courbe = "".join(blocs[max(0, min(7, int(v / haut * 7.999)))] for v in ech)
    duree = M.DUREES_PARTIE.get(m.duree, f"{m.duree} mois")
    rang = (f" · {b['rang']}{'re' if b['rang'] == 1 else 'e'} sur {b['nb']}" if b["nb"] > 1 else " · en solo")
    return "\n".join([
        f"Ma Boîte — {s.nom} · {duree} · {m.difficulte}",
        f"{emoji_resultat(m, b)} {sans_emoji(b['titre'])} : × {b['moic']:.1f} ({legende_moic(m)})".replace(".", ",", 1),
        f"Valeur finale {court(b['valeur'])}{rang}",
        f"{courbe}",
        "Et vous, vous feriez mieux ? #MaBoîte"])


def dessiner_carte(m, b):
    """Construit l'image (PIL.Image) de la carte de fin de partie, prête à être enregistrée en PNG."""
    j, s = m.joueur, m.s
    W = CARTE_W
    img = Image.new("RGB", (W, CARTE_H), _hex(FOND))
    _degrade_fond(img, _hex(FOND), _hex("#0a0e14"))
    d = ImageDraw.Draw(img)
    moic = b["moic"]
    if m.fin == "faillite" or moic < 1:
        coul = _hex(ROUGE)
    elif moic < 3:
        coul = _hex(AMBRE)
    else:
        coul = _hex(VERT)
    mut, txt, bord = _hex(MUT), _hex(TXT), _hex(BORD)
    panneau, panneau2, acc = _hex(PANNEAU), _hex(PANNEAU2), _hex(ACC)

    d.text((80, 64), "MA BOÎTE", font=_police_carte(30, True), fill=acc)
    duree_txt = M.DUREES_PARTIE.get(m.duree, f"{m.duree} mois")
    entete = f"{duree_txt} · {m.difficulte}".upper()
    bbox = d.textbbox((0, 0), entete, font=_police_carte(22))
    d.text((W - 80 - (bbox[2] - bbox[0]), 70), entete, font=_police_carte(22), fill=mut)
    d.line([(80, 128), (W - 80, 128)], fill=bord, width=2)

    _centre(d, j.nom, 172, _police_carte(50, True), txt)
    _centre(d, s.nom, 236, _police_carte(25), mut)
    _centre(d, sans_emoji(b["titre"]), 310, _police_carte(42, True), coul)
    _centre(d, f"× {moic:.1f}".replace(".", ","), 380, _police_carte(150, True), coul)
    _centre(d, legende_moic(m), 555, _police_carte(24), mut)
    y_suite = 600
    if b["nb"] > 1:
        _centre(d, f"{b['rang']}{'re' if b['rang'] == 1 else 'e'} sur {b['nb']} entreprises", y_suite, _police_carte(26, True), _hex(AMBRE))
        y_suite += 46

    y0, y1 = y_suite + 30, y_suite + 330
    _rect_arrondi(d, [80, y0, W - 80, y1], 16, fill=panneau, outline=bord, width=1)
    d.text((110, y0 + 24), "VALEUR DE L'ENTREPRISE", font=_police_carte(16, True), fill=mut)
    serie = [h.get("valorisation", 0.0) for h in j.historique if "valorisation" in h]
    if m.fin == "rachat":
        serie.append(b["valeur"])
    if len(serie) >= 2:
        gx0, gx1, gy0, gy1 = 110, W - 110, y0 + 70, y1 - 40
        vmax = max(max(serie), b["capital"], 1.0) * 1.08
        yv = lambda v: gy1 - (gy1 - gy0) * max(0.0, v) / vmax
        pts = [(gx0 + (gx1 - gx0) * i / (len(serie) - 1), yv(v)) for i, v in enumerate(serie)]
        fond_courbe = tuple(int(coul[k] * 0.25 + panneau[k] * 0.75) for k in range(3))
        d.polygon([(gx0, gy1)] + pts + [(gx1, gy1)], fill=fond_courbe)
        d.line(pts, fill=coul, width=5, joint="curve")
        d.ellipse([pts[-1][0] - 8, pts[-1][1] - 8, pts[-1][0] + 8, pts[-1][1] + 8], fill=coul)
        yc = yv(b["capital"])                      # repère : l'argent investi
        x = gx0
        while x < gx1:
            d.line([(x, yc), (min(x + 14, gx1), yc)], fill=_hex("#9e9e9e"), width=2)
            x += 24
        d.text((gx0 + 4, yc - 26), f"argent investi : {court(b['capital'])}", font=_police_carte(16), fill=mut)
        d.text((gx0, gy1 + 10), "mois 1", font=_police_carte(15), fill=mut)
        fin_txt = f"mois {len(serie)}"
        bb = d.textbbox((0, 0), fin_txt, font=_police_carte(15))
        d.text((gx1 - (bb[2] - bb[0]), gy1 + 10), fin_txt, font=_police_carte(15), fill=mut)
        bb = d.textbbox((0, 0), court(b["valeur"]), font=_police_carte(24, True))
        d.text((W - 110 - (bb[2] - bb[0]), y0 + 18), court(b["valeur"]), font=_police_carte(24, True), fill=txt)
    else:
        _centre(d, "Partie trop courte pour une courbe.", (y0 + y1) // 2, _police_carte(20), mut)

    y2 = y1 + 36
    largeur = (W - 160 - 40) / 3
    for i, (lib, val) in enumerate([("VOTRE GAIN", court(b["gain"])), ("CA ANNUEL", court(b["ca"])),
                                    ("EMPLOIS CRÉÉS", str(b["salaries"]))]):
        x0 = 80 + i * (largeur + 20)
        _rect_arrondi(d, [x0, y2, x0 + largeur, y2 + 110], 14, fill=panneau2, outline=bord, width=1)
        d.text((x0 + 20, y2 + 18), lib, font=_police_carte(15, True), fill=mut)
        d.text((x0 + 20, y2 + 46), val, font=_police_carte(30, True), fill=txt)

    _centre(d, "Et vous, vous feriez mieux ?   #MaBoîte", CARTE_H - 110, _police_carte(30, True), txt)
    _centre(d, f"Simulation d'entreprise · {s.nom} · {duree_txt}", CARTE_H - 60,
            _police_carte(18), mut)
    return img


# =============================================================================
class Application:
    def __init__(self, racine: tk.Tk):
        self.r = racine
        racine.title("Ma Boîte — simulation de création d'entreprise")
        racine.configure(bg=FOND)
        racine.geometry("1320x820")
        racine.minsize(1220, 760)
        self.cadre = None
        self.m = None
        self.dialogue_ouvert = False
        self.fichier = None
        racine.bind("<Return>", lambda _: self.tour() if self.m and not self.m.fin and not self.dialogue_ouvert
                    else None)
        racine.bind("<Control-s>", lambda _: self.sauvegarder())
        racine.protocol("WM_DELETE_WINDOW", self.quitter)
        self.ecran_creation()

    # ================================================================ sauvegarde
    def sauvegarder(self, silencieux=False):
        """Écrit la partie dans sauvegardes/<entreprise>_<secteur>.sav (écriture atomique)."""
        m = self.m
        if not m or m.fin or not self.fichier:
            return False
        j = m.joueur
        meta = {"version": VERSION_SAUVEGARDE, "nom": j.nom, "secteur": m.s.nom, "icone": m.s.icone,
                "mois": m.mois, "rang": m.rang_joueur(), "nb": len(m.entreprises), "tresorerie": j.tresorerie,
                "difficulte": m.difficulte, "duree": m.duree, "horodatage": time.time()}
        etat = {"marche": m, "journal": list(self.lignes_journal),
                "decisions": {"prix": self.v_prix.get(), "mkt": self.v_mkt.get(), "qual": self.v_qual.get()}}
        try:
            DOSSIER_SAUVEGARDES.mkdir(exist_ok=True)
            tmp = self.fichier.with_suffix(".tmp")
            with open(tmp, "wb") as h:
                pickle.dump(meta, h)
                pickle.dump(etat, h)
            os.replace(tmp, self.fichier)
        except OSError as e:
            self.l_sauve.config(text="⚠ Sauvegarde impossible", fg=ROUGE)
            if not silencieux:
                self.dialogue("Sauvegarde impossible", f"Le fichier n'a pas pu être écrit ({e}). Si le dossier "
                              "est synchronisé par OneDrive, réessayez dans quelques secondes.", icone="⚠",
                              couleur=ROUGE)
            return False
        self.l_sauve.config(text=f"✓ Sauvegardé à {datetime.now():%H:%M}", fg=VERT)
        if not silencieux:
            self.flash(f"Partie sauvegardée dans {self.fichier.name} (dossier « sauvegardes » du jeu). "
                       "Elle est aussi sauvegardée automatiquement à chaque mois.")
        return True

    def reprendre(self, fichier):
        try:
            with open(fichier, "rb") as h:
                meta = pickle.load(h)
                etat = pickle.load(h)
        except Exception as e:
            self.dialogue("Sauvegarde illisible", f"Impossible de lire {Path(fichier).name} ({type(e).__name__}).",
                          icone="⚠", couleur=ROUGE)
            return
        if meta.get("version") != VERSION_SAUVEGARDE:
            self.dialogue("Sauvegarde trop ancienne", "Cette partie a été créée avec une version précédente du jeu "
                          "(avant les 8 nouveaux secteurs) et ne peut pas être reprise.", icone="⚠", couleur=ROUGE)
            return
        self.m = etat["marche"]
        DUREE_JEU["n"] = self.m.duree
        self.fichier = Path(fichier)
        self.ecran_jeu(etat.get("decisions"), etat.get("journal"))

    def supprimer_sauvegarde(self, meta):
        i, _ = self.dialogue("Supprimer cette partie ?", f"« {meta['nom']} » ({meta['secteur']}, mois "
                             f"{meta['mois']}/{meta.get('duree', 36)}) sera définitivement effacée.", ("Supprimer", "Annuler"),
                             "⚠", ROUGE)
        if i == 0:
            try:
                Path(meta["fichier"]).unlink()
            except OSError:
                pass
            self.ecran_creation()

    def menu(self):
        if self.m and not self.m.fin:
            self.sauvegarder(silencieux=True)
        self.ecran_creation()

    def quitter(self):
        if self.m and not self.m.fin:
            self.sauvegarder(silencieux=True)
        self.r.destroy()

    def vider(self):
        if self.cadre:
            self.cadre.destroy()
        self.cadre = tk.Frame(self.r, bg=FOND)
        self.cadre.pack(fill="both", expand=True)
        return self.cadre

    # ================================================================ dialogues
    def dialogue(self, titre, texte, boutons=("Compris",), icone="ℹ", couleur=ACC, curseur_montant=None,
                 info_montant=None, titre_curseur="Montant", segments=None, fmt_curseur=None):
        """Fenêtre modale au thème du jeu. Renvoie (index du bouton choisi, montant du curseur éventuel).
        Avec plusieurs boutons, le dernier (ou la fermeture de la fenêtre) vaut « annuler ».
        segments = (titre, options, variable tk) ajoute un choix exclusif (lu ensuite dans la variable)."""
        d = tk.Toplevel(self.r, bg=PANNEAU)
        d.title(titre)
        d.transient(self.r)
        d.resizable(False, False)
        d.configure(highlightthickness=1, highlightbackground=BORD)
        tk.Frame(d, bg=couleur, height=4).pack(fill="x")
        corps = tk.Frame(d, bg=PANNEAU, padx=26, pady=18)
        corps.pack(fill="both")
        tete = tk.Frame(corps, bg=PANNEAU)
        tete.pack(fill="x")
        tk.Label(tete, text=icone, font=police(22), bg=PANNEAU, fg=couleur).pack(side="left", padx=(0, 12))
        tk.Label(tete, text=titre, font=police(15, True), bg=PANNEAU, fg=TXT, wraplength=420, justify="left"
                 ).pack(side="left")
        tk.Label(corps, text=texte, font=police(11), bg=PANNEAU, fg="#d4d4d4", wraplength=470, justify="left"
                 ).pack(anchor="w", pady=(12, 4))
        var = None
        info = tk.Label(corps, font=police(9), bg=PANNEAU, fg=MUT, justify="left", wraplength=470)

        def maj_info():
            if info_montant:
                txt, alerte = info_montant(var.get() if var else None)
                info.config(text=txt, fg=ROUGE if alerte else MUT)
        if segments:
            tk.Label(corps, text=segments[0], font=police(10, True), bg=PANNEAU, fg=TXT).pack(anchor="w", pady=(8, 4))
            Segments(corps, segments[1], segments[2], maj_info).pack(anchor="w")
        if curseur_montant:
            mini, maxi, pas = curseur_montant[:3]
            var = tk.IntVar(value=curseur_montant[3] if len(curseur_montant) > 3 else maxi)
            curseur(corps, titre_curseur, var, mini, maxi, pas, fmt_curseur or (lambda v: euros(float(v))), maj_info)
        if info_montant:
            info.pack(anchor="w", pady=(6, 0))
            maj_info()
        res = {"i": len(boutons) - 1}

        def choisir(i):
            res["i"] = i
            d.destroy()
        ligne = tk.Frame(corps, bg=PANNEAU)
        ligne.pack(fill="x", pady=(16, 0))
        for i, lib in enumerate(boutons):
            Bouton(ligne, lib, lambda i=i: choisir(i), "primaire" if i == 0 else "secondaire").pack(
                side="left", padx=(0, 8))
        d.bind("<Return>", lambda _: choisir(0))
        d.bind("<Escape>", lambda _: choisir(len(boutons) - 1))
        d.update_idletasks()
        x = self.r.winfo_rootx() + (self.r.winfo_width() - d.winfo_reqwidth()) // 2
        y = self.r.winfo_rooty() + max(0, (self.r.winfo_height() - d.winfo_reqheight()) // 3)
        d.geometry(f"+{x}+{y}")
        d.grab_set()
        d.focus_set()
        self.dialogue_ouvert = True
        self.r.wait_window(d)
        self.dialogue_ouvert = False
        return res["i"], (var.get() if var else None)

    # ================================================================ écran de création
    def ecran_creation(self):
        self.m = None
        f = self.vider()
        haut = tk.Frame(f, bg=FOND, padx=30, pady=14)
        haut.pack(fill="x")
        tk.Label(haut, text="Ma Boîte", font=police(26, True), bg=FOND, fg=TXT).pack(anchor="w")
        tk.Label(haut, text=f"Votre mise : {euros(M.APPORT)}. Choisissez un secteur, convainquez investisseurs et "
                 "banquiers, et bâtissez l'entreprise qui vaudra le plus face à vos concurrents.", font=police(11),
                 bg=FOND, fg=MUT).pack(anchor="w")

        parties = lister_sauvegardes()
        if parties:
            bande = tk.Frame(f, bg=FOND, padx=30)
            bande.pack(fill="x", pady=(0, 10))
            tk.Label(bande, text="Reprendre une partie", font=police(11, True), bg=FOND, fg=TXT).pack(anchor="w",
                                                                                                 pady=(0, 6))
            ligne = tk.Frame(bande, bg=FOND)
            ligne.pack(fill="x")
            for k in range(4):
                ligne.columnconfigure(k, weight=1, uniform="p")
            for i, meta in enumerate(parties[:4]):
                c = tk.Frame(ligne, bg=PANNEAU, highlightthickness=1, highlightbackground=BORD, padx=12, pady=6)
                c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
                tk.Label(c, text=f"{meta.get('icone', '')}  {meta['nom']}", font=police(11, True), bg=PANNEAU,
                         fg=TXT).pack(anchor="w")
                duree = meta.get("duree", 36)
                rang = f" · #{meta['rang']} sur {meta['nb']}" if meta.get("nb", 1) > 1 else ""
                tk.Label(c, text=f"{meta['secteur']} · mois {min(meta['mois'] + 1, duree)}/{duree}{rang}",
                         font=police(9), bg=PANNEAU, fg=MUT).pack(anchor="w")
                tk.Label(c, text=f"Trésorerie {court(meta['tresorerie'])} · "
                         f"{datetime.fromtimestamp(meta['horodatage']):%d/%m à %H:%M}", font=police(9), bg=PANNEAU,
                         fg=MUT).pack(anchor="w")
                bas_c = tk.Frame(c, bg=PANNEAU)
                bas_c.pack(fill="x", pady=(4, 0))
                Bouton(bas_c, "Reprendre", lambda f=meta["fichier"]: self.reprendre(f), "primaire", padx=12,
                       pady=3).pack(side="left")
                Bouton(bas_c, "Supprimer", lambda m=meta: self.supprimer_sauvegarde(m), "fantome", padx=8,
                       pady=3).pack(side="left", padx=6)
            if len(parties) > 4:
                tk.Label(bande, text=f"+ {len(parties) - 4} autre(s) partie(s) dans le dossier « sauvegardes ».",
                         font=police(9), bg=FOND, fg=MUT).pack(anchor="w", pady=(4, 0))

        corps = tk.Frame(f, bg=FOND, padx=30)
        corps.pack(fill="both", expand=True)
        corps.columnconfigure(0, weight=5)
        corps.columnconfigure(1, weight=2, minsize=350)
        corps.rowconfigure(0, weight=1)

        # --- gauche : nom et secteur
        g = Carte(corps, "Votre projet")
        g.grid(row=0, column=0, sticky="nsew", padx=(0, 16), pady=(0, 16))
        ligne = tk.Frame(g, bg=PANNEAU)
        ligne.pack(fill="x")
        tk.Label(ligne, text="Nom de l'entreprise", font=police(10, True), bg=PANNEAU, fg=MUT).pack(side="left")
        self.v_nom = tk.StringVar(value="Ma Boîte")
        tk.Entry(ligne, textvariable=self.v_nom, font=police(12), bg=PANNEAU2, fg=TXT, insertbackground=TXT,
                 relief="flat", highlightthickness=1, highlightbackground=BORD, highlightcolor=ACC, width=32
                 ).pack(side="left", padx=12, ipady=4)
        tk.Label(g, text="Choisissez votre secteur", font=police(10, True), bg=PANNEAU, fg=MUT).pack(anchor="w",
                                                                                                      pady=(10, 4))
        grille = tk.Frame(g, bg=PANNEAU)
        grille.pack(fill="x")
        self.v_secteur = tk.StringVar(value="saas")
        self.cartes_secteur = {}
        for i, (cle, s) in enumerate(M.SECTEURS.items()):
            c = tk.Frame(grille, bg=PANNEAU2, highlightthickness=2, highlightbackground=PANNEAU2, padx=10, pady=6,
                         cursor="hand2")
            c.grid(row=i // 4, column=i % 4, sticky="nsew", padx=3, pady=3)
            grille.columnconfigure(i % 4, weight=1, uniform="s")
            w1 = tk.Label(c, text=f"{s.icone}  {s.nom}", font=police(10, True), bg=PANNEAU2, fg=TXT, anchor="w",
                          wraplength=200, justify="left")
            w2 = tk.Label(c, text=s.tag, font=police(8), bg=PANNEAU2, fg=MUT, wraplength=190, justify="left")
            w3 = tk.Label(c, text=f"Mise de départ {M.fmt_c(s.installation)}", font=police(8, True), bg=PANNEAU2,
                          fg=ACC_SURVOL)
            for w in (w1, w2, w3):
                w.pack(anchor="w")
            for w in (c, w1, w2, w3):
                w.bind("<Button-1>", lambda _, k=cle: self.choisir_secteur(k))
            self.cartes_secteur[cle] = c
        self.detail = tk.Frame(g, bg=PANNEAU)
        self.detail.pack(fill="both", expand=True, pady=(10, 0))

        # --- droite : compétition, durée, financement, lancement
        dr = Carte(corps, "La partie")
        dr.grid(row=0, column=1, sticky="nsew", pady=(0, 16))
        tk.Label(dr, text="Concurrents", font=police(10, True), bg=PANNEAU, fg=MUT).pack(anchor="w")
        self.v_nb = tk.IntVar(value=3)
        Segments(dr, [(k, str(k) if k else "Solo") for k in range(5)], self.v_nb, self.maj_creation
                 ).pack(anchor="w", pady=(4, 8))
        tk.Label(dr, text="Difficulté", font=police(10, True), bg=PANNEAU, fg=MUT).pack(anchor="w")
        self.v_diff = tk.StringVar(value="Normal")
        Segments(dr, [(k, k) for k in M.DIFFICULTES], self.v_diff, self.maj_creation).pack(anchor="w", pady=(4, 8))
        tk.Label(dr, text="Durée de la partie", font=police(10, True), bg=PANNEAU, fg=MUT).pack(anchor="w")
        self.v_duree = tk.IntVar(value=36)
        Segments(dr, list(M.DUREES_PARTIE.items()), self.v_duree, self.maj_creation).pack(anchor="w", pady=(4, 4))
        self.l_adv = tk.Label(dr, font=police(9), bg=PANNEAU, fg=MUT, justify="left", wraplength=290)
        self.l_adv.pack(anchor="w", pady=(2, 2))
        self.zone_pret = tk.Frame(dr, bg=PANNEAU)
        self.zone_pret.pack(fill="x")
        self.l_depart = tk.Label(dr, font=police(10, True), bg=PANNEAU, justify="left", wraplength=300)
        self.l_depart.pack(anchor="w", pady=8)
        Bouton(dr, "Lancer mon entreprise  →", self.demarrer, "primaire", taille=12, pady=10).pack(
            fill="x", side="bottom")
        self.choisir_secteur("saas")

    def choisir_secteur(self, cle):
        self.v_secteur.set(cle)
        s = M.SECTEURS[cle]
        for k, c in self.cartes_secteur.items():
            c.configure(highlightbackground=ACC if k == cle else PANNEAU2)
        for w in self.detail.winfo_children():
            w.destroy()

        def ligne(txt, coul, gras=False, taille=10):
            l = tk.Label(self.detail, text=txt, font=police(taille, gras), bg=PANNEAU, fg=coul, justify="left",
                         anchor="w", wraplength=740)
            l.pack(anchor="w", fill="x", pady=(0, 5))
            self.detail.bind("<Configure>", lambda e: [w.config(wraplength=max(300, e.width - 10))
                                                      for w in self.detail.winfo_children()])
        ligne(f"{s.icone}  {s.nom} — {s.tag}", TXT, True, 12)
        ligne(s.description, "#d4d4d4")
        ligne("📊  Métrique clé : " + s.metrique, AMBRE, True)
        ligne("🎮  " + s.gameplay, "#d4d4d4")
        tour = (f"💼  Tour de table : votre mise ({court(M.APPORT)}) + des investisseurs ({court(s.investisseurs)}, "
                f"qui reçoivent {pct(s.part_investisseurs)} du capital)")
        if s.subvention_initiale:
            tour += f" + {s.libelle_subvention} ({court(s.subvention_initiale)})"
        tour += f". À financer : {s.libelle_installation.lower()} ({court(s.installation)})"
        if s.equipe_initiale:
            tour += f" et une équipe de {s.equipe_initiale} personnes"
        ligne(tour + ".", MUT)
        for w in self.zone_pret.winfo_children():
            w.destroy()
        self.v_pret = tk.IntVar(value=int(s.pret_conseille))
        self.l_pret_val = curseur(self.zone_pret, s.libelle_pret, self.v_pret, 0, int(s.pret_max), int(s.pas_pret),
                                  lambda v: court(float(v)), self.maj_creation)
        self.l_pret_conseil = tk.Label(self.zone_pret, font=police(9), bg=PANNEAU, fg=MUT, wraplength=300,
                                       justify="left")
        self.l_pret_conseil.pack(anchor="w")
        self.maj_creation()

    def maj_creation(self):
        s = M.SECTEURS[self.v_secteur.get()]
        pret = self.v_pret.get()
        tresor = M.APPORT + s.investisseurs + s.subvention_initiale + pret - s.installation
        taux = M.TAUX_REF_INITIAL + 0.018 if s.pret_variable else s.taux_pret_initial
        mensu = M.nouveau_pret(pret, taux, s.duree_pret_initial).mensualite if pret else 0
        fixes = s.loyer + s.salaire_dirigeant + s.frais_generaux + s.equipe_initiale * s.salaire + s.cout_fixe_ops
        mois = tresor / fixes if fixes else 99
        ok = mois >= 3
        self.l_pret_val.config(text=court(pret))
        self.l_pret_conseil.config(text=f"Sur {s.duree_pret_initial // 12} ans à {M.fmt_taux(taux)}"
                                   + (" (taux variable)" if s.pret_variable else "")
                                   + (f", {s.differe_initial} mois de différé" if s.differe_initial else "")
                                   + f". Conseillé : {court(s.pret_conseille)}.")
        self.l_depart.config(text=f"Trésorerie de départ : {court(tresor)}\n≈ {mois:.0f} mois de charges fixes "
                             f"({court(fixes)}/mois)" + (f"\nMensualité du prêt : {court(mensu)}" if pret else "")
                             + ("" if ok else "\n⚠ Trop juste pour tenir : empruntez davantage."),
                             fg=VERT if ok else ROUGE)
        nb = self.v_nb.get()
        ordre = ["equilibre", "lowcost", "premium", "startup"][:nb]
        self.l_adv.config(text=("Adversaires : " + ", ".join(M.STRATEGIES[k].nom.lower() for k in ordre)
                                + ". D'autres peuvent arriver.") if nb else
                          "Seul sur votre marché… pour l'instant.")

    def demarrer(self):
        nom = self.v_nom.get().strip() or "Ma Boîte"
        fichier = fichier_sauvegarde(nom, self.v_secteur.get())
        ancien = lire_entete(fichier) if fichier.exists() else None
        if ancien:
            i, _ = self.dialogue("Une partie porte déjà ce nom", f"« {ancien['nom']} » ({ancien['secteur']}) est "
                                 f"sauvegardée au mois {ancien['mois'] + 1}. La nouvelle partie la remplacera.",
                                 ("Remplacer", "Annuler"), "⚠", AMBRE)
            if i != 0:
                return
        self.m = M.Marche(nom, self.v_secteur.get(), float(self.v_pret.get()), self.v_nb.get(), self.v_diff.get(),
                          duree=self.v_duree.get())
        DUREE_JEU["n"] = self.m.duree
        self.fichier = fichier
        self.ecran_jeu()

    # ================================================================ écran de jeu
    def ecran_jeu(self, decisions=None, journal=None):
        f = self.vider()
        m, j, s = self.m, self.m.joueur, self.m.s
        self.decisions_init = decisions or {}
        self.lignes_journal = []

        # --- barre latérale
        DUREE_JEU["n"] = m.duree
        side = tk.Frame(f, bg=BARRE, width=236, padx=12, pady=14)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Label(side, text=f"{s.icone}  {j.nom}", font=police(13, True), bg=BARRE, fg=TXT, wraplength=210,
                 justify="left").pack(anchor="w")
        tk.Label(side, text=s.nom, font=police(9), bg=BARRE, fg=MUT, wraplength=210, justify="left").pack(anchor="w")
        tk.Frame(side, bg=BARRE, height=10).pack()
        self.nav = {}
        self.page = None
        for cle, lib in [("bord", "▦   Tableau de bord"), ("activite", "◆   " + s.libelle_activite),
                         ("equipe", "☺   Équipe"), ("fin", "∑   Finances"),
                         ("banque", "€   Banque et capital"), ("conc", "⚑   Concurrence"),
                         ("rachats", "⇄   Rachats"), ("inv", "▲   Investir"), ("journal", "☰   Journal")]:
            b = tk.Label(side, text=lib, font=police(10, True), bg=BARRE, fg=MUT, anchor="w", padx=10, pady=6,
                         cursor="hand2")
            b.pack(fill="x", pady=1)
            b.bind("<Button-1>", lambda _, k=cle: self.afficher(k))
            b.bind("<Enter>", lambda _, b=b, k=cle: b.config(bg=PANNEAU) if self.page != k else None)
            b.bind("<Leave>", lambda _, b=b, k=cle: b.config(bg=BARRE) if self.page != k else None)
            self.nav[cle] = b
        tk.Frame(side, bg=BARRE, height=8).pack()
        for lib, cmd in (("⤓   Sauvegarder  (Ctrl+S)", self.sauvegarder), ("⌂   Menu principal", self.menu)):
            b = tk.Label(side, text=lib, font=police(10), bg=BARRE, fg=MUT, anchor="w", padx=12, pady=6,
                         cursor="hand2")
            b.pack(fill="x")
            b.bind("<Button-1>", lambda _, c=cmd: c())
            b.bind("<Enter>", lambda _, b=b: b.config(fg=TXT))
            b.bind("<Leave>", lambda _, b=b: b.config(fg=MUT))
        self.l_sauve = tk.Label(side, text="Sauvegarde automatique activée", font=police(8), bg=BARRE, fg=DISCRET,
                                anchor="w", padx=12)
        self.l_sauve.pack(fill="x")
        bas = tk.Frame(side, bg=BARRE)
        bas.pack(side="bottom", fill="x")
        self.l_rang = tk.Label(bas, font=police(22, True), bg=BARRE, fg=AMBRE)
        self.l_rang.pack(anchor="w")
        self.l_rang2 = tk.Label(bas, font=police(9), bg=BARRE, fg=MUT)
        self.l_rang2.pack(anchor="w")
        tk.Frame(bas, bg=BARRE, height=12).pack()
        self.l_mois = tk.Label(bas, font=police(9, True), bg=BARRE, fg=MUT)
        self.l_mois.pack(anchor="w")
        self.c_temps = tk.Canvas(bas, height=6, bg=PANNEAU2, highlightthickness=0)
        self.c_temps.pack(fill="x", pady=(4, 14))
        self.b_suivant = Bouton(bas, "Mois suivant  ▶", self.tour, "primaire", taille=12, pady=12)
        self.b_suivant.pack(fill="x")
        tk.Label(bas, text="ou touche Entrée", font=police(8), bg=BARRE, fg=DISCRET).pack(pady=(4, 0))

        # --- zone principale
        main = tk.Frame(f, bg=FOND, padx=20, pady=14)
        main.pack(side="left", fill="both", expand=True)
        tete = tk.Frame(main, bg=FOND)
        tete.pack(fill="x")
        self.l_page = tk.Label(tete, font=police(18, True), bg=FOND, fg=TXT)
        self.l_page.pack(side="left")
        droite = tk.Frame(tete, bg=FOND)
        droite.pack(side="right")
        self.l_treso = tk.Label(droite, font=police(18, True), bg=FOND)
        self.l_treso.pack(side="right")
        tk.Label(droite, text="Trésorerie", font=police(9), bg=FOND, fg=MUT).pack(side="right", padx=(0, 8),
                                                                                  pady=(6, 0))
        self.l_note = tk.Label(droite, font=police(10, True), fg="#0b0b0b", padx=8, pady=4, cursor="hand2")
        self.l_note.pack(side="right", padx=(18, 0))
        self.l_note.bind("<Button-1>", lambda _: self.afficher("banque"))
        self.l_date = tk.Label(droite, font=police(10, True), bg=PANNEAU2, fg=TXT, padx=10, pady=4)
        self.l_date.pack(side="right", padx=18)

        self.flash_l = tk.Label(main, font=police(10), bg="#16130a", fg="#f5d58a", anchor="w", justify="left",
                                padx=14, pady=7, wraplength=1000)
        self.flash_l.pack(fill="x", side="bottom", pady=(10, 0))

        zone = tk.Frame(main, bg=FOND)
        zone.pack(fill="both", expand=True, pady=(12, 0))
        zone.rowconfigure(0, weight=1)
        zone.columnconfigure(0, weight=1)
        self.pages = {}
        for cle in ("bord", "activite", "equipe", "fin", "banque", "conc", "rachats", "inv", "journal"):
            p = tk.Frame(zone, bg=FOND)
            p.grid(row=0, column=0, sticky="nsew")
            self.pages[cle] = p
        self.construire_bord(self.pages["bord"])
        self.construire_activite(self.pages["activite"])
        self.construire_equipe(self.pages["equipe"])
        self.construire_fin(self.pages["fin"])
        self.construire_banque(self.pages["banque"])
        self.construire_conc(self.pages["conc"])
        self.construire_rachats(self.pages["rachats"])
        self.construire_inv(self.pages["inv"])
        self.construire_journal(self.pages["journal"])
        self.afficher("bord")
        if journal:
            for texte, tag in journal:
                self.ecrire(texte, tag)
            self.ecrire(f"— Partie reprise le {datetime.now():%d/%m/%Y à %H:%M} —", "titre")
            self.flash(f"Partie reprise : {m.date()}, mois {m.mois + 1} sur {m.duree}. Bon retour !")
        else:
            self.flash(f"Bienvenue ! Métrique clé de votre secteur : {s.metrique.lower()}. Réglez vos décisions, "
                       f"passez voir la page « {s.libelle_activite} », puis cliquez sur « Mois suivant ».")
            self.ecrire("Début de l'aventure. Concurrents : " + (", ".join(
                f"{e.nom} ({e.strategie.nom.lower()})" for e in m.concurrents) or "aucun") + ".", "marche")
        self.maj()

    def afficher(self, cle):
        self.page = cle
        self.pages[cle].tkraise()
        titres = {"bord": "Tableau de bord", "activite": self.m.s.libelle_activite, "equipe": "Équipe et recrutement", "fin": "États financiers", "banque": "Banque, trésorerie et capital",
                  "conc": "Concurrence", "rachats": "Rachats et filiales", "inv": "Investissements stratégiques",
                  "journal": "Journal"}
        self.l_page.config(text=titres[cle])
        for k, b in self.nav.items():
            b.config(bg=PANNEAU if k == cle else BARRE, fg=TXT if k == cle else MUT)
        if cle == "conc":
            self.r.after(10, lambda: graphe_parts(self.g_parts, self.m.entreprises))
        if cle == "bord":
            self.r.after(10, lambda: graphe_finances(self.g_fin, self.m.joueur.historique))
        if cle == "equipe":
            self.maj_equipe()
        if cle == "activite":
            self.maj_activite()
        if cle == "rachats":
            self.maj_rachats()
        if cle == "fin":
            self.maj_fin()
        if cle == "banque":
            self.maj_banque()

    # ------------------------------------------------------------ page : tableau de bord
    def construire_bord(self, p):
        s, j = self.m.s, self.m.joueur
        ligne = tk.Frame(p, bg=FOND)
        ligne.pack(fill="x")
        self.tuiles = {}
        for i, (cle, lib) in enumerate([("ca", s.libelle_ca), ("res", "Résultat du mois"), ("k1", "—"), ("k2", "—"),
                                        ("valo", "Valeur de l'entreprise")]):
            t = Tuile(ligne, lib)
            t.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            ligne.columnconfigure(i, weight=1, uniform="t")
            self.tuiles[cle] = t

        bas = tk.Frame(p, bg=FOND)
        bas.pack(fill="both", expand=True, pady=(12, 0))
        bas.columnconfigure(1, weight=1)
        bas.rowconfigure(0, weight=1)

        # décisions (propres au secteur)
        dc = Carte(bas, "Décisions du mois")
        dc.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        mk0, q0 = budgets_conseilles(j)

        def cale(v, d):
            return type(d[1])(min(d[2], max(d[1], round(v / d[3]) * d[3])))
        self.v_prix = tk.DoubleVar(value=self.decisions_init.get("prix", j.prix))
        self.l_prix_info = None
        dp = s.decisions.get("prix")
        if dp:
            lib, mini, maxi, pas = dp
            curseur(dc, lib, self.v_prix, mini, maxi, pas, lambda v: prix_txt(float(v), s), self.maj_prix_info)
            self.l_prix_info = tk.Label(dc, font=police(9), bg=PANNEAU, fg=MUT, justify="left", anchor="w",
                                        wraplength=290)
            self.l_prix_info.pack(fill="x", pady=(2, 0))
        dm, dq = s.decisions["mkt"], s.decisions["qual"]
        self.v_mkt = tk.IntVar(value=int(self.decisions_init.get("mkt", cale(mk0, dm))))
        curseur(dc, dm[0], self.v_mkt, dm[1], dm[2], dm[3], lambda v: court(float(v)))
        self.v_qual = tk.IntVar(value=int(self.decisions_init.get("qual", cale(q0, dq))))
        curseur(dc, dq[0], self.v_qual, dq[1], dq[2], dq[3], lambda v: court(float(v)))
        texte_libre(dc, f"Repère : un concurrent équilibré dépenserait ≈ {court(mk0)} et {court(q0)} par mois.",
                    largeur=290, pady=(4, 0))

        eq = tk.Frame(dc, bg=PANNEAU)
        eq.pack(fill="x", pady=(12, 0))
        tk.Label(eq, text="Équipe", font=police(10, True), bg=PANNEAU, fg=TXT).pack(side="left")
        self.l_equipe = tk.Label(eq, font=police(10, True), bg=PANNEAU, fg=ACC, padx=10)
        self.l_equipe.pack(side="left")
        Bouton(eq, "Recruter / gérer  →", lambda: self.afficher("equipe"), "secondaire", taille=9, padx=10, pady=3
               ).pack(side="right")
        self.l_equipe_info = tk.Label(dc, font=police(9), bg=PANNEAU, fg=MUT, wraplength=290, justify="left")
        self.l_equipe_info.pack(anchor="w", pady=(2, 0))
        fi = tk.Frame(dc, bg=PANNEAU)
        fi.pack(fill="x", pady=(10, 0))
        Bouton(fi, "Emprunter", self.emprunter, "secondaire").pack(side="left", fill="x", expand=True, padx=(0, 4))
        Bouton(fi, "Lever des fonds", self.lever, "secondaire").pack(side="left", fill="x", expand=True, padx=(4, 0))

        conseil = tk.Frame(dc, bg="#181818")
        conseil.pack(fill="x", pady=(12, 0))
        tk.Frame(conseil, bg=ACC, width=3).pack(side="left", fill="y")
        self.l_conseil = tk.Label(conseil, font=police(9), bg="#181818", fg="#e5e5e5", justify="left", anchor="w",
                                  wraplength=280, padx=10, pady=8)
        self.l_conseil.pack(fill="x")

        # performance
        perf = Carte(bas, "Performance")
        perf.grid(row=0, column=1, sticky="nsew")
        self.g_fin = tk.Canvas(perf, height=200, bg=PANNEAU, highlightthickness=0)
        self.g_fin.pack(fill="both", expand=True)
        self.g_fin.bind("<Configure>", lambda _: graphe_finances(self.g_fin, self.m.joueur.historique))
        tk.Frame(perf, bg=BORD, height=1).pack(fill="x", pady=8)
        anneaux = tk.Frame(perf, bg=PANNEAU)
        anneaux.pack(fill="x")
        self.anneaux = {}
        for i, (cle, lib) in enumerate([("notoriete", s.libelle_notoriete), ("qualite", s.libelle_qualite),
                                        ("satisfaction", "Satisfaction"), ("moral", "Moral équipe"),
                                        ("jauge", j.act.jauge()[0])]):
            a = Anneau(anneaux, lib)
            a.grid(row=0, column=i, sticky="n")
            anneaux.columnconfigure(i, weight=1)
            self.anneaux[cle] = a

    # ------------------------------------------------------------ page : activité (propre à chaque secteur)
    def construire_activite(self, p):
        self.page_act = p
        self.zone_act = tk.Frame(p, bg=FOND)
        self.zone_act.pack(fill="both", expand=True)

    def maj_activite(self):
        if self.page != "activite":
            return
        self.zone_act.destroy()
        z = self.zone_act = tk.Frame(self.page_act, bg=FOND)
        z.pack(fill="both", expand=True)
        getattr(self, "act_" + self.m.s.modele)(z)

    def action(self, msg, tag="bon"):
        """Résultat d'une action de la page Activité : journal, bandeau, puis mise à jour."""
        if msg:
            self.ecrire(msg, tag)
            self.flash(msg)
        self.maj()

    def deux_colonnes(self, z, poids=(3, 2)):
        corps = tk.Frame(z, bg=FOND)
        corps.pack(fill="both", expand=True, pady=(12, 0))
        corps.columnconfigure(0, weight=poids[0], uniform="a")
        corps.columnconfigure(1, weight=poids[1], uniform="a")
        corps.rowconfigure(0, weight=1)
        g = tk.Frame(corps, bg=FOND)
        g.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        d = tk.Frame(corps, bg=FOND)
        d.grid(row=0, column=1, sticky="nsew")
        return g, d

    @staticmethod
    def courbe(parent, hauteur, dessin):
        can = tk.Canvas(parent, height=hauteur, bg=PANNEAU, highlightthickness=0)
        can.pack(fill="both", expand=True)
        can.bind("<Configure>", lambda _: dessin(can))
        return can

    @staticmethod
    def rangee(parent, fond=PANNEAU2, pady=5):
        l = tk.Frame(parent, bg=fond, padx=10, pady=pady)
        l.pack(fill="x", pady=(0, 6))
        return l

    def badge_activite(self):
        m, j = self.m, self.m.joueur
        a = j.act
        if isinstance(a, M.ActiviteAero):
            n = sum(1 for ao in m.appels if j.nom not in ao.offres and j.notoriete >= ao.exigence)
            return f"   ● {n}" if n else ""
        if isinstance(a, M.ActiviteEnergie):
            return "   ●" if a.projets or (m.enchere and j.nom not in m.enchere["offres"]) else ""
        if isinstance(a, M.ActiviteJeu):
            p = a.projet
            return "   ●" if not p or (p.avancement >= 1 and not p.lancer) else ""
        if isinstance(a, M.ActiviteLuxe):
            return "   ●" if j.prix > a.pma() else ""
        if isinstance(a, M.ActiviteDistribution):
            return "   ●" if a.rupture > 0.03 or a.defaut else ""
        if isinstance(a, M.ActiviteIndustrie):
            h = j.historique[-1] if j.historique else None
            return "   ●" if h and h["utilisation"] > 1.05 else ""
        return ""

    # ---------------------------------------------------------------- industrie lourde
    def act_industrie(self, z):
        j = self.m.joueur
        a = j.act
        pm = a.point_mort()
        rangee_kpis(z, [
            ("Utilisation des usines", pct(a.utilisation),
             "point mort ≈ " + (pct(pm) if pm < 5 else "hors d'atteinte"), VERT if a.utilisation >= min(pm, 1) else ROUGE),
            ("Coût de production", euros(a.cout_module()),
             f"par module · effet d'expérience −{pct(1 - a.facteur_experience())}", TXT),
            ("Capacité nominale", f"{M.fmt_n(a.capacite_nominale())} modules",
             f"produits ce mois-ci : {M.fmt_n(a.production)}", TXT),
            ("Coûts fixes des usines", court(a.fixes()) + "/mois", "énergie, maintenance, encadrement", TXT)]
        ).pack(fill="x")
        g, d = self.deux_colonnes(z)
        c = Carte(g, "Vos usines", "Une usine coûte presque autant à l'arrêt qu'en marche : remplissez-la. Si la "
                  "demande chute, la mise en sommeil réduit ses coûts fixes de 70 %, au prix du moral de l'équipe.")
        c.pack(fill="both", expand=True)
        etats = {"active": ("● En activité", VERT), "sommeil": ("◐ En sommeil", AMBRE),
                 "travaux": ("◌ En construction", ACC_SURVOL)}
        for i, u in enumerate(a.usines):
            l = self.rangee(c)
            bt = tk.Frame(l, bg=PANNEAU2)
            bt.pack(side="right")
            gauche = tk.Frame(l, bg=PANNEAU2)
            gauche.pack(side="left", fill="x", expand=True)
            tk.Label(gauche, text=f"🏭  {u['nom']}", font=police(10, True), bg=PANNEAU2, fg=TXT).pack(anchor="w")
            lib, coul = etats[u["etat"]]
            if u["etat"] == "travaux":
                lib += f" · encore {u['travaux']} mois"
            tk.Label(gauche, text=f"{lib}  ·  {M.fmt_n(u['capacite'])} modules/mois  ·  {court(u['fixe'])}/mois de "
                     "coûts fixes", font=police(9), bg=PANNEAU2, fg=coul).pack(anchor="w")
            if u["etat"] == "active":
                Bouton(bt, "Mettre en sommeil", lambda i=i: self.action("🏭 " + a.mettre_en_sommeil(i), "mut"),
                       "fantome", taille=9, padx=8, pady=3).pack(side="right")
            elif u["etat"] == "sommeil":
                Bouton(bt, f"Relancer ({court(u['fixe'] * 0.5)})", lambda i=i: self.action("🏭 " + a.relancer(i)),
                       "secondaire", taille=9, padx=8, pady=3).pack(side="right")
        b = Bouton(c, f"Construire une usine  ({court(a.COUT_USINE)})", self.construire_usine, "vert")
        b.pack(anchor="w", pady=(8, 0))
        b.activer(not any(u["etat"] == "travaux" for u in a.usines))
        texte_libre(c, f"+{M.fmt_n(a.CAPA_USINE)} modules par mois, {a.TRAVAUX_USINE} mois de travaux, amortie sur "
                    f"10 ans, {court(a.FIXE_USINE)}/mois de coûts fixes. À financer par emprunt ou levée de fonds.",
                    largeur=560, pady=(4, 0))
        c2 = Carte(d, "Utilisation et point mort", "Sous la ligne orange, les usines perdent de l'argent : les "
                   "coûts fixes écrasent la marge.")
        c2.pack(fill="both", expand=True)
        reels = j.mois_reels()
        serie = [h["kpi"].get("utilisation", 0.0) for h in reels]
        self.courbe(c2, 220, lambda can: graphe_series(
            can, [("Utilisation des usines", serie, ACC)], pct, ref=pm if pm < 1.5 else None, lib_ref="point mort",
            dates=[h["date"] for h in reels]))

    def construire_usine(self):
        j = self.m.joueur
        a = j.act
        i, _ = self.dialogue("Construire une usine ?", f"Coût : {euros(a.COUT_USINE)}, payé maintenant et amorti sur "
                             f"10 ans. Mise en service dans {a.TRAVAUX_USINE} mois : +{M.fmt_n(a.CAPA_USINE)} modules "
                             f"par mois, mais {euros(a.FIXE_USINE)} de coûts fixes mensuels qu'elle tourne ou non.\n\n"
                             f"Trésorerie après : {euros(j.tresorerie - a.COUT_USINE)}.", ("Construire", "Annuler"),
                             "🏭", VERT)
        if i == 0:
            msg = a.construire()
            self.action("🏭 " + msg, "bon" if msg.startswith("Construction") else "mauvais")

    # ---------------------------------------------------------------- SaaS
    def act_saas(self, z):
        j = self.m.joueur
        a = j.act
        mrr = j.abonnes * j.prix
        cac, ltv = a.cac(), a.ltv()
        ok_cac = math.isfinite(cac) and cac > 0
        ratio = ltv / cac if ok_cac and math.isfinite(ltv) else None
        rangee_kpis(z, [
            ("Clients abonnés", M.fmt_n(j.abonnes), f"+{M.fmt_n(a.nouveaux)} / −{M.fmt_n(a.perdus)} ce mois-ci", TXT),
            ("Revenu récurrent (MRR)", court(mrr), f"soit {court(mrr * 12)} par an (ARR)", TXT),
            ("Attrition (churn)", f"{a.churn_mois * 100:.1f} %".replace(".", ","), "clients perdus chaque mois",
             ROUGE if a.churn_mois > 0.04 else VERT if a.churn_mois < 0.02 else TXT),
            ("LTV / CAC", f"× {ratio:.1f}".replace(".", ",") if ratio else "—",
             f"valeur d'un client {court(ltv)} · coût d'acquisition {court(cac) if ok_cac else '—'}",
             VERT if ratio and ratio >= 3 else ROUGE if ratio else TXT),
            ("Maturité du produit", f"{a.maturite:.0f} %", "elle monte avec la R&D", TXT)]).pack(fill="x")
        g, d = self.deux_colonnes(z)
        c = Carte(g, "Revenu récurrent mensuel (MRR)", "Chaque client paie tous les mois : le MRR s'accumule. "
                  "C'est lui que regardent les investisseurs.")
        c.pack(fill="both", expand=True)
        reels = j.mois_reels()
        self.courbe(c, 240, lambda can: graphe_series(
            can, [("MRR", [h["kpi"].get("mrr", 0.0) for h in reels], ACC)], M.fmt_c,
            barres=("Nouveaux clients × prix", [h["kpi"].get("nouveaux", 0.0) * h["prix"] for h in reels], "#343434"),
            dates=[h["date"] for h in reels]))
        c2 = Carte(d, "Les règles du SaaS")
        c2.pack(fill="both", expand=True)
        h = reels[-1] if reels else None
        cap = j.capacite()
        tableau(c2, ["", ""], [
            ("Prix par client et par mois", [prix_txt(j.prix)], ""),
            ("Coût d'hébergement par client", [prix_txt(j.cout_unitaire)], ""),
            ("Marge brute", [pct(1 - j.cout_unitaire / j.prix) if j.prix else "—"], ""),
            ("Clients que l'équipe peut suivre", [M.fmt_n(cap)], ""),
            ("Charge de l'équipe", [pct(h["utilisation"]) if h else "—"], "")]).pack(fill="x")
        texte_libre(c2, "• La R&D fait mûrir le produit : un produit mûr attire plus de clients et en perd moins.\n"
                    "• Une attrition de 2 % par mois, c'est un client qui reste 4 ans ; à 5 %, moins de 2 ans.\n"
                    "• Règle d'or : un client doit rapporter au moins 3 fois ce qu'il a coûté à acquérir (LTV/CAC ≥ 3).\n"
                    "• Les levées de fonds valorisent le revenu récurrent : c'est le moment de lever quand le MRR "
                    "grimpe.", largeur=380, pady=(10, 0))

    # ---------------------------------------------------------------- biotech
    def act_biotech(self, z):
        j = self.m.joueur
        a = j.act
        brule = a.cout_mois + j.charges_fixes() + j.mkt + j.qinv
        aut = (j.tresorerie + j.placements) / brule if brule > 0 else 99
        cliniques = [x for x in a.molecules if x.en_clinique]
        rangee_kpis(z, [
            ("Valeur du pipeline", court(a.pipeline()), "rNPV : valeur ajustée du risque d'échec", TXT),
            ("Autonomie de trésorerie", f"{max(0.0, aut):.0f} mois", f"vous brûlez {court(brule)} par mois",
             ROUGE if aut < 6 else VERT if aut > 12 else AMBRE),
            ("Molécules en clinique", str(len(cliniques)),
             "une seule : c'est quitte ou double" if len(cliniques) <= 1 else "risque réparti",
             ROUGE if len(cliniques) <= 1 else VERT),
            ("Chercheurs", f"{a.capacite():.0f} pour {a.besoin_personnel():.0f}", "capacité / besoin des essais",
             ROUGE if a.besoin_personnel() > a.capacite() else TXT)]).pack(fill="x")
        g, d = self.deux_colonnes(z, (5, 2))
        c = Carte(g, "Pipeline clinique", "Chaque phase réussie multiplie la valeur d'une molécule ; un échec la "
                  "réduit à néant. Si votre dernière molécule en clinique échoue, les investisseurs se retirent.")
        c.pack(fill="both", expand=True)
        statuts = {"actif": "", "pause": "⏸ en pause", "licencie": "", "echec": "❌ échec",
                   "abandonne": "abandonnée", "commercialise": "✅ sur le marché"}
        ordre = sorted(a.molecules, key=lambda x: (x.statut in ("echec", "abandonne"), -x.phase, -x.avancement))
        for mol in ordre[:7]:
            mort = mol.statut in ("echec", "abandonne")
            l = self.rangee(c)
            bt = tk.Frame(l, bg=PANNEAU2)
            bt.pack(side="right")
            gauche = tk.Frame(l, bg=PANNEAU2)
            gauche.pack(side="left", fill="x", expand=True)
            haut = tk.Frame(gauche, bg=PANNEAU2)
            haut.pack(fill="x")
            tk.Label(haut, text=f"💊 {mol.nom}", font=police(10, True), bg=PANNEAU2,
                     fg=DISCRET if mort else TXT).pack(side="left")
            tk.Label(haut, text=f"  {mol.indication} · ventes au pic {court(mol.potentiel)}/an", font=police(9),
                     bg=PANNEAU2, fg=MUT).pack(side="left")
            bas = tk.Frame(gauche, bg=PANNEAU2)
            bas.pack(fill="x", pady=(3, 0))
            tk.Label(bas, text=mol.libelle_phase, font=police(9, True), bg=PANNEAU2,
                     fg=DISCRET if mort else ACC_SURVOL, width=14, anchor="w").pack(side="left")
            if mol.phase < 5 and not mort:
                barre(bas, mol.avancement, 110).pack(side="left", padx=(0, 8))
                succes = a.proba(mol.phase) if mol.statut != "licencie" else min(0.95, M.PHASES[mol.phase][3] * 1.1)
                tk.Label(bas, text=f"{pct(mol.avancement)} · succès ≈ {pct(succes)} · valeur {court(a.rnpv(mol))}",
                         font=police(9), bg=PANNEAU2, fg="#cfcfcf").pack(side="left")
            elif not mort:
                tk.Label(bas, text=f"valeur {court(a.rnpv(mol))}", font=police(9), bg=PANNEAU2, fg="#cfcfcf"
                         ).pack(side="left")
            etat = statuts[mol.statut]
            if mol.statut == "licencie":
                etat = f"🤝 chez {mol.partenaire} (royalties {pct(mol.royalties)})"
            if mol.accelere:
                etat = "⏩ accéléré"
            if mol.recherche_partenaire:
                etat += " · on cherche un partenaire"
            if etat:
                tk.Label(bas, text=etat, font=police(9, True), bg=PANNEAU2, fg=AMBRE).pack(side="left", padx=8)

            def bouton(txt, cmd, style="fantome"):
                Bouton(bt, txt, cmd, style, taille=8, padx=6, pady=2).pack(side="left", padx=(4, 0))
            if mol.statut == "actif" and mol.phase < 5:
                bouton("Rythme normal" if mol.accelere else "Accélérer",
                       lambda mol=mol: self.action(a.accelerer(mol), "mut"), "secondaire")
                bouton("Pause", lambda mol=mol: self.action(a.pause(mol), "mut"))
                if mol.phase >= 1 and not mol.recherche_partenaire:
                    bouton("Licencier…", lambda mol=mol: self.action("🤝 " + a.chercher_partenaire(mol), "mut"))
                bouton("Abandonner", lambda mol=mol: self.abandonner_molecule(mol), "danger")
            elif mol.statut == "pause":
                bouton("Reprendre", lambda mol=mol: self.action(a.pause(mol), "mut"), "secondaire")
                bouton("Abandonner", lambda mol=mol: self.abandonner_molecule(mol), "danger")
        c2 = Carte(d, "Les étapes", "Coût mensuel et chance de succès de chaque étape (avec votre qualité "
                   "scientifique actuelle).")
        c2.pack(fill="both", expand=True)
        tableau(c2, ["", "Durée", "Coût/mois", "Succès"],
                [(nom, [f"{duree} mois", court(cout), pct(a.proba(i))], "")
                 for i, (nom, duree, cout, _, _) in enumerate(M.PHASES)]).pack(fill="x")
        texte_libre(c2, "• Accélérer : 50 % plus vite, 60 % plus cher.\n• Licencier : un grand laboratoire paie "
                    "tout de suite, finance les essais restants, puis vous verse des jalons et des royalties.\n"
                    "• Le budget « Recherche » fait découvrir de nouvelles molécules.\n• Chaque phase réussie ouvre "
                    "une subvention Bpifrance et fait grimper la valorisation : levez juste après !",
                    largeur=300, pady=(10, 0))

    def abandonner_molecule(self, mol):
        i, _ = self.dialogue(f"Abandonner {mol.nom} ?", f"Ses dépenses s'arrêtent, mais toute sa valeur "
                             f"({court(self.m.joueur.act.rnpv(mol))} ajustés du risque) disparaît.",
                             ("Abandonner", "Annuler"), "⚠", ROUGE)
        if i == 0:
            self.action(self.m.joueur.act.abandonner(mol), "mauvais")

    # ---------------------------------------------------------------- jeu vidéo
    def act_jeu(self, z):
        j = self.m.joueur
        a = j.act
        p = a.projet
        if p:
            note = M.note_attendue(p.qualite, p.avancement)
            reste = p.charge * max(0.0, 1 - p.avancement) / max(1.0, a.capacite())
            rangee_kpis(z, [
                (f"« {p.nom} » ({p.libelle})", pct(min(p.avancement, 9.99)),
                 "prêt à sortir !" if p.avancement >= 1 else "avancement du développement",
                 VERT if p.avancement >= 1 else TXT),
                ("Wishlists", M.fmt_n(p.wishlists), f"≈ {pct(M.conversion(M.note_attendue(p.qualite, 1.0)))} "
                 "achèteront à la sortie", TXT),
                ("Note attendue", f"{note:.0f}/100", f"si le jeu sortait maintenant (qualité {p.qualite:.0f})",
                 VERT if note >= 72 else ROUGE if note < 55 else AMBRE),
                ("Temps restant", f"≈ {reste:.0f} mois" if p.avancement < 1 else "terminé",
                 f"votre équipe : {a.capacite():.1f} personnes-mois par mois".replace(".", ","), TXT)]).pack(fill="x")
        else:
            h = j.historique[-1] if j.historique else None
            rangee_kpis(z, [("Jeux sortis", str(len(a.catalogue)), "", TXT),
                            ("Ventes du mois", M.fmt_n(h["ventes"]) if h else "—", "copies, tous jeux confondus", TXT),
                            (j.s.libelle_notoriete, f"{j.notoriete:.0f}/100", "vos fans achètent vos jeux", TXT)]
                        ).pack(fill="x")
        g, d = self.deux_colonnes(z)
        if p:
            c = Carte(g, "Projet en cours", "Pas un euro de revenu avant la sortie. Le mois du lancement décide de "
                      "tout : sortez un jeu fini, quand les wishlists sont au plus haut, et évitez les mois chargés.")
            c.pack(fill="x")
            l = tk.Frame(c, bg=PANNEAU)
            l.pack(fill="x")
            tk.Label(l, text=f"🎮  {p.nom}", font=police(13, True), bg=PANNEAU, fg=TXT).pack(side="left")
            tk.Label(l, text=f"jeu {p.libelle}", font=police(9, True), bg=PANNEAU2, fg=ACC_SURVOL, padx=6
                     ).pack(side="left", padx=10)
            barre(c, min(p.avancement, 1.0), 420, 10, repere=0.8).pack(anchor="w", pady=(8, 2))
            infos = f"Prix de sortie : {prix_txt(self.v_prix.get())} (curseur du tableau de bord)."
            if p.editeur:
                infos += (f" Éditeur : {p.editeur['nom']} — avance de {court(p.editeur['avance'])}, "
                          f"encore {court(p.editeur['restant'])} à lui rembourser sur les ventes.")
            texte_libre(c, infos, largeur=600, pady=(4, 0))
            bts = tk.Frame(c, bg=PANNEAU)
            bts.pack(fill="x", pady=(8, 0))
            if p.lancer:
                tk.Label(bts, text="🚀 Sortie prévue à la fin du mois", font=police(10, True), bg=PANNEAU, fg=VERT
                         ).pack(side="left")
                Bouton(bts, "Repousser", lambda: self.action(a.annuler_lancement(), "mut"), "secondaire", taille=9
                       ).pack(side="left", padx=10)
            else:
                b = Bouton(bts, "Sortir le jeu…", self.sortir_jeu, "vert")
                b.pack(side="left")
                b.activer(p.avancement >= 0.8)
            if not p.editeur:
                b = Bouton(bts, "Signer avec un éditeur…", self.signer_editeur, "secondaire")
                b.pack(side="left", padx=8)
                b.activer(p.avancement >= 0.15)
        else:
            c = Carte(g, "Lancer un nouveau projet", "Plus le jeu est ambitieux, plus il coûte cher et long à "
                      "développer… et plus il peut rapporter. Recrutez pour aller plus vite.")
            c.pack(fill="x")
            for env, (lib, charge, prix, portee) in M.ENVERGURES.items():
                duree = charge / max(1.0, a.capacite())
                l = self.rangee(c)
                tk.Label(l, text=f"Jeu {lib}", font=police(11, True), bg=PANNEAU2, fg=TXT, width=8, anchor="w"
                         ).pack(side="left")
                tk.Label(l, text=f"{charge} personnes-mois (≈ {duree:.0f} mois avec votre équipe) · ≈ "
                         f"{court(charge * j.s.salaire)} de salaires · vendu {prix} € · audience × {portee:g}",
                         font=police(9), bg=PANNEAU2, fg="#cfcfcf", wraplength=460, justify="left").pack(side="left")
                Bouton(l, "Lancer", lambda env=env: self.nouveau_jeu(env), "primaire", taille=9, padx=10, pady=3
                       ).pack(side="right")
        c = Carte(g, "Jeux sortis")
        c.pack(fill="both", expand=True, pady=(12, 0))
        if not a.catalogue:
            texte_libre(c, "Aucun jeu sorti pour l'instant.", largeur=500)
        for jj in reversed(a.catalogue[-5:]):
            l = self.rangee(c)
            tk.Label(l, text=f"{jj.nom}", font=police(10, True), bg=PANNEAU2, fg=TXT).pack(side="left")
            tk.Label(l, text=f"  {jj.libelle} · sorti en {jj.date_sortie} · {M.fmt_n(jj.lancement)} copies le 1er mois"
                     f" · {M.fmt_n(jj.ventes_total)} au total", font=police(9), bg=PANNEAU2, fg=MUT).pack(side="left")
            tk.Label(l, text=f"{jj.note:.0f}/100", font=police(11, True), bg=PANNEAU2,
                     fg=VERT if jj.note >= 72 else AMBRE if jj.note >= 55 else ROUGE).pack(side="right")
        c2 = Carte(d, "Wishlists et ventes", "Le marketing fait monter les wishlists (surtout passé 25 % de "
                   "développement) ; elles se convertissent en ventes le jour de la sortie, selon la note.")
        c2.pack(fill="both", expand=True)
        reels = j.mois_reels()
        self.courbe(c2, 220, lambda can: graphe_series(
            can, [("Wishlists du projet", [h["kpi"].get("wishlists", 0.0) for h in reels], ACC)], M.fmt_n,
            barres=("Copies vendues", [h["ventes"] for h in reels], "#343434"), dates=[h["date"] for h in reels]))
        texte_libre(c2, "Note de la critique : elle dépend de la qualité (budget « Polish et tests », moral, talents) "
                    "et de l'avancement — un jeu sorti inachevé est sanctionné. Plusieurs jeux qui sortent le même "
                    "mois se partagent les joueurs.", largeur=380, pady=(8, 0))

    def nouveau_jeu(self, env):
        msg = self.m.joueur.act.nouveau_projet(env)
        self.v_prix.set(M.ENVERGURES[env][2])
        self.action("🎮 " + msg, "bon")

    def sortir_jeu(self):
        j = self.m.joueur
        p = j.act.projet
        note = M.note_attendue(p.qualite, p.avancement)
        i, _ = self.dialogue(f"Sortir « {p.nom} » ?", f"Le jeu sortira à la fin du mois, à "
                             f"{prix_txt(self.v_prix.get())}.\nAvancement : {pct(min(p.avancement, 9.99))} · note "
                             f"attendue ≈ {note:.0f}/100 · {M.fmt_n(p.wishlists)} wishlists."
                             + ("\n\n⚠ Inachevé, il sera buggé et la critique le sanctionnera." if p.avancement < 1
                                else ""), ("Sortir le jeu", "Pas encore"), "🚀", VERT)
        if i == 0:
            self.action("🚀 " + j.act.demander_lancement(), "bon")

    def signer_editeur(self):
        j = self.m.joueur
        p = j.act.projet
        reste = p.charge * max(0.0, 1 - p.avancement) * j.s.salaire
        avance = max(50_000, round(0.6 * reste / 10_000) * 10_000)
        i, _ = self.dialogue("Signer avec un éditeur ?", f"Un éditeur vous verse ≈ {euros(avance)} d'avance tout de "
                             "suite et met son marketing au service du jeu (+30 % de wishlists). En échange, il prend "
                             "50 % des revenus nets jusqu'à récupérer son avance, puis 30 % pour toujours.",
                             ("Signer", "Annuler"), "✍", ACC)
        if i == 0:
            self.action("✍ " + j.act.signer_editeur(), "bon")

    # ---------------------------------------------------------------- luxe
    def act_luxe(self, z):
        j = self.m.joueur
        a = j.act
        pma = a.pma()
        h = j.historique[-1] if j.historique else None
        rangee_kpis(z, [
            ("Réputation", f"{j.notoriete:.0f}/100", "fait monter le prix accepté", TXT),
            ("Indice d'exclusivité", f"{a.exclusivite:.0f}/100", "la rareté perçue de la marque",
             VERT if a.exclusivite >= 60 else ROUGE if a.exclusivite < 35 else TXT),
            ("Prix maximal accepté", court(pma), f"votre prix : {pct(j.prix / pma)} du plafond",
             ROUGE if j.prix > pma else TXT),
            ("Liste d'attente", f"{M.fmt_n(a.attente)} pièce(s)", "des clients qui attendent : bon signe",
             VERT if a.attente >= 1 else TXT)]).pack(fill="x")
        g, d = self.deux_colonnes(z)
        c = Carte(g, "Politique de la maison", "Le luxe ne se vend pas en volume : la rareté et la réputation "
                  "permettent des prix que personne ne discute.")
        c.pack(fill="both", expand=True)
        capa = max(1, int(j.capacite()))
        self.v_quota = tk.IntVar(value=a.quota)

        def changer():
            a.quota = self.v_quota.get()
        curseur(c, "Pièces mises en vente chaque mois", self.v_quota, 0, max(10, int(capa * 1.5)), 1,
                lambda v: "toute la production" if int(float(v)) == 0 else f"{int(float(v))} pièces", changer)
        texte_libre(c, f"Vos artisans peuvent produire {capa} pièces par mois"
                    + (f" ; vous en avez vendu {M.fmt_n(h['ventes'])} le mois dernier." if h else ".")
                    + " Limiter l'offre crée une liste d'attente, qui renforce l'exclusivité ; vendre à tout le monde "
                    "banalise la marque.", largeur=560, pady=(6, 0))
        texte_libre(c, "• Ne baissez jamais vos prix : −10 % de prix, c'est −25 d'exclusivité et −12 de réputation.\n"
                    "• Le marketing (défilés, égéries) ne fait pas vendre davantage : il fait monter la réputation, "
                    "donc le prix que la clientèle accepte.\n• Au-delà de 35 % du marché, la marque est surexposée.\n"
                    "• Au-dessus du prix maximal accepté, les ventes s'effondrent.",
                    couleur="#d4d4d4", largeur=560, pady=(10, 0))
        c2 = Carte(d, "Votre prix et le plafond", "Montez votre prix à mesure que le plafond monte.")
        c2.pack(fill="both", expand=True)
        reels = j.mois_reels()
        self.courbe(c2, 220, lambda can: graphe_series(
            can, [("Prix maximal accepté", [h["kpi"].get("pma", 0.0) for h in reels], AMBRE),
                  ("Votre prix", [h["prix"] for h in reels], ACC)], M.fmt_c, dates=[h["date"] for h in reels]))

    # ---------------------------------------------------------------- aéronautique
    def act_aero(self, z):
        m = self.m
        j = m.joueur
        a = j.act
        rangee_kpis(z, [
            ("Carnet de commandes", court(a.carnet()), f"{len(a.actifs())} contrat(s) en cours", TXT),
            ("Charge / capacité", pct(a.charge_mois), f"capacité : {a.capacite():.0f} personnes-mois par mois",
             ROUGE if a.charge_mois > 1.05 else TXT),
            ("Pénalités de retard", court(a.penalites), "cumulées depuis le début", ROUGE if a.penalites else VERT),
            ("Crédibilité technique", f"{j.notoriete:.0f}/100", "elle ouvre les plus gros appels d'offres", TXT)]
        ).pack(fill="x")
        g, d = self.deux_colonnes(z, (1, 1))
        c = Carte(g, "Contrats en cours", "Chaque quart réalisé est facturé au client (jalon). En retard, vous "
                  "payez chaque mois 1,5 % du contrat de pénalités.")
        c.pack(fill="both", expand=True)
        actifs = a.actifs()
        if not actifs:
            texte_libre(c, "Aucun contrat en cours : répondez aux appels d'offres, sinon votre équipe coûte sans "
                        "rien produire.", couleur=ROUGE, largeur=480)
        for ct in actifs[:5]:
            l = self.rangee(c)
            t = tk.Frame(l, bg=PANNEAU2)
            t.pack(fill="x")
            tk.Label(t, text=f"📦 {ct.objet}", font=police(10, True), bg=PANNEAU2, fg=TXT).pack(side="left")
            tk.Label(t, text=court(ct.montant), font=police(10, True), bg=PANNEAU2, fg=TXT).pack(side="right")
            retard = m.mois > ct.echeance
            tk.Label(l, text=f"{ct.client} · livraison prévue : {m.date(ct.echeance - m.mois)}"
                     + (f" · ⚠ en retard, {court(ct.penalites)} de pénalités" if retard else ""),
                     font=police(9), bg=PANNEAU2, fg=ROUGE if retard else MUT).pack(anchor="w")
            b = tk.Frame(l, bg=PANNEAU2)
            b.pack(fill="x", pady=(3, 0))
            barre(b, ct.avancement, 220).pack(side="left")
            tk.Label(b, text=f"  {pct(ct.avancement)} · jalons facturés {ct.jalons}/4", font=police(9), bg=PANNEAU2,
                     fg="#cfcfcf").pack(side="left")
        livres = [x for x in a.contrats if x.livre]
        if livres:
            texte_libre(c, f"{len(livres)} contrat(s) déjà livré(s).", largeur=480, pady=(4, 0))
        c2 = Carte(d, "Appels d'offres ouverts", "Le client retient l'offre la mieux notée : le prix d'abord, puis "
                   "la qualité technique, la crédibilité et votre capacité à livrer. Des groupes étrangers "
                   "concourent aussi.")
        c2.pack(fill="both", expand=True)
        if not m.appels:
            texte_libre(c2, "Aucun appel d'offres en ce moment : il en arrive régulièrement (le budget de "
                        "prospection aide à les repérer et à gagner en crédibilité).", largeur=480)
        for ao in m.appels[:4]:
            l = self.rangee(c2)
            t = tk.Frame(l, bg=PANNEAU2)
            t.pack(fill="x")
            tk.Label(t, text=f"📣 {ao.objet}", font=police(10, True), bg=PANNEAU2, fg=TXT).pack(side="left")
            tk.Label(t, text=court(ao.montant), font=police(10, True), bg=PANNEAU2, fg=TXT).pack(side="right")
            rivaux = len([n for n in ao.offres if n != j.nom])
            tk.Label(l, text=f"{ao.client} · {ao.duree} mois · ≈ {ao.charge / ao.duree:.0f} personnes à plein temps · "
                     f"décision en {m.date(ao.decision - m.mois)} · {rivaux} concurrent(s) en lice", font=police(9),
                     bg=PANNEAU2, fg=MUT, wraplength=460, justify="left").pack(anchor="w")
            b = tk.Frame(l, bg=PANNEAU2)
            b.pack(fill="x", pady=(3, 0))
            if j.notoriete < ao.exigence:
                tk.Label(b, text=f"Crédibilité exigée : {ao.exigence:.0f} (vous : {j.notoriete:.0f})", font=police(9, True),
                         bg=PANNEAU2, fg=ROUGE).pack(side="left")
            elif j.nom in ao.offres:
                tk.Label(b, text=f"✓ Votre offre : {court(ao.offres[j.nom])}", font=police(9, True), bg=PANNEAU2,
                         fg=VERT).pack(side="left")
                Bouton(b, "Modifier…", lambda ao=ao: self.offre_ao(ao), "fantome", taille=8, padx=8, pady=2
                       ).pack(side="right")
            else:
                Bouton(b, "Répondre…", lambda ao=ao: self.offre_ao(ao), "primaire", taille=9, padx=10, pady=3
                       ).pack(side="right")
        if m.appels_clos:
            texte_libre(c2, "Derniers résultats : " + " · ".join(f"{ao.objet} → {ao.gagnant}"
                                                                   for ao in m.appels_clos[-3:]),
                        largeur=480, pady=(4, 0))

    def offre_ao(self, ao):
        m, j = self.m, self.m.joueur
        a = j.act
        pas = 10_000
        mini = int(ao.montant * 0.8 // pas * pas)
        maxi = int(ao.montant * 1.3 // pas * pas)
        depart = int(ao.offres.get(j.nom, ao.montant * 0.97) // pas * pas)
        charge = (a.charge_prevue(m.mois) + ao.charge / ao.duree) / max(1.0, a.capacite())

        def info(v):
            cout = ao.charge * j.s.salaire * j.salaire_mult + v * 0.30 * j.cout_unitaire
            marge = v - cout
            return (f"Marge estimée : {court(marge)} ({pct(marge / v)}) · votre prix : {pct(v / ao.montant - 1, True)} "
                    f"par rapport au budget du client. Si vous gagnez, votre charge passera à ≈ {pct(charge)} de "
                    "votre capacité" + (" : il faudra recruter, sinon retards et pénalités." if charge > 1.05 else "."),
                    marge < 0 or charge > 1.2)
        i, v = self.dialogue(f"Répondre à {ao.client}", f"« {ao.objet} » : budget {euros(ao.montant)}, {ao.duree} mois "
                             f"de travaux (≈ {M.fmt_n(ao.charge)} personnes-mois). Acompte de 20 % à la signature, puis "
                             "facturation par jalons.\nPlus votre prix est bas, plus vos chances montent — très vite.",
                             ("Déposer l'offre", "Annuler"), "📣", ACC, (mini, maxi, pas, depart), info, "Votre prix")
        if i == 0 and v:
            self.action("📣 " + m.deposer_offre(ao, float(v)), "mut")

    # ---------------------------------------------------------------- grande distribution
    def act_distribution(self, z):
        j = self.m.joueur
        a = j.act
        reels = j.mois_reels()
        der = reels[-3:]
        ca3 = sum(h["ca"] for h in der)
        mn = sum(h["resultat"] for h in der) / ca3 if ca3 else None
        rangee_kpis(z, [
            ("Rotation des stocks", f"{a.jours_stock():.0f} jours", f"stock {court(j.stocks)} · cible {a.jours_cible} j",
             TXT),
            ("Ruptures de stock", f"{a.rupture * 100:.1f} %".replace(".", ","), "commandes non servies le mois dernier",
             ROUGE if a.rupture > 0.03 else VERT),
            ("Fournisseurs", "comptant" if a.defaut else f"{j.delai_fournisseurs} jours",
             f"sous surveillance encore {a.defaut} mois" if a.defaut else "délai de paiement obtenu",
             ROUGE if a.defaut else VERT),
            ("Marge nette", pct(mn) if mn is not None else "—", "sur 3 mois · 2 à 5 % dans ce métier",
             TXT if mn is None else VERT if mn >= 0.02 else AMBRE if mn >= 0 else ROUGE)]).pack(fill="x")
        g, d = self.deux_colonnes(z)
        c = Carte(g, "Pilotage des stocks", "Chaque mois, vous commandez de quoi couvrir la demande prévue plus votre "
                  "stock de sécurité. Trop de stock : de l'argent qui dort et 1,2 % de frais de stockage par mois. "
                  "Trop peu : des ruptures et des clients perdus.")
        c.pack(fill="both", expand=True)
        self.v_jours = tk.IntVar(value=a.jours_cible)

        def changer():
            a.jours_cible = self.v_jours.get()
        curseur(c, "Stock de sécurité visé", self.v_jours, 5, 60, 1, lambda v: f"{int(float(v))} jours de ventes",
                changer)
        tk.Label(c, text="BESOIN EN FONDS DE ROULEMENT", font=police(8, True), bg=PANNEAU, fg=MUT).pack(anchor="w",
                                                                                                     pady=(14, 2))
        tableau(c, ["", ""], [("Stocks", [j.stocks], ""), ("+ Factures clients à encaisser", [j.total_creances], ""),
                              ("− Factures fournisseurs à payer", [-j.total_fournisseurs], ""),
                              ("= Besoin en fonds de roulement",
                               [j.stocks + j.total_creances - j.total_fournisseurs], "total")]).pack(fill="x")
        texte_libre(c, "Le secret de la distribution : vos clients paient comptant, vous payez vos fournisseurs à 60 "
                    "jours — ce sont eux qui financent vos stocks. Mais un seul impayé, et ils exigent d'être payés "
                    "comptant pendant 3 mois. Délais fournisseurs : page Banque.", largeur=560, pady=(8, 0))
        c2 = Carte(d, "Rotation des stocks", "Nombre de jours de ventes que représente votre stock.")
        c2.pack(fill="both", expand=True)
        self.courbe(c2, 220, lambda can: graphe_series(
            can, [("Jours de stock", [h["kpi"].get("rotation", 0.0) for h in reels], ACC)],
            lambda v: f"{v:.0f} j", ref=a.jours_cible, lib_ref="cible", dates=[h["date"] for h in reels]))

    # ---------------------------------------------------------------- énergie
    def act_energie(self, z):
        m = self.m
        j = m.joueur
        a = j.act
        mw = sum(x.mw for x in a.en_service())
        mw_t = sum(x.mw for x in a.centrales if x.etat == "travaux")
        variable = sum(p.capital_restant for p in j.prets if p.variable)
        rangee_kpis(z, [
            ("Parc en service", f"{mw:.0f} MW", f"+{mw_t:.0f} MW en construction" if mw_t else
             f"{len(a.projets)} projet(s) prêt(s) à construire", TXT),
            ("Rendement du capital (ROIC)", f"{a.roic() * 100:.1f} %".replace(".", ","),
             "à comparer au coût de votre dette", VERT if a.roic() > m.taux_ref + 0.018 else AMBRE),
            ("Prix de gros de l'électricité", f"{m.spot:.0f} €/MWh", f"moyenne récente {m.spot_moyen():.0f} €/MWh",
             TXT),
            ("Taux de référence", M.fmt_taux(m.taux_ref), f"dette à taux variable : {court(variable)}",
             AMBRE if m.taux_ref > 0.04 else TXT)]).pack(fill="x")
        g, d = self.deux_colonnes(z, (3, 2))
        c = Carte(g, "Vos centrales", "Au prix du marché, vos revenus suivent les flambées… et les effondrements. "
                  "Un contrat long (PPA) garantit un prix fixe pendant des années.")
        c.pack(fill="both", expand=True)
        icones = {"solaire": "☀", "eolien": "💨", "stockage": "🔋"}
        for ct in a.centrales[:6]:
            l = self.rangee(c)
            bt = tk.Frame(l, bg=PANNEAU2)
            bt.pack(side="right")
            gauche = tk.Frame(l, bg=PANNEAU2)
            gauche.pack(side="left", fill="x", expand=True)
            tk.Label(gauche, text=f"{icones.get(ct.type, '⚡')} {ct.nom} · {ct.mw:.0f} MW", font=police(10, True),
                     bg=PANNEAU2, fg=TXT).pack(anchor="w")
            if ct.etat == "travaux":
                txt, coul = f"◌ En construction : mise en service dans {ct.travaux} mois", ACC_SURVOL
            else:
                txt = (f"● {M.fmt_n(ct.production)} MWh produits · {court(ct.revenu)} de revenus le mois dernier"
                       if ct.type != "stockage" else f"● {court(ct.revenu)} de revenus le mois dernier")
                coul = VERT
            tk.Label(gauche, text=txt, font=police(9), bg=PANNEAU2, fg=coul).pack(anchor="w")
            sous_contrat = ct.ppa_prix is not None and m.mois < ct.ppa_fin
            if ct.type == "stockage":
                contrat = "Achète l'électricité quand elle est bon marché, la revend aux heures de pointe."
            elif sous_contrat:
                contrat = f"Contrat : {ct.ppa_prix:.1f} €/MWh garantis jusqu'en {m.date(ct.ppa_fin - m.mois)}".replace(
                    ".", ",", 1)
            else:
                contrat = "Vend au prix du marché"
            tk.Label(gauche, text=contrat, font=police(9), bg=PANNEAU2, fg=MUT).pack(anchor="w")
            if ct.type != "stockage" and not sous_contrat:
                Bouton(bt, "Contrat industriel…", lambda ct=ct: self.ppa(ct), "secondaire", taille=8, padx=6, pady=2
                       ).pack(anchor="e")
                if m.enchere and j.nom not in m.enchere["offres"]:
                    Bouton(bt, "Offre à l'État…", lambda ct=ct: self.enchere(ct), "primaire", taille=8, padx=6,
                           pady=2).pack(anchor="e", pady=(3, 0))
        if m.enchere:
            mon = m.enchere["offres"].get(j.nom)
            texte_libre(c, "📣 Appel d'offres de l'État en cours : 80 MW de contrats à 20 ans pour les offres les "
                        "moins chères. " + (f"Votre offre : {mon[1]:.1f} €/MWh pour « {mon[0].nom} »."
                                            .replace(".", ",", 1) if mon else "Déposez une offre avant la fin du mois."),
                        couleur=AMBRE, largeur=600, pady=(4, 0))
        c2 = Carte(d, "Projets prêts à construire", "Le budget de développement obtient les permis. Une centrale se "
                   "finance à 80 % par une dette de projet à taux variable (si votre note le permet).")
        c2.pack(fill="both", expand=True)
        l = tk.Frame(c2, bg=PANNEAU)
        l.pack(fill="x", pady=(0, 8))
        tk.Label(l, text="Prochain permis  ", font=police(9), bg=PANNEAU, fg=MUT).pack(side="left")
        barre(l, a.developpement / 100, 160).pack(side="left")
        if not a.projets:
            texte_libre(c2, "Aucun projet autorisé pour l'instant.", largeur=380)
        for p in a.projets:
            f = a.financement(p)
            l = self.rangee(c2)
            t = tk.Frame(l, bg=PANNEAU2)
            t.pack(fill="x")
            tk.Label(t, text=f"{icones.get(p.type, '⚡')} {p.nom}", font=police(10, True), bg=PANNEAU2, fg=TXT
                     ).pack(side="left")
            Bouton(t, "Construire…", lambda p=p: self.construire_centrale(p), "vert", taille=8, padx=8, pady=2
                   ).pack(side="right")
            lc = a.lcoe(p.type)
            tk.Label(l, text=f"{M.TYPES_CENTRALE[p.type][1]:.0f} MW · {court(f['capex'])}"
                     + (f" · coût de revient ≈ {lc:.0f} €/MWh" if lc else ""), font=police(9), bg=PANNEAU2,
                     fg="#cfcfcf", wraplength=380, justify="left").pack(anchor="w")
            tk.Label(l, text=f"Dette {court(f['dette'])} · subvention {court(f['subvention'])} · à apporter "
                     f"{court(f['fonds_propres'])}", font=police(9), bg=PANNEAU2,
                     fg=VERT if j.tresorerie >= f["fonds_propres"] else ROUGE, wraplength=380, justify="left").pack(anchor="w")
        c3 = Carte(d, "Prix de gros de l'électricité")
        c3.pack(fill="both", expand=True, pady=(12, 0))
        lcoe = a.lcoe("solaire")
        self.courbe(c3, 140, lambda can: graphe_series(
            can, [("€/MWh", m.spot_hist[-(m.duree + 1):], AMBRE)], lambda v: f"{v:.0f} €", ref=lcoe,
            lib_ref="coût de revient solaire"))

    def ppa(self, ct):
        m, j = self.m, self.m.joueur
        a = j.act
        prix = a.prix_ppa_industriel(m)
        i, _ = self.dialogue("Contrat avec un industriel", f"Un industriel gros consommateur propose d'acheter toute la "
                             f"production de « {ct.nom} » à {prix:.1f} €/MWh pendant 10 ans.\n\nPrix de marché actuel : "
                             f"{m.spot:.0f} €/MWh (moyenne récente {m.spot_moyen():.0f}). Votre coût de revient : "
                             f"≈ {a.lcoe(ct.type):.0f} €/MWh.\nUn revenu garanti rassure les banques, mais vous "
                             "renoncez aux flambées de prix.", ("Signer", "Refuser"), "⚡", ACC)
        if i == 0:
            self.action("⚡ " + a.signer_ppa(ct, prix, 10, len(j.historique)), "bon")

    def enchere(self, ct):
        m, j = self.m, self.m.joueur
        a = j.act
        lc = a.lcoe(ct.type)
        mini, maxi = max(20, int(lc * 0.8)), max(40, int(lc * 1.6))
        i, v = self.dialogue("Appel d'offres de l'État", f"Proposez un prix garanti pour « {ct.nom} » pendant 20 ans. "
                             "L'État retient les offres les moins chères, dans la limite de 80 MW et sous un prix "
                             "plafond qu'il ne dévoile pas.", ("Déposer l'offre", "Annuler"), "📣", ACC,
                             (mini, maxi, 1, min(maxi, max(mini, round(lc * 1.06)))),
                             lambda v: (f"Votre coût de revient : ≈ {lc:.0f} €/MWh. Marge : {pct(v / lc - 1, True)}."
                                        if lc else "", bool(lc) and v < lc), "Prix proposé",
                             fmt_curseur=lambda v: f"{float(v):.0f} €/MWh")
        if i == 0 and v:
            self.action("📣 " + m.offre_enchere(ct, float(v)), "mut")

    def construire_centrale(self, p):
        j = self.m.joueur
        a = j.act
        f = a.financement(p)
        lib, mw, capex, travaux, *_ = M.TYPES_CENTRALE[p.type]
        i, _ = self.dialogue(f"Construire « {p.nom} » ?", f"{mw:.0f} MW, {travaux} mois de travaux.\nInvestissement : "
                             f"{euros(f['capex'])}\n• dette de projet (15 ans, taux variable) : {euros(f['dette'])}\n"
                             f"• subvention d'investissement : {euros(f['subvention'])}\n• à apporter sur votre "
                             f"trésorerie : {euros(f['fonds_propres'])}\n\nTrésorerie après : "
                             f"{euros(j.tresorerie - f['fonds_propres'])}.", ("Construire", "Annuler"), "⚡", VERT)
        if i == 0:
            msg = a.construire(p)
            self.action("⚡ " + msg, "bon" if msg.startswith("Construction") else "mauvais")

    # ------------------------------------------------------------ page : concurrence
    def construire_conc(self, p):
        self.cartes_conc = tk.Frame(p, bg=FOND)
        self.cartes_conc.pack(fill="x")
        c = Carte(p, "Parts de marché", "Chaque mois, les clients se répartissent selon le prix, la notoriété, "
                  "la qualité et la satisfaction.")
        c.pack(fill="both", expand=True, pady=(12, 0))
        self.g_parts = tk.Canvas(c, bg=PANNEAU, highlightthickness=0, height=200)
        self.g_parts.pack(fill="both", expand=True)
        self.g_parts.bind("<Configure>", lambda _: graphe_parts(self.g_parts, self.m.entreprises))

    def maj_conc(self):
        zone = self.cartes_conc
        for w in zone.winfo_children():
            w.destroy()
        s = self.m.s
        classes = self.m.classement()
        n = len(classes)
        colonnes = 3 if n > 4 else max(1, n)
        for i, e in enumerate(classes):
            h = e.historique[-1] if e.historique else None
            carte = tk.Frame(zone, bg=PANNEAU, highlightthickness=2 if e.joueur else 1,
                             highlightbackground=e.couleur if e.joueur else BORD)
            carte.grid(row=i // colonnes, column=i % colonnes, sticky="nsew",
                       padx=(0 if i % colonnes == 0 else 10, 0), pady=(0 if i < colonnes else 10, 0))
            zone.columnconfigure(i % colonnes, weight=1, uniform="c")
            tk.Frame(carte, bg=e.couleur if e.actif else "#3a3a3a", height=4).pack(fill="x")
            corps = tk.Frame(carte, bg=PANNEAU, padx=14, pady=10)
            corps.pack(fill="both", expand=True)
            t = tk.Frame(corps, bg=PANNEAU)
            t.pack(fill="x")
            tk.Label(t, text=f"#{i + 1}" if e.actif else "—", font=police(10, True), bg=PANNEAU2,
                     fg=AMBRE if i == 0 and e.actif else TXT, padx=6).pack(side="left")
            tk.Label(t, text=("★ " if e.joueur else "") + e.nom, font=police(11, True), bg=PANNEAU,
                     fg=TXT if e.actif else DISCRET, padx=8).pack(side="left")
            tk.Label(t, text="vous" if e.joueur else e.strategie.nom.replace(" financée", ""), font=police(8, True),
                     bg=PANNEAU2, fg=e.couleur if e.actif else DISCRET, padx=6, pady=1).pack(side="right")
            if not e.actif:
                tk.Label(corps, text=e.fin_raison.capitalize(), font=police(12, True), bg=PANNEAU, fg=ROUGE
                         ).pack(anchor="w", pady=(8, 0))
                continue
            mil = tk.Frame(corps, bg=PANNEAU)
            mil.pack(fill="x", pady=(6, 0))
            tk.Label(mil, text=pct(h["part"]) if h else "—", font=police(22, True), bg=PANNEAU, fg=e.couleur
                     ).pack(side="left")
            tk.Label(mil, text=" du marché", font=police(9), bg=PANNEAU, fg=MUT).pack(side="left", pady=(10, 0))
            etat = ("en difficulté", ROUGE) if e.tresorerie < e.charges_fixes() or e.note in "DE" else ("en forme", VERT)
            tk.Label(mil, text="● " + etat[0], font=police(9, True), bg=PANNEAU, fg=etat[1]).pack(side="right")
            g = tk.Frame(corps, bg=PANNEAU)
            g.pack(fill="x", pady=(6, 0))
            infos = [("Prix", prix_txt(e.prix, s)) if s.decisions.get("prix") else ("Salariés", str(e.salaries)),
                     ("CA du mois", court(h["ca"]) if h else "—"),
                     ("Valeur", court(e.valorisation())), (s.libelle_notoriete, f"{e.notoriete:.0f}/100"),
                     ("Trésorerie", court(e.tresorerie)), ("Note de crédit", e.note)]
            for k, (lib, val) in enumerate(infos):
                tk.Label(g, text=lib, font=police(8), bg=PANNEAU, fg=MUT).grid(row=(k // 2) * 2, column=k % 2,
                                                                               sticky="w")
                tk.Label(g, text=val, font=police(10, True), bg=PANNEAU, fg=TXT).grid(row=(k // 2) * 2 + 1,
                                                                                      column=k % 2, sticky="w")
                g.columnconfigure(k % 2, weight=1)
            tk.Label(corps, text=e.act.resume(), font=police(9, True), bg=PANNEAU, fg=ACC_SURVOL, wraplength=260,
                     justify="left").pack(anchor="w", pady=(6, 0))
            if e.ameliorations:
                tk.Label(corps, text="Investissements : " + ", ".join(e.ameliorations_secteur()[c].nom.lower()
                                                                       for c in e.ameliorations),
                         font=police(8), bg=PANNEAU, fg=MUT, wraplength=220, justify="left").pack(anchor="w",
                                                                                                  pady=(6, 0))
            if not e.joueur and not self.m.fin:
                pied = tk.Frame(corps, bg=PANNEAU)
                pied.pack(fill="x", pady=(8, 0))
                b = Bouton(pied, f"Refuse de négocier ({e.refus_rachat} mois)" if e.refus_rachat else "Racheter…",
                           lambda e=e: self.racheter(e), "secondaire", taille=9, padx=10, pady=4)
                b.pack(side="left")
                b.activer(not e.refus_rachat)
                tk.Label(pied, text=f"{e.salaries} salarié(s)", font=police(8), bg=PANNEAU, fg=MUT).pack(side="right")

    # ------------------------------------------------------------ page : investir
    def construire_inv(self, p):
        tk.Label(p, text="Des paris sur l'avenir : ils coûtent cher et rapportent sur la durée. Payés comptant, ils "
                 "sont amortis sur 5 ans ; en crédit-bail, vous les payez par loyers. Vos concurrents investissent "
                 "aussi.", font=police(10), bg=FOND, fg=MUT, wraplength=1040, justify="left").pack(anchor="w")
        self.cartes_inv = tk.Frame(p, bg=FOND)
        self.cartes_inv.pack(fill="both", expand=True, pady=(10, 0))

    def maj_inv(self):
        zone = self.cartes_inv
        for w in zone.winfo_children():
            w.destroy()
        j = self.m.joueur
        for i, (cle, a) in enumerate(j.ameliorations_secteur().items()):
            carte = Carte(zone)
            carte.grid(row=i // 3, column=i % 3, sticky="nsew", padx=(0 if i % 3 == 0 else 12, 0),
                       pady=(0 if i < 3 else 12, 0))
            zone.columnconfigure(i % 3, weight=1, uniform="i")
            niveau = j.ameliorations.get(cle, 0)
            t = tk.Frame(carte, bg=PANNEAU)
            t.pack(fill="x")
            tk.Label(t, text=a.icone, font=police(20), bg=PANNEAU, fg=ACC).pack(side="left")
            tk.Label(t, text="  " + a.nom, font=police(12, True), bg=PANNEAU, fg=TXT
                     ).pack(side="left")
            tk.Label(t, text="●" * niveau + "○" * (a.niveaux - niveau), font=police(12), bg=PANNEAU,
                     fg=VERT).pack(side="right")
            tk.Label(carte, text=a.effet, font=police(10), bg=PANNEAU, fg="#d4d4d4", wraplength=300,
                     justify="left").pack(anchor="w", pady=(8, 4))
            deja = [e.nom for e in self.m.concurrents if e.actif and cle in e.ameliorations]
            tk.Label(carte, text=("Déjà fait par : " + ", ".join(deja)) if deja else "Aucun concurrent ne l'a fait.",
                     font=police(8), bg=PANNEAU, fg=MUT, wraplength=300, justify="left").pack(anchor="w")
            bas = tk.Frame(carte, bg=PANNEAU)
            bas.pack(fill="x", pady=(10, 0))
            if j.peut_ameliorer(cle):
                cout = j.cout_amelioration(cle)
                prix = tk.Frame(bas, bg=PANNEAU)
                prix.pack(side="left")
                tk.Label(prix, text=court(cout), font=police(13, True), bg=PANNEAU, fg=TXT).pack(anchor="w")
                tk.Label(prix, text=f"ou {M.DUREE_CREDIT_BAIL} × {euros(j.loyer_credit_bail(cle))} en crédit-bail",
                         font=police(8), bg=PANNEAU, fg=MUT).pack(anchor="w")
                b = Bouton(bas, "Investir…", lambda c=cle: self.investir(c), "vert")
                b.pack(side="right")
                b.activer(j.tresorerie >= cout or j.note != "E")
            else:
                tk.Label(bas, text="✔ Niveau maximum atteint", font=police(10, True), bg=PANNEAU, fg=VERT
                         ).pack(side="left")

    # ------------------------------------------------------------ page : équipe
    def construire_equipe(self, p):
        self.page_equipe = p
        self.zone_equipe = tk.Frame(p, bg=FOND)
        self.zone_equipe.pack(fill="both", expand=True)

    def maj_equipe(self):
        if self.page != "equipe":
            return
        self.zone_equipe.destroy()
        z = self.zone_equipe = tk.Frame(self.page_equipe, bg=FOND)
        z.pack(fill="both", expand=True)
        j, s = self.m.joueur, self.m.s
        jg = j.act.jauge()
        haut = tk.Frame(z, bg=FOND)
        haut.pack(fill="x")
        for i, (lib, val, coul) in enumerate([
                ("Effectif", f"vous + {j.salaries}", TXT),
                ("Masse salariale", euros(j.masse_salariale()) + "/mois", TXT),
                ("Capacité", "—" if isinstance(j.act, M.ActiviteEnergie) else M.fmt_n(j.capacite()), TXT),
                (jg[0], jg[2], couleur_note(jg[1], jg[3])),
                ("Moral de l'équipe", f"{j.moral:.0f}/100", couleur_note(j.moral))]):
            c = tk.Frame(haut, bg=PANNEAU, highlightthickness=1, highlightbackground=BORD, padx=14, pady=8)
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            haut.columnconfigure(i, weight=1, uniform="e")
            tk.Label(c, text=lib.upper(), font=police(8, True), bg=PANNEAU, fg=MUT).pack(anchor="w")
            tk.Label(c, text=val, font=police(15, True), bg=PANNEAU, fg=coul).pack(anchor="w")

        corps = tk.Frame(z, bg=FOND)
        corps.pack(fill="both", expand=True, pady=(12, 0))
        corps.columnconfigure(0, weight=3, uniform="q")
        corps.columnconfigure(1, weight=2, uniform="q")
        corps.rowconfigure(0, weight=1)
        g = Carte(corps, "Votre équipe", "Chacun a son salaire, son moral et ses exigences. Une exigence non "
                  "respectée trois mois d'affilée, ou un moral au plus bas, et il démissionne.")
        g.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        equipiers = [e for e in j.equipe if e.nom == "Équipier"]      # anonymes (rachats, anciens recrutements)
        nommes = [e for e in j.equipe if e.nom != "Équipier"]
        if not j.equipe:
            texte_libre(g, "Vous travaillez seul pour l'instant. Recrutez parmi les candidats du mois, à droite.",
                        largeur=560)
        ratio_prix = j.prix / s.prix_ref if s.prix_ref else 1.0
        for e in sorted(nommes, key=lambda e: -e.salaire):
            l = tk.Frame(g, bg=PANNEAU2, padx=10, pady=6)
            l.pack(fill="x", pady=(0, 6))
            tk.Label(l, text=e.p.icone, font=police(16), bg=PANNEAU2, fg=TXT, width=2).pack(side="left")
            dr = tk.Frame(l, bg=PANNEAU2)
            dr.pack(side="right")
            mil = tk.Frame(l, bg=PANNEAU2, padx=8)
            mil.pack(side="left", fill="x", expand=True)
            ligne = tk.Frame(mil, bg=PANNEAU2)
            ligne.pack(fill="x")
            tk.Label(ligne, text=e.nom, font=police(10, True), bg=PANNEAU2, fg=TXT).pack(side="left")
            tk.Label(ligne, text=f"  {j.titre(e)}" + (f"  · ex-{e.origine}" if e.origine else "")
                     + f"  · {e.anciennete} mois", font=police(9), bg=PANNEAU2, fg=MUT).pack(side="left")
            ok = j.exigence_ok(e, ratio_prix)
            exi = j.exigence_texte(e)
            tk.Label(mil, text=("✓ " if ok else "⚠ ") + exi, font=police(8), bg=PANNEAU2, fg=MUT if ok else AMBRE,
                     wraplength=390, justify="left").pack(anchor="w")
            tk.Label(dr, text=euros(e.salaire * j.salaire_mult) + "/mois", font=police(10, True), bg=PANNEAU2,
                     fg=TXT).grid(row=0, column=0, columnspan=2, sticky="e")
            barre = tk.Canvas(dr, width=90, height=8, bg="#2c2c2c", highlightthickness=0)
            barre.grid(row=1, column=0, columnspan=2, sticky="e", pady=3)
            barre.create_rectangle(0, 0, 90 * e.moral / 100, 8, fill=couleur_note(e.moral), outline="")
            Bouton(dr, "+10 %", lambda e=e: self.augmenter(e), "fantome", taille=8, padx=6, pady=1).grid(
                row=2, column=0, sticky="e")
            Bouton(dr, "Licencier", lambda e=e: self.licencier(e), "danger", taille=8, padx=6, pady=1).grid(
                row=2, column=1, sticky="e", padx=(4, 0))
        if equipiers:
            l = tk.Frame(g, bg=PANNEAU2, padx=10, pady=6)
            l.pack(fill="x", pady=(0, 6))
            tk.Label(l, text="👤", font=police(16), bg=PANNEAU2, fg=TXT, width=2).pack(side="left")
            dr = tk.Frame(l, bg=PANNEAU2)
            dr.pack(side="right")
            mil = tk.Frame(l, bg=PANNEAU2, padx=8)
            mil.pack(side="left", fill="x", expand=True)
            tk.Label(mil, text=f"Équipiers polyvalents × {len(equipiers)}", font=police(10, True), bg=PANNEAU2,
                     fg=TXT).pack(anchor="w")
            orig = sorted({e.origine for e in equipiers if e.origine})
            tk.Label(mil, text="Produisent comme des salariés standards." + (f" Venus de : {', '.join(orig)}."
                                                                             if orig else ""),
                     font=police(8), bg=PANNEAU2, fg=MUT).pack(anchor="w")
            tk.Label(dr, text=euros(j.s.salaire * j.salaire_mult) + "/mois chacun", font=police(10, True),
                     bg=PANNEAU2, fg=TXT).pack(anchor="e")
            Bouton(dr, "Licencier un équipier", lambda: self.licencier(equipiers[-1]), "danger", taille=8, padx=6,
                   pady=1).pack(anchor="e", pady=(3, 0))

        d = Carte(corps, "Candidats ce mois-ci", "De nouveaux profils chaque mois. Proposez un salaire : en dessous de "
                  "leur prétention, ils risquent de refuser.")
        d.grid(row=0, column=1, sticky="nsew")
        if not j.vivier:
            texte_libre(d, "Plus de candidat ce mois-ci : il en viendra d'autres le mois prochain.", largeur=380)
        for c in j.vivier:
            k = tk.Frame(d, bg=PANNEAU2, padx=12, pady=8)
            k.pack(fill="x", pady=(0, 8))
            t = tk.Frame(k, bg=PANNEAU2)
            t.pack(fill="x")
            tk.Label(t, text=f"{c.p.icone}  {c.nom}", font=police(11, True), bg=PANNEAU2, fg=TXT).pack(side="left")
            tk.Label(t, text=etoiles(c.talent), font=police(10), bg=PANNEAU2, fg=AMBRE).pack(side="right")
            tk.Label(k, text=j.titre(c), font=police(9, True), bg=PANNEAU2, fg=ACC_SURVOL).pack(anchor="w")
            tk.Label(k, text=c.p.effet, font=police(8), bg=PANNEAU2, fg="#cfcfcf", wraplength=360,
                     justify="left").pack(anchor="w", pady=(2, 0))
            tk.Label(k, text="Exigence : " + j.exigence_texte(c), font=police(8), bg=PANNEAU2, fg=AMBRE, wraplength=360,
                     justify="left").pack(anchor="w", pady=(2, 0))
            b = tk.Frame(k, bg=PANNEAU2)
            b.pack(fill="x", pady=(6, 0))
            tk.Label(b, text=f"Prétention : {euros(c.pretention)}/mois", font=police(10, True), bg=PANNEAU2,
                     fg=TXT).pack(side="left")
            Bouton(b, "Négocier…", lambda c=c: self.negocier(c), "primaire", taille=9, padx=10, pady=3).pack(
                side="right")

    def negocier(self, c):
        j = self.m.joueur
        mini = int(c.pretention * 0.8 // 50 * 50)
        maxi = int(c.pretention * 1.3 // 50 * 50)

        def info(v):
            ch = M.chance_acceptation(v / c.pretention)
            txt = (f"Chance qu'il accepte : {ch:.0%}. Coût : {euros(v * 12)} par an + {euros(j.frais_recrutement(c))} "
                   "de frais de recrutement.").replace("%", " %")
            if c.profil == "star":
                txt += " Il recevra 2 % du capital."
            if c.profil == "commercial":
                txt += " Plus 3 % de commission sur le chiffre d'affaires."
            if v > c.pretention:
                txt += " Mieux payé que prévu : il démarrera très motivé."
            return txt, ch < 0.5
        texte = (f"{j.titre(c)} · talent {etoiles(c.talent)}\n{c.p.effet}\nExigence : {j.exigence_texte(c)}\n"
                 f"Prétention : {euros(c.pretention)} par mois (salaire chargé).")
        i, v = self.dialogue(f"Recruter {c.nom}", texte, ("Faire l'offre", "Annuler"), c.p.icone, ACC,
                             (mini, maxi, 50, int(c.pretention)), info, "Salaire proposé")
        if i != 0 or not v:
            return
        ok, msg = j.embaucher(c, v)
        self.ecrire(("👋 " if ok else "✖ ") + msg, "bon" if ok else "mauvais")
        if not ok:
            self.dialogue("Offre refusée", msg, icone="✖", couleur=ROUGE)
        self.maj()

    def augmenter(self, e):
        j = self.m.joueur
        nouveau = round(e.salaire * 1.1 / 50) * 50
        i, _ = self.dialogue(f"Augmenter {e.nom} ?", f"{euros(e.salaire)} → {euros(nouveau)} par mois, soit "
                             f"{euros((nouveau - e.salaire) * 12)} de plus par an. Son moral remonte nettement.",
                             ("Augmenter", "Annuler"), "€", VERT)
        if i == 0:
            self.ecrire("💶 " + j.augmenter(e), "bon")
            self.maj()

    # ------------------------------------------------------------ page : rachats et filiales
    def construire_rachats(self, p):
        self.page_rachats = p
        self.zone_rachats = tk.Frame(p, bg=FOND)
        self.zone_rachats.pack(fill="both", expand=True)

    def maj_rachats(self):
        if self.page != "rachats":
            return
        self.zone_rachats.destroy()
        z = self.zone_rachats = tk.Frame(self.page_rachats, bg=FOND)
        z.pack(fill="both", expand=True)
        m, j = self.m, self.m.joueur
        tk.Label(z, text="Grandissez aussi en rachetant d'autres sociétés : un fournisseur (achats moins chers, à l'abri "
                 "des pénuries), un sous-traitant (plus de capacité), une activité complémentaire (nouveaux revenus), "
                 "une start-up (technologie) ou un petit concurrent de niche (fusion). Pour un concurrent direct, "
                 "passez par la page Concurrence.", font=police(10), bg=FOND, fg=MUT, wraplength=1040,
                 justify="left").pack(anchor="w")
        corps = tk.Frame(z, bg=FOND)
        corps.pack(fill="both", expand=True, pady=(12, 0))
        corps.columnconfigure(0, weight=1, uniform="r")
        corps.columnconfigure(1, weight=1, uniform="r")
        corps.rowconfigure(0, weight=1)

        g = Carte(corps, "À vendre en ce moment", "De nouvelles occasions apparaissent au fil des mois. Si vous "
                  "tardez, un concurrent peut les racheter avant vous.")
        g.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        if not m.opportunites:
            texte_libre(g, "Aucune entreprise à vendre pour l'instant : revenez dans un mois ou deux.", largeur=460)
        for f in m.opportunites:
            k = tk.Frame(g, bg=PANNEAU2, padx=12, pady=8)
            k.pack(fill="x", pady=(0, 8))
            t = tk.Frame(k, bg=PANNEAU2)
            t.pack(fill="x")
            tk.Label(t, text=f.nom, font=police(11, True), bg=PANNEAU2, fg=TXT).pack(side="left")
            tk.Label(t, text=f.libelle_type, font=police(8, True), bg=PANNEAU, fg=ACC_SURVOL, padx=6).pack(side="right")
            tk.Label(k, text=f"{f.metier} · {f.salaries} salarié(s) · encore {f.dispo} mois en vente", font=police(9),
                     bg=PANNEAU2, fg=MUT).pack(anchor="w")
            tk.Label(k, text=f"CA ≈ {euros(f.ca)}/mois · marge {pct(f.marge)} · trésorerie {euros(f.tresorerie)} · "
                     f"dettes {euros(f.dette)}", font=police(9), bg=PANNEAU2, fg="#cfcfcf").pack(anchor="w")
            tk.Label(k, text=f.effet, font=police(9), bg=PANNEAU2, fg=VERT, wraplength=440, justify="left"
                     ).pack(anchor="w", pady=(2, 0))
            b = tk.Frame(k, bg=PANNEAU2)
            b.pack(fill="x", pady=(6, 0))
            tk.Label(b, text=f"Prix demandé : {euros(f.prix)}", font=police(10, True), bg=PANNEAU2, fg=TXT
                     ).pack(side="left")
            Bouton(b, "Faire une offre…", lambda f=f: self.offre_cible(f), "primaire", taille=9, padx=10, pady=3
                   ).pack(side="right")

        d = Carte(corps, "Vos filiales", "Leurs ventes et leurs charges s'ajoutent à vos comptes (comptes consolidés). "
                  "Développez-les pour qu'elles rapportent plus, ou revendez-les.")
        d.grid(row=0, column=1, sticky="nsew")
        if not j.filiales:
            texte_libre(d, "Aucune filiale pour l'instant.", largeur=460)
        else:
            ca = sum(f.ca for f in j.filiales)
            val = sum(f.valeur_entreprise(m.s.multiple) for f in j.filiales)
            texte_libre(d, f"{len(j.filiales)} filiale(s) · CA ≈ {euros(ca)}/mois · valeur ≈ {euros(val)}",
                        couleur=TXT, taille=10, largeur=460, pady=(0, 8))
        for f in j.filiales:
            k = tk.Frame(d, bg=PANNEAU2, padx=12, pady=8)
            k.pack(fill="x", pady=(0, 8))
            t = tk.Frame(k, bg=PANNEAU2)
            t.pack(fill="x")
            tk.Label(t, text=f.nom, font=police(11, True), bg=PANNEAU2, fg=TXT).pack(side="left")
            tk.Label(t, text="●" * f.niveau + "○" * (3 - f.niveau), font=police(11), bg=PANNEAU2, fg=VERT
                     ).pack(side="right")
            tk.Label(k, text=f"{f.metier} · {f.libelle_type.lower()} · rachetée en {f.acquise_le}", font=police(9),
                     bg=PANNEAU2, fg=MUT).pack(anchor="w")
            tk.Label(k, text=f"CA ≈ {euros(f.ca)}/mois · marge {pct(f.marge)} · résultat ≈ {euros(f.ca * f.marge, True)}"
                     f"/mois · valeur ≈ {euros(f.valeur_entreprise(m.s.multiple))}", font=police(9), bg=PANNEAU2,
                     fg="#cfcfcf").pack(anchor="w")
            tk.Label(k, text=f.effet, font=police(8), bg=PANNEAU2, fg=MUT, wraplength=440, justify="left"
                     ).pack(anchor="w", pady=(2, 0))
            b = tk.Frame(k, bg=PANNEAU2)
            b.pack(fill="x", pady=(6, 0))
            if f.niveau < 3:
                cout = j.cout_developpement(f)
                bt = Bouton(b, f"Développer ({euros(cout)})", lambda f=f: self.developper(f), "vert", taille=9,
                            padx=10, pady=3)
                bt.pack(side="left")
                bt.activer(j.tresorerie >= cout)
            Bouton(b, f"Vendre (≈ {euros(j.offre_cession(f))})", lambda f=f: self.vendre_filiale(f), "fantome",
                   taille=9, padx=10, pady=3).pack(side="right")

    def offre_cible(self, f):
        m, j = self.m, self.m.joueur
        moyens = max(0.0, j.tresorerie + j.placements + j.capacite_emprunt())
        mini = max(5_000, int(f.prix * 0.7) // 1000 * 1000)
        maxi = max(mini + 5_000, int(f.prix * 1.3) // 1000 * 1000)
        depart = min(maxi, max(mini, int(f.prix) // 1000 * 1000, 0))
        valeur = f.valeur(m.s.multiple)

        def info(offre):
            if offre > moyens:
                return f"⚠ Au-delà de vos moyens : {euros(moyens)} au maximum (trésorerie, placements, emprunt).", True
            ch = M.chance_acceptation(offre / f.prix)
            emprunt = max(0.0, offre - j.tresorerie - j.placements + 2_000)
            return ((f"Chance que les vendeurs acceptent : {ch:.0%}. ".replace("%", " %")
                     + (f"Financement : trésorerie, plus un emprunt d'environ {euros(emprunt)}. " if emprunt >= 1000
                        else "Financement : sur votre trésorerie. ")
                     + f"Valeur estimée : {euros(valeur)} ; votre offre : {pct(offre / max(valeur, 1) - 1, True)} "
                     "par rapport à cette valeur."), ch < 0.5)
        texte = (f"{f.metier} ({f.libelle_type.lower()}) · {f.salaries} salarié(s)\nCA ≈ {euros(f.ca)} par mois, marge "
                 f"{pct(f.marge)}. Trésorerie {euros(f.tresorerie)}, matériel {euros(f.immos)}, dettes "
                 f"{euros(f.dette)} (repris avec l'entreprise).\n{f.effet}\n\nPrix demandé : {euros(f.prix)}. En "
                 "dessous, les vendeurs peuvent refuser et durcir leur position ; au deuxième refus, ils se retirent.")
        i, offre = self.dialogue(f"Racheter {f.nom} ?", texte, ("Faire l'offre", "Annuler"), "⇄", ACC,
                                 (mini, maxi, pas_montant(maxi), depart), info, "Votre offre")
        if i != 0 or not offre:
            return
        ok, msg = m.offrir_cible(f, offre)
        self.ecrire(("🏢 " if ok else "✖ ") + msg, "bon" if ok else "mauvais")
        self.dialogue("Rachat conclu !" if ok else "Offre refusée", msg, icone="✔" if ok else "✖",
                      couleur=VERT if ok else ROUGE)
        self.maj()

    def developper(self, f):
        j = self.m.joueur
        cout = j.cout_developpement(f)
        i, _ = self.dialogue(f"Développer {f.nom} ?", f"Investir {euros(cout)} (matériel, recrutements, marketing), "
                             "amortis sur 5 ans : activité +25 % et marge améliorée. Niveau "
                             f"{f.niveau + 1}/3. Trésorerie après : {euros(j.tresorerie - cout)}.",
                             ("Investir", "Annuler"), "▲", VERT)
        if i == 0:
            self.ecrire("🏗 " + j.developper_filiale(f), "bon")
            self.maj()

    def vendre_filiale(self, f):
        j = self.m.joueur
        prix = j.offre_cession(f)
        i, _ = self.dialogue(f"Vendre {f.nom} ?", f"Un acheteur propose {euros(prix)} et reprend ses dettes. Vous "
                             f"perdez son activité (≈ {euros(f.ca)} de CA par mois) et ses effets : "
                             f"{f.effet[0].lower()}{f.effet[1:]}", ("Vendre", "Garder"), "⇄", AMBRE)
        if i == 0:
            self.ecrire("💰 " + j.vendre_filiale(f), "bon")
            self.maj()

    # ------------------------------------------------------------ page : finances
    def construire_fin(self, p):
        self.v_vue_fin = tk.StringVar(value="cr")
        haut = tk.Frame(p, bg=FOND)
        haut.pack(fill="x")
        self.seg_fin = Segments(haut, [("cr", "Compte de résultat"), ("bilan", "Bilan"), ("flux", "Flux de trésorerie"),
                                       ("ratios", "Ratios"), ("prev", "Prévisionnel")], self.v_vue_fin, self.maj_fin)
        self.seg_fin.pack(side="left")
        self.page_fin = p
        self.l_fin_info = tk.Label(haut, font=police(9), bg=FOND, fg=MUT, justify="right")
        self.l_fin_info.pack(side="right")
        self.zone_fin = tk.Frame(p, bg=FOND)
        self.zone_fin.pack(fill="both", expand=True, pady=(12, 0))

    def maj_fin(self):
        if self.page != "fin":
            return
        self.zone_fin.destroy()                   # cadre neuf : chaque vue a sa propre grille
        self.zone_fin = tk.Frame(self.page_fin, bg=FOND)
        self.zone_fin.pack(fill="both", expand=True, pady=(12, 0))
        self.seg_fin.peindre()
        j = self.m.joueur
        self.l_fin_info.config(text=f"Exercice comptable : janvier → décembre · données arrêtées fin "
                               f"{j.historique[-1]['date'] if j.mois_reels() else '—'}")
        getattr(self, "vue_" + self.v_vue_fin.get())(self.zone_fin)

    def vue_cr(self, z):
        j = self.m.joueur
        reels = j.mois_reels()
        c = Carte(z, "Compte de résultat", "Ce que l'entreprise a gagné ou perdu : les ventes, moins toutes les "
                  "charges, y compris celles qui ne sortent pas d'argent (amortissements) et l'impôt.")
        c.pack(fill="both", expand=True)
        h1 = reels[-1] if reels else None
        h2 = reels[-2] if len(reels) > 1 else None
        annee = self.m.date().split()[-1]
        prec = j.exercices[-1] if j.exercices else None
        v1 = valeurs_cr(h1["pl"]) if h1 else None
        v2 = valeurs_cr(h2["pl"]) if h2 else None
        vx = valeurs_cr(j.exercice)
        vp = valeurs_cr(prec["pl"]) if prec else None
        ca_x = j.exercice["ca"]
        lignes = []
        for cle, lib, style in LIGNES_CR:
            if cle == "operations":
                lib = j.s.libelle_ops
            part = f"{round(vx[cle] / ca_x * 100)} %".replace("-", "−") if ca_x and abs(vx[cle]) >= 0.5 else ""
            lignes.append((lib, [v1[cle] if v1 else "", v2[cle] if v2 else "", vx[cle], part,
                                 vp[cle] if vp else ""], style))
        entetes = ["", h1["date"].capitalize() if h1 else "Mois dernier", h2["date"].capitalize() if h2 else
                   "Mois précédent", f"Exercice {annee}\nà date", "% du CA",
                   f"Exercice {prec['annee']}" if prec else "Exercice précédent"]
        tableau(c, entetes, lignes).pack(fill="x")
        notes = [f"Impôt sur les sociétés : 15 % jusqu'à {euros(M.SEUIL_IS)} de bénéfice, 25 % au-delà, calculé à "
                 "la clôture (décembre), payé en mai. "
                 + {"recherche": "Crédit d'impôt recherche", "developpement": "Crédit d'impôt jeu vidéo"}.get(
                     j.s.base_credit, "Crédit d'impôt innovation")
                 + f" : {pct(j.s.credit_impot)} des dépenses éligibles ({euros(j.cii_annee)} acquis cette année)."]
        if j.deficit_reportable:
            notes.append(f"Déficits des années passées, qui réduiront vos futurs bénéfices imposables : "
                         f"{euros(j.deficit_reportable)}.")
        if h1 and h1.get("details"):
            notes.append("Éléments exceptionnels du dernier mois : " + " ; ".join(
                f"{lib} ({euros(mt, True)})" for lib, mt in h1["details"]) + ".")
        texte_libre(c, "  ".join(notes), largeur=1000, pady=(10, 0))

    def vue_bilan(self, z):
        j = self.m.joueur
        reels = j.mois_reels()
        b = j.bilan_comptable()
        ref = next((h for h in reversed(reels[:-1]) if h["date"].startswith("décembre")), reels[0] if reels else None)
        rb = ref["bilan"] if ref else None
        lib_ref = f"Fin {ref['date']}" if ref else ""
        z.columnconfigure(0, weight=1, uniform="b")
        z.columnconfigure(1, weight=1, uniform="b")
        z.rowconfigure(0, weight=1)

        def col(d, cle, part="actif"):
            return [b[part][cle], rb[part][cle] if rb else ""]
        ca = Carte(z, "Actif", "Ce que possède l'entreprise.")
        ca.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        a = b["actif"]
        lignes = [("Immobilisations nettes", col(a, "immos"), "")]
        if a["goodwill"] or (rb and rb["actif"]["goodwill"]):
            lignes.append(("Goodwill", col(a, "goodwill"), ""))
        for cle, lib in (("stocks", "Stocks de marchandises"), ("encours", "Travaux en cours (à facturer)")):
            if a[cle] or (rb and rb["actif"].get(cle)):
                lignes.append((lib, col(a, cle), ""))
        lignes += [("Créances clients", col(a, "creances"), ""),
                   ("Crédit d'impôt à recevoir", col(a, "etat"), ""),
                   ("Placements", col(a, "placements"), ""),
                   ("Banque", col(a, "disponibilites"), ""),
                   ("Total actif", [b["total_actif"], rb["total_actif"] if rb else ""], "grand")]
        tableau(ca, ["", "Aujourd'hui", lib_ref], lignes).pack(fill="x")
        if j.immos:
            tk.Label(ca, text="IMMOBILISATIONS", font=police(8, True), bg=PANNEAU, fg=MUT).pack(anchor="w",
                                                                                              pady=(14, 2))
            for im in sorted(j.immos, key=lambda i: -(i["brut"] - i["amorti"]))[:6]:
                texte_libre(ca, f"{im['libelle']} : {euros(im['brut'])} amortis à "
                            f"{im['amorti'] / im['brut'] * 100:.0f} % → {euros(im['brut'] - im['amorti'])}",
                            couleur="#cfcfcf", largeur=330)
            if len(j.immos) > 6:
                texte_libre(ca, f"… et {len(j.immos) - 6} autre(s).", largeur=440)

        cp = Carte(z, "Passif", "Qui la finance : actionnaires ou prêteurs.")
        cp.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        p = b["passif"]
        cpx = p["capital"] + p["reserves"] + p["resultat"]
        cpr = (rb["passif"]["capital"] + rb["passif"]["reserves"] + rb["passif"]["resultat"]) if rb else ""
        lignes = [("Capital", col(p, "capital", "passif"), ""),
                  ("Réserves", col(p, "reserves", "passif"), ""),
                  ("Résultat en cours", col(p, "resultat", "passif"), ""),
                  ("Capitaux propres", [cpx, cpr], "total"),
                  ("Emprunts", col(p, "emprunts", "passif"), ""),
                  ("Découvert", col(p, "decouvert", "passif"), ""),
                  ("Acomptes et avances reçus", col(p, "avances", "passif"), ""),
                  ("Fournisseurs", col(p, "fournisseurs", "passif"), ""),
                  ("Impôt à payer", col(p, "fiscal", "passif"), ""),
                  ("Total passif", [b["total_passif"], rb["total_passif"] if rb else ""], "grand")]
        tableau(cp, ["", "Aujourd'hui", lib_ref], lignes).pack(fill="x")
        ecart = b["total_actif"] - b["total_passif"]
        tk.Label(cp, text="✓ Bilan équilibré : actif = passif" if abs(ecart) < 1 else f"⚠ Écart : {euros(ecart)}",
                 font=police(10, True), bg=PANNEAU, fg=VERT if abs(ecart) < 1 else ROUGE).pack(anchor="w", pady=(10, 0))
        if b["hors_bilan"]:
            texte_libre(cp, f"Hors bilan : {euros(b['hors_bilan'])} de loyers de crédit-bail restant à payer.",
                        largeur=330, pady=(4, 0))
        # lecture financière : FR − BFR = trésorerie nette
        fr = cpx + p["emprunts"] - a["immos"] - a["goodwill"]
        bfr = (a["creances"] + a["etat"] + a["stocks"] + a["encours"] - p["fournisseurs"] - p["fiscal"]
               - p["avances"])
        tn = a["placements"] + a["disponibilites"] - p["decouvert"]
        tk.Label(cp, text="LECTURE DU BILAN", font=police(8, True), bg=PANNEAU, fg=MUT).pack(anchor="w", pady=(14, 2))
        tableau(cp, ["", ""], [("Fonds de roulement", [fr], ""),
                               ("− Besoin en fonds de roulement", [-bfr], ""),
                               ("= Trésorerie nette", [tn], "total")]).pack(fill="x")

        cg = Carte(z, "En un coup d'œil")
        cg.grid(row=0, column=2, sticky="nsew")
        z.columnconfigure(2, minsize=250)
        can = tk.Canvas(cg, width=230, bg=PANNEAU, highlightthickness=0)
        can.pack(fill="both", expand=True)
        can.bind("<Configure>", lambda _: graphe_bilan(can, j.bilan_comptable()))

    def vue_flux(self, z):
        j = self.m.joueur
        reels = j.mois_reels()
        h1 = reels[-1] if reels else None
        z.columnconfigure(0, weight=3)
        z.columnconfigure(1, weight=2)
        z.rowconfigure(0, weight=1)
        c = Carte(z, "Tableau des flux de trésorerie", "D'où vient l'argent et où il est parti (méthode directe).")
        c.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        tout = {k: sum(h["flux"][k] for h in reels) + j.periode["flux"][k] for k in M.FLUX}
        cols = [(h1["flux"], h1["tresorerie_debut"], h1["tresorerie"]) if h1 else None,
                (j.periode["flux"], j.periode["tresorerie_debut"], j.tresorerie),
                (tout, reels[0]["tresorerie_debut"] if reels else j.periode["tresorerie_debut"], j.tresorerie)]

        def ligne(lib, fn, style=""):
            return (lib, [fn(*x) if x else "" for x in cols], style)
        lignes = [ligne("Trésorerie en début de période", lambda f, d, e: d, "section")]
        groupes = [("Flux d'exploitation", M.FLUX_EXPLOITATION), ("Flux d'investissement", M.FLUX_INVESTISSEMENT),
                   ("Flux de financement", M.FLUX_FINANCEMENT)]
        libelles = dict(LIGNES_FLUX)
        for titre, cles in groupes:
            for k in cles:
                lignes.append(ligne(libelles[k], lambda f, d, e, k=k: f[k]))
            lignes.append(ligne(titre, lambda f, d, e, cles=cles: sum(f[k] for k in cles), "total"))
        lignes.append(ligne("Variation de trésorerie", lambda f, d, e: sum(f.values()), "grand"))
        lignes.append(ligne("Trésorerie en fin de période", lambda f, d, e: e, "total"))
        tableau(c, ["", h1["date"].capitalize() if h1 else "Mois dernier", "Mois en cours\n(à date)",
                    "Depuis la création"], lignes).pack(fill="x")

        d = Carte(z, "Le mois dernier en cascade")
        d.grid(row=0, column=1, sticky="nsew")
        can = tk.Canvas(d, height=250, bg=PANNEAU, highlightthickness=0)
        can.pack(fill="x")
        can.bind("<Configure>", lambda _: graphe_cascade(can, h1))
        if h1:
            f = h1["flux"]
            expl = sum(f[k] for k in M.FLUX_EXPLOITATION)
            tk.Label(d, text="RÉSULTAT ≠ TRÉSORERIE", font=police(8, True), bg=PANNEAU, fg=MUT).pack(anchor="w",
                                                                                                   pady=(10, 2))
            if not f["acquisitions"]:
                h2 = reels[-2] if len(reels) > 1 else None

                def bfr(b):
                    return (b["actif"]["creances"] + b["actif"]["etat"] + b["actif"]["stocks"] + b["actif"]["encours"]
                            - b["passif"]["fournisseurs"] - b["passif"]["fiscal"] - b["passif"]["avances"]) if b else 0.0
                dbfr = bfr(h1["bilan"]) - bfr(h2["bilan"] if h2 else None)
                tableau(d, ["", ""], [("Résultat net du mois", [h1["resultat"]], ""),
                                      ("+ Amortissements", [h1["pl"]["dotations"]], ""),
                                      ("− Hausse du BFR", [-dbfr], ""),
                                      ("= Flux d'exploitation", [expl], "total")]).pack(fill="x")
                texte_libre(d, "Le besoin en fonds de roulement augmente quand vos clients vous doivent plus "
                            "(ventes à crédit) ou que vous payez vos fournisseurs plus vite.", largeur=380,
                            pady=(6, 0))
            else:
                texte_libre(d, "Ce mois-ci, un rachat d'entreprise a modifié tout le bilan.", largeur=380)

    def vue_ratios(self, z):
        j = self.m.joueur
        reels = j.mois_reels()
        if not reels:
            texte_libre(z, "Les ratios apparaîtront après le premier mois.", fond=FOND, taille=11)
            return
        der = reels[-3:]
        n = len(der)
        pl = M.somme_pl([h["pl"] for h in der])
        sd = M.soldes(pl)
        ca = pl["ca"]
        b = j.bilan_comptable()
        cartes = []

        def ratio(v, fmt="pct"):
            if v is None:
                return "—"
            return (f"{v * 100:.0f} %" if fmt == "pct" else f"{v:.0f} j" if fmt == "j" else
                    f"× {v:.1f}" if fmt == "x" else f"{v:.1f} an(s)").replace(".", ",").replace("-", "−")
        div = lambda a, b_: a / b_ if b_ else None
        mb, me, mn = div(sd["marge_brute"], ca), div(sd["ebe"], ca), div(sd["net"], ca)
        cartes.append(("Marge brute", ratio(mb), "Ce qui reste des ventes une fois les achats payés.",
                       TXT if mb is None else VERT if mb > 0.5 else AMBRE if mb > 0.25 else ROUGE))
        cartes.append(("Marge d'EBE", ratio(me), "La rentabilité de l'activité, avant amortissements, intérêts et "
                       "impôt.", TXT if me is None else VERT if me > 0.12 else AMBRE if me > 0 else ROUGE))
        cartes.append(("Marge nette", ratio(mn), "Ce qu'il reste vraiment pour 100 € de ventes, tout compris.",
                       TXT if mn is None else VERT if mn > 0.05 else AMBRE if mn > 0 else ROUGE))
        # point mort : charges fixes / taux de marge sur coûts variables
        ops_var = j.s.modele in ("jeu", "distribution", "biotech")      # coûts d'exploitation variables ?
        fixes = (sum(pl[k] for k in ("salaires", "loyer", "marketing", "qualite", "credit_bail", "divers", "dotations",
                                      "charges_fin")) + (0.0 if ops_var else pl["operations"])
                 - pl["produits_fin"] - pl["subventions"]) / n
        tmcv = div(ca - pl["achats"] - pl["impayes"] - (pl["operations"] if ops_var else 0.0), ca)
        if tmcv and tmcv > 0:
            pm = fixes / tmcv
            ecart = ca / n - pm
            cartes.append(("Point mort", court(pm) + " /mois", ("Atteint : " if ecart >= 0 else "Il manque ")
                           + f"{court(abs(ecart))} de ventes par mois" + (" de marge de sécurité." if ecart >= 0 else
                                                                            " pour ne plus perdre d'argent."),
                           VERT if ecart >= 0 else ROUGE))
        else:
            cartes.append(("Point mort", "—", "Vous vendez à perte : impossible à atteindre.", ROUGE))
        ca_m = ca / n
        achats_m = pl["achats"] / n
        bfr = (b["actif"]["creances"] + b["actif"]["etat"] + b["actif"]["stocks"] + b["actif"]["encours"]
               - b["passif"]["fournisseurs"] - b["passif"]["fiscal"] - b["passif"]["avances"])
        jb = div(bfr * 30, ca_m)
        cartes.append(("Besoin en fonds de roulement", court(bfr), f"Soit {ratio(jb, 'j')} de chiffre d'affaires "
                       "immobilisés dans le cycle clients / fournisseurs." if jb is not None else
                       "L'argent immobilisé dans le cycle clients / fournisseurs.", VERT if bfr <= 0 else TXT))
        dso = div(b["actif"]["creances"] * 30, ca_m)
        dpo = div(b["passif"]["fournisseurs"] * 30, achats_m)
        cartes.append(("Délais de paiement", f"{ratio(dso, 'j')} / {ratio(dpo, 'j')}",
                       "Clients / fournisseurs : ce que vos clients mettent à vous payer, et vous à payer vos "
                       "fournisseurs.", TXT))
        brule = sum(sum(h["flux"][k] for k in M.FLUX_EXPLOITATION + M.FLUX_INVESTISSEMENT) for h in der) / n
        if brule < 0:
            aut = (j.tresorerie + j.placements + j.decouvert_autorise()) / -brule
            cartes.append(("Autonomie", f"{max(0.0, aut):.0f} mois", "Avant d'épuiser trésorerie, placements et "
                           f"découvert, au rythme actuel ({euros(brule)}/mois).", VERT if aut > 12 else AMBRE
                           if aut > 6 else ROUGE))
        else:
            cartes.append(("Autonomie", "Illimitée", f"Votre activité génère de la trésorerie : "
                           f"{euros(brule, True)} par mois en moyenne.", VERT))
        ebe_an = sd["ebe"] / n * 12
        dn = j.dette_nette
        cartes.append(("Dette nette / EBE", "Trésorerie nette" if dn <= 0 else ratio(dn / ebe_an, "an") if ebe_an > 0
                       else "EBE négatif", "Combien d'années d'EBE pour rembourser toutes les dettes. Les banques "
                       "s'inquiètent au-delà de 3 ans.", VERT if dn <= 0 or (ebe_an > 0 and dn / ebe_an < 2) else
                       AMBRE if ebe_an > 0 and dn / ebe_an < 4 else ROUGE))
        cpx = j.capitaux_propres
        cartes.append(("Endettement (gearing)", ratio(dn / cpx) if cpx > 0 else "Fonds propres négatifs",
                       "Dette nette rapportée aux capitaux propres.", ROUGE if cpx <= 0 else VERT if dn / cpx < 1
                       else AMBRE if dn / cpx < 2 else ROUGE))
        roe = sd["net"] / n * 12 / cpx if cpx > 0 else None
        cartes.append(("Rentabilité des capitaux propres", ratio(roe), "Résultat net annuel rapporté à l'argent "
                       "investi par les actionnaires (ROE).", TXT if roe is None else VERT if roe > 0.15 else AMBRE
                       if roe > 0 else ROUGE))
        couv = div(sd["ebe"], pl["charges_fin"])
        cartes.append(("Couverture des intérêts", ratio(couv, "x") if couv is not None else "Aucun intérêt",
                       "EBE / charges financières. En dessous de × 3, la banque s'inquiète.",
                       VERT if couv is None or couv > 5 else AMBRE if couv > 3 else ROUGE))
        cartes.append(("Capitaux propres", euros(cpx), f"Dont {euros(j.capital)} apportés par les actionnaires et "
                       f"{euros(cpx - j.capital, True)} de résultats accumulés.", VERT if cpx >= j.capital else AMBRE
                       if cpx > 0 else ROUGE))
        for i, (titre, val, expl, coul) in enumerate(cartes):
            c = tk.Frame(z, bg=PANNEAU, highlightthickness=1, highlightbackground=BORD, padx=14, pady=10)
            c.grid(row=i // 4, column=i % 4, sticky="nsew", padx=(0 if i % 4 == 0 else 10, 0),
                   pady=(0 if i < 4 else 10, 0))
            z.columnconfigure(i % 4, weight=1, uniform="r")
            tk.Label(c, text=titre.upper(), font=police(8, True), bg=PANNEAU, fg=MUT).pack(anchor="w")
            tk.Label(c, text=val, font=police(16, True), bg=PANNEAU, fg=coul).pack(anchor="w", pady=(2, 2))
            tk.Label(c, text=expl, font=police(9), bg=PANNEAU, fg="#bdbdbd", wraplength=220, justify="left"
                     ).pack(anchor="w")
        tk.Label(z, text=f"Calculés sur les {n} derniers mois. Couleurs : vert = sain, orange = à surveiller, "
                 "rouge = danger.", font=police(9), bg=FOND, fg=MUT).grid(row=3, column=0, columnspan=4, sticky="w",
                                                                          pady=(10, 0))

    def vue_prev(self, z):
        j, m = self.m.joueur, self.m
        proj = m.projeter(self.v_prix.get(), self.v_mkt.get(), self.v_qual.get())
        d_ = m.s.decisions
        choix = ((f"prix {prix_txt(self.v_prix.get(), m.s)}, " if d_.get("prix") else "")
                 + f"{d_['mkt'][0].lower()} {court(self.v_mkt.get())}, {d_['qual'][0].lower()} "
                 f"{court(self.v_qual.get())}")
        c = Carte(z, "Prévisionnel de trésorerie à 6 mois", f"Si vous gardez vos décisions actuelles ({choix}) "
                  f"sans embaucher, et sans coup du sort : un scénario, pas une promesse. "
                  "Les concurrents, la saison, les impôts et les remboursements sont pris en compte.")
        c.pack(fill="both", expand=True)
        can = tk.Canvas(c, height=250, bg=PANNEAU, highlightthickness=0)
        can.pack(fill="both", expand=True)
        dec = j.decouvert_autorise()
        can.bind("<Configure>", lambda _: graphe_prev(can, j.historique, proj, dec))
        if not proj:
            texte_libre(c, "La partie se termine : plus rien à prévoir.", pady=(8, 0))
            return
        lignes = [(x["date"].capitalize(), [x["ca"], x["ebe"], x["resultat"], x["tresorerie"], x["note"]], "")
                  for x in proj]
        tableau(c, ["", "Chiffre d'affaires", "EBE", "Résultat net", "Trésorerie fin de mois", "Note"],
                lignes).pack(fill="x", pady=(10, 0))
        neg = next((x for x in proj if x["tresorerie"] < 0), None)
        crise = next((x for x in proj if x["tresorerie"] < -x["decouvert"]), None)
        mini = min(proj, key=lambda x: x["tresorerie"])
        if crise:
            txt, coul = (f"🚨 En {crise['date']}, la trésorerie ({euros(crise['tresorerie'])}) dépasserait le découvert "
                         "autorisé : incident bancaire, prêt d'urgence ou faillite. Agissez maintenant : emprunt, "
                         "affacturage, baisse des dépenses, hausse des prix…"), ROUGE
        elif neg:
            txt, coul = (f"⚠ Votre compte passerait à découvert en {neg['date']} (point bas : {euros(mini['tresorerie'])} "
                         f"en {mini['date']}). Le découvert coûte 12 % par an et dégrade votre note."), AMBRE
        else:
            txt, coul = (f"✓ Pas de tension en vue : point bas de {euros(mini['tresorerie'])} en {mini['date']}."), VERT
        texte_libre(c, txt, couleur=coul, taille=10, largeur=1000, pady=(10, 0))

    # ------------------------------------------------------------ page : banque et capital
    def construire_banque(self, p):
        self.zone_banque = tk.Frame(p, bg=FOND)
        self.zone_banque.pack(fill="both", expand=True)

    def maj_banque(self):
        if self.page != "banque":
            return
        z = self.zone_banque
        for w in z.winfo_children():
            w.destroy()
        j = self.m.joueur
        for k in range(3):
            z.columnconfigure(k, weight=1, uniform="k")
        cols = [tk.Frame(z, bg=FOND) for _ in range(3)]
        for k, cf in enumerate(cols):
            cf.grid(row=0, column=k, sticky="nsew", padx=(0 if k == 0 else 12, 0))
        W = 300

        # --- la banque
        c = Carte(cols[0], "Votre banque")
        c.pack(fill="x")
        t = tk.Frame(c, bg=PANNEAU)
        t.pack(fill="x")
        tk.Label(t, text=j.note, font=police(30, True), bg=COULEURS_NOTE[j.note], fg="#0b0b0b", width=2
                 ).pack(side="left")
        d = tk.Frame(t, bg=PANNEAU, padx=12)
        d.pack(side="left", fill="x")
        tk.Label(d, text=f"Note de crédit : {M.NOTES_TXT[j.note].lower()}", font=police(11, True), bg=PANNEAU,
                 fg=TXT).pack(anchor="w")
        tk.Label(d, text="Revue chaque mois par votre banquier.", font=police(9), bg=PANNEAU, fg=MUT).pack(anchor="w")
        _, crit = j.analyse_credit()
        g = tk.Frame(c, bg=PANNEAU)
        g.pack(fill="x", pady=(10, 0))
        for i, (lib, val, ok) in enumerate(crit):
            tk.Label(g, text=("✓ " if ok else "✗ ") + lib, font=police(9), bg=PANNEAU, fg=VERT if ok else ROUGE
                     ).grid(row=i, column=0, sticky="w")
            tk.Label(g, text=val, font=police(9, True), bg=PANNEAU, fg=TXT).grid(row=i, column=1, sticky="e")
        g.columnconfigure(0, weight=1)
        tk.Frame(c, bg=BORD, height=1).pack(fill="x", pady=8)
        if j.note == "E":
            texte_libre(c, "Note E : plus aucun crédit ni découvert. Il faut redresser l'activité, ou lever des fonds.",
                        couleur=ROUGE, largeur=W)
        else:
            taux = " · ".join(f"{M.fmt_taux(j.taux_emprunt(a))} sur {a} ans" for a in M.DUREES_PRET)
            for lib, val in (("Taux de référence", M.fmt_taux(self.m.taux_ref)), ("Taux", taux), ("Capacité d'emprunt", euros(j.capacite_emprunt())),
                             ("Découvert autorisé", f"{euros(j.decouvert_autorise())} (agios 12 %/an)")):
                l = tk.Frame(c, bg=PANNEAU)
                l.pack(fill="x")
                tk.Label(l, text=lib, font=police(9), bg=PANNEAU, fg=MUT).pack(side="left")
                tk.Label(l, text=val, font=police(9, True), bg=PANNEAU, fg=TXT, wraplength=200, justify="right"
                         ).pack(side="right")
        b = Bouton(c, "Nouvel emprunt…", self.emprunter, "primaire")
        b.pack(fill="x", pady=(10, 0))
        b.activer(j.note != "E" and j.capacite_emprunt() >= 1000)

        c = Carte(cols[0], "Emprunts en cours")
        c.pack(fill="both", expand=True, pady=(12, 0))
        if not j.prets:
            texte_libre(c, "Aucun emprunt : l'entreprise ne doit rien à sa banque.", largeur=W)
        for pr in j.prets:
            l = tk.Frame(c, bg=PANNEAU2, padx=10, pady=6)
            l.pack(fill="x", pady=(0, 6))
            h = tk.Frame(l, bg=PANNEAU2)
            h.pack(fill="x")
            tk.Label(h, text=pr.libelle, font=police(10, True), bg=PANNEAU2, fg=TXT).pack(side="left")
            tk.Label(h, text=court(pr.capital_restant), font=police(10, True), bg=PANNEAU2, fg=TXT).pack(side="right")
            h = tk.Frame(l, bg=PANNEAU2)
            h.pack(fill="x")
            tk.Label(h, text=f"{M.fmt_taux(pr.taux)}{' variable' if pr.variable else ''} · {court(pr.mensualite)}/mois"
                     f" · encore {pr.mois_restants()} mois" + (f" ({pr.differe} de différé)" if pr.differe else ""),
                     font=police(8), bg=PANNEAU2, fg=MUT).pack(side="left")
            Bouton(h, "Solder", lambda pr=pr: self.solder(pr), "fantome", taille=8, padx=8, pady=1).pack(side="right")
        if j.prets:
            texte_libre(c, f"Total : {court(j.dette)} · mensualités {court(sum(p.mensualite for p in j.prets))}/mois",
                        couleur=TXT, largeur=W)

        # --- trésorerie et délais
        c = Carte(cols[1], "Trésorerie et placements")
        c.pack(fill="x")
        for lib, val, coul in (("Compte courant", euros(j.tresorerie), VERT if j.tresorerie >= 0 else ROUGE),
                               ("Placements (compte à terme 3 %)", euros(j.placements), TXT)):
            l = tk.Frame(c, bg=PANNEAU)
            l.pack(fill="x")
            tk.Label(l, text=lib, font=police(10), bg=PANNEAU, fg=MUT).pack(side="left")
            tk.Label(l, text=val, font=police(12, True), bg=PANNEAU, fg=coul).pack(side="right")
        texte_libre(c, "Placez la trésorerie qui dort : elle rapporte 3 % par an. En cas de découvert, la banque "
                    "débloque vos placements automatiquement.", largeur=W, pady=(6, 0))
        l = tk.Frame(c, bg=PANNEAU)
        l.pack(fill="x", pady=(10, 0))
        b = Bouton(l, "Placer…", self.placer, "secondaire")
        b.pack(side="left", fill="x", expand=True, padx=(0, 4))
        b.activer(j.tresorerie >= 1000)
        b = Bouton(l, "Récupérer…", self.retirer, "secondaire")
        b.pack(side="left", fill="x", expand=True, padx=(4, 0))
        b.activer(j.placements >= 100)

        c = Carte(cols[1], "Délais de paiement")
        c.pack(fill="both", expand=True, pady=(12, 0))
        part = j.s.b2b
        tk.Label(c, text="Vos clients professionnels", font=police(10, True), bg=PANNEAU, fg=TXT).pack(anchor="w")
        if part:
            self.v_delai_c = tk.IntVar(value=j.delai_clients)
            Segments(c, [(0, "Comptant"), (30, "30 jours"), (60, "60 jours")], self.v_delai_c,
                     self.changer_delais).pack(anchor="w", pady=(4, 2))
            att, imp = M.DELAIS_CLIENTS[j.delai_clients]
            texte_libre(c, f"Les pros font {pct(part)} de vos ventes. Leur laisser du temps vous rend plus attractif "
                        f"(+{(att - 1) * part * 100:.0f} % ici), mais l'argent arrive plus tard"
                        + (f" et {imp * 100:.1f} % des factures ne seront jamais payées.".replace(".", ",", 1)
                           if imp else "."), largeur=W)
        else:
            texte_libre(c, "Vos clients sont des particuliers : ils paient comptant.", largeur=W)
        tk.Label(c, text="Vos fournisseurs", font=police(10, True), bg=PANNEAU, fg=TXT).pack(anchor="w", pady=(10, 0))
        self.v_delai_f = tk.IntVar(value=j.delai_fournisseurs)
        Segments(c, [(0, "Comptant −2 %"), (30, "30 jours"), (60, "60 jours +1,5 %")], self.v_delai_f,
                 self.changer_delais).pack(anchor="w", pady=(4, 2))
        texte_libre(c, "Payer comptant vous vaut un escompte ; payer tard garde l'argent plus longtemps, mais le "
                    "fournisseur le facture.", largeur=W)
        tk.Frame(c, bg=BORD, height=1).pack(fill="x", pady=8)
        texte_libre(c, f"Factures clients à encaisser : {euros(j.total_creances)}\nFactures fournisseurs à payer : "
                    f"{euros(j.total_fournisseurs)}", couleur=TXT, largeur=W)
        b = Bouton(c, f"Affacturage : encaisser {euros(j.total_creances * (1 - M.FRAIS_AFFACTURAGE))} maintenant",
                   self.affacturer, "secondaire", taille=9)
        b.pack(fill="x", pady=(8, 0))
        b.activer(j.total_creances >= 100)

        # --- capital
        c = Carte(cols[2], "Capital et actionnaires")
        c.pack(fill="x")
        dm = j.dividende_max()
        for lib, val in (("Votre part du capital", pct(j.part_fondateur)), ("Capitaux propres", euros(j.capitaux_propres)),
                         ("Bénéfices distribuables", euros(max(0.0, j.reserves))),
                         ("Dividendes versés", euros(j.dividendes_verses)),
                         ("Votre patrimoine (dividendes nets)", euros(j.patrimoine))):
            l = tk.Frame(c, bg=PANNEAU)
            l.pack(fill="x")
            tk.Label(l, text=lib, font=police(10), bg=PANNEAU, fg=MUT).pack(side="left")
            tk.Label(l, text=val, font=police(10, True), bg=PANNEAU, fg=VERT if "patrimoine" in lib and j.patrimoine
                     else TXT).pack(side="right")
        texte_libre(c, "Un dividende fait sortir l'argent de l'entreprise (sa valeur baisse d'autant), mais il vous "
                    f"appartient pour de bon, même en cas de faillite. Flat tax de {M.FLAT_TAX:.0%}.", largeur=W,
                    pady=(6, 0))
        l = tk.Frame(c, bg=PANNEAU)
        l.pack(fill="x", pady=(10, 0))
        b = Bouton(l, "Verser un dividende…", self.dividende, "vert")
        b.pack(side="left", fill="x", expand=True, padx=(0, 4))
        b.activer(dm >= 1000)
        b = Bouton(l, "Lever des fonds…", self.lever, "secondaire")
        b.pack(side="left", fill="x", expand=True, padx=(4, 0))
        b.activer(j.conditions_levee() is not None)
        cl = j.conditions_levee()
        texte_libre(c, (f"Des investisseurs vous valorisent {euros(cl['valorisation'])} : vous pouvez lever entre "
                        f"{euros(cl['mini'])} et {euros(cl['maxi'])}.") if cl else
                    (j.lever() + f" ({j.levees}/{j.s.levees_max} levées faites)."), largeur=W, pady=(6, 0))

        c = Carte(cols[2], "Crédit-bail (hors bilan)")
        c.pack(fill="both", expand=True, pady=(12, 0))
        if not j.credits_bail:
            texte_libre(c, "Aucun contrat. Sur la page Investir, vous pouvez financer un investissement en "
                        "crédit-bail : rien à payer tout de suite, 36 loyers ensuite (15 % plus cher au total).",
                        largeur=W)
        for cb in j.credits_bail:
            l = tk.Frame(c, bg=PANNEAU2, padx=10, pady=6)
            l.pack(fill="x", pady=(0, 6))
            tk.Label(l, text=cb["libelle"], font=police(10, True), bg=PANNEAU2, fg=TXT).pack(anchor="w")
            tk.Label(l, text=f"{euros(cb['loyer'])}/mois · encore {cb['restant']} loyers sur {cb['total']}",
                     font=police(8), bg=PANNEAU2, fg=MUT).pack(anchor="w")
        if j.credits_bail:
            texte_libre(c, f"Engagement total restant : {euros(j.engagements_credit_bail)}", couleur=TXT, largeur=W)

    # ------------------------------------------------------------ page : journal
    def construire_journal(self, p):
        c = Carte(p, padx=6, pady=6)
        c.pack(fill="both", expand=True)
        self.journal = tk.Text(c, wrap="word", font=police(10), relief="flat", bg=PANNEAU, fg="#d4d4d4", padx=12,
                               pady=10, insertbackground=TXT, highlightthickness=0)
        sb = tk.Scrollbar(c, command=self.journal.yview, bg=PANNEAU2, troughcolor=PANNEAU, bd=0,
                          highlightthickness=0, activebackground=ACC)
        self.journal.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.journal.pack(fill="both", expand=True)
        for tag, coul in [("titre", ACC), ("bon", VERT), ("mauvais", ROUGE), ("event", AMBRE), ("mut", MUT),
                          ("marche", VIOLET)]:
            self.journal.tag_configure(tag, foreground=coul)
        self.journal.tag_configure("titre", font=police(10, True), spacing1=8)

    def ecrire(self, texte, tag=None):
        self.lignes_journal.append((texte, tag))
        self.journal.insert("end", texte + "\n", tag)
        self.journal.see("end")

    def flash(self, texte):
        self.flash_l.config(text=texte)

    # ------------------------------------------------------------ actions
    def recruter(self):
        self.ecrire(self.m.joueur.recruter(), "mut")
        self.maj()

    def licencier(self, e=None):
        j = self.m.joueur
        if not j.equipe:
            self.dialogue("Aucun salarié", "Vous travaillez seul pour l'instant.")
            return
        if e is None:
            e = (j.membres("equipier") or j.equipe)[-1]
        rh = [x for x in j.membres("rh") if x is not e]
        i, _ = self.dialogue(f"Licencier {e.nom} ?", f"{j.titre(e)} depuis {e.anciennete} mois. Indemnités : "
                             f"{euros(j.indemnite(e))}. Le moral de l'équipe va baisser."
                             + (f"\n\n⚠ {rh[0].nom}, votre RH, refuse les licenciements : il démissionnera." if rh
                                else ""), ("Licencier", "Annuler"), "⚠", ROUGE)
        if i == 0:
            self.ecrire(j.licencier(e), "mauvais")
            self.maj()

    def emprunter(self):
        j = self.m.joueur
        cap = j.capacite_emprunt()
        if j.note == "E" or cap < 1000:
            self.dialogue("La banque refuse", ("Votre note de crédit est E : plus aucun crédit tant que la situation "
                                               "ne s'est pas redressée." if j.note == "E" else
                                               "Vous êtes déjà trop endetté pour votre niveau d'activité. Augmentez "
                                               "votre chiffre d'affaires ou attendez d'avoir remboursé."),
                          icone="✖", couleur=ROUGE)
            return
        v_duree = tk.IntVar(value=5)

        def info(montant):
            taux = j.taux_emprunt(v_duree.get())
            p = M.nouveau_pret(montant, taux, v_duree.get() * 12)
            return (f"Taux {M.fmt_taux(taux)} · mensualité {euros(p.mensualite)} · coût total des intérêts "
                    f"{euros(p.mensualite * p.duree - montant)}", False)
        i, montant = self.dialogue("Emprunter", f"Note {j.note} : votre banque peut vous prêter jusqu'à {euros(cap)}. "
                                   "Plus la durée est longue, plus la mensualité est faible… et plus le crédit coûte "
                                   "cher.", ("Emprunter", "Annuler"), "€", ACC,
                                   (pas_montant(cap), int(cap), pas_montant(cap),
                                    min(int(cap), max(pas_montant(cap), int(cap) // 4))), info,
                                   segments=("Durée", [(2, "2 ans"), (5, "5 ans"), (7, "7 ans")], v_duree))
        if i == 0 and montant:
            self.ecrire("🏦 " + j.emprunter(montant, v_duree.get()), "bon")
            self.maj()

    def solder(self, pret):
        j = self.m.joueur
        pen = pret.penalite()
        total = pret.capital_restant + pen
        if total > j.tresorerie:
            self.dialogue("Trésorerie insuffisante", f"Il faut {euros(total)} pour solder ce prêt (capital restant "
                          f"{euros(pret.capital_restant)} + indemnité {euros(pen)}).", icone="✖", couleur=ROUGE)
            return
        i, _ = self.dialogue(f"Solder : {pret.libelle}", f"Capital restant {euros(pret.capital_restant)} + indemnité "
                             f"de remboursement anticipé {euros(pen)} = {euros(total)}.\nVous économisez environ "
                             f"{euros(pret.interets_restants() - pen)} d'intérêts (indemnité déduite) et "
                             f"{euros(pret.mensualite)} de mensualité. Trésorerie après : {euros(j.tresorerie - total)}.",
                             ("Solder le prêt", "Annuler"), "€", ACC)
        if i == 0:
            self.ecrire("🏦 " + j.rembourser(pret), "bon")
            self.maj()

    def placer(self):
        j = self.m.joueur
        maxi = int(j.tresorerie // 1000 * 1000)
        if maxi < 1000:
            return
        charges = j.charges_fixes()

        def info(v):
            return (f"Intérêts : environ {euros(v * M.TAUX_LIVRET / 12)} par mois. Trésorerie restante : "
                    f"{euros(j.tresorerie - v)}" + (" — moins de 2 mois de charges fixes !" if j.tresorerie - v <
                                                    2 * charges else "."), j.tresorerie - v < 2 * charges)
        i, v = self.dialogue("Placer de la trésorerie", "Un compte à terme rémunéré à 3 % par an, récupérable à tout "
                             "moment.", ("Placer", "Annuler"), "€", VIOLET,
                             (1000, maxi, 1000, max(1000, int((j.tresorerie - 2 * charges) // 1000 * 1000))), info)
        if i == 0 and v:
            self.ecrire("💶 " + j.placer(v), "bon")
            self.maj()

    def retirer(self):
        j = self.m.joueur
        maxi = int(j.placements // 100 * 100)
        if maxi < 100:
            return
        i, v = self.dialogue("Récupérer des placements", f"Vous avez {euros(j.placements)} placés.",
                             ("Récupérer", "Annuler"), "€", VIOLET, (100, maxi, 100, maxi))
        if i == 0 and v:
            self.ecrire("💶 " + j.retirer(v), "mut")
            self.maj()

    def affacturer(self):
        j = self.m.joueur
        tot = j.total_creances
        i, _ = self.dialogue("Affacturage", f"Une société d'affacturage rachète vos {euros(tot)} de factures clients "
                             f"en attente et vous verse tout de suite {euros(tot * (1 - M.FRAIS_AFFACTURAGE))} "
                             f"(commission de {M.FRAIS_AFFACTURAGE:.0%}). Les impayés éventuels deviennent son problème.",
                             ("Céder mes factures", "Annuler"), "€", ACC)
        if i == 0:
            self.ecrire("🏦 " + j.ceder_creances(), "bon")
            self.maj()

    def changer_delais(self):
        j = self.m.joueur
        avant = (j.delai_clients, j.delai_fournisseurs)
        j.regler_delais(self.v_delai_c.get() if j.s.b2b else None, self.v_delai_f.get())
        if (j.delai_clients, j.delai_fournisseurs) != avant:
            self.ecrire(f"📄 Délais de paiement : clients {j.delai_clients or 'comptant'}"
                        f"{' jours' if j.delai_clients else ''}, fournisseurs {j.delai_fournisseurs or 'comptant'}"
                        f"{' jours' if j.delai_fournisseurs else ''}.", "mut")
        self.maj()

    def dividende(self):
        j = self.m.joueur
        mx = int(j.dividende_max() // 500 * 500)
        if mx < 1000:
            self.dialogue("Rien à distribuer", "Il faut des bénéfices d'exercices clos (réserves positives) et de la "
                          "trésorerie.", icone="ℹ", couleur=MUT)
            return
        charges = j.charges_fixes()

        def info(v):
            brut = v * j.part_fondateur
            return (f"Vous toucherez {euros(brut * (1 - M.FLAT_TAX))} nets ({euros(brut)} bruts − flat tax "
                    f"{M.FLAT_TAX:.0%})" + (f", les autres actionnaires {euros(v - brut)}" if j.part_fondateur < 1
                                            else "") + f". Trésorerie après : {euros(j.tresorerie - v)}.",
                    j.tresorerie - v < 2 * charges)
        i, v = self.dialogue("Verser un dividende", f"Vous pouvez distribuer jusqu'à {euros(mx)} de bénéfices mis en "
                             "réserve. L'argent quitte l'entreprise — sa valeur baisse d'autant — mais il est à vous "
                             "pour de bon, même si l'entreprise fait faillite ensuite.", ("Verser", "Annuler"), "◆",
                             VERT, (500, mx, 500, max(500, mx // 2 // 500 * 500)), info, "Dividende total")
        if i == 0 and v:
            self.ecrire("💰 " + j.verser_dividende(v), "bon")
            self.maj()

    def lever(self):
        j = self.m.joueur
        c = j.conditions_levee()
        if not c:
            self.dialogue("Pas d'investisseur", j.lever(), icone="ℹ", couleur=MUT)
            return
        v = c["valorisation"]

        def info(montant):
            part = montant / (v + montant)
            return (f"Les investisseurs prendraient {pct(part)} du capital : vous garderiez "
                    f"{pct(j.part_fondateur * (1 - part))} d'une entreprise valorisée {euros(v + montant)}.",
                    j.part_fondateur * (1 - part) < 0.5)
        i, montant = self.dialogue("Levée de fonds", f"Des investisseurs sont prêts à investir, sur la base d'une "
                                   f"valorisation de {euros(v)} avant l'opération. À vous de choisir le montant : "
                                   "plus vous levez, plus vous êtes dilué. Cet argent n'est jamais remboursé.",
                                   ("Lever les fonds", "Annuler"), "◆", VIOLET,
                                   (c["mini"], c["maxi"], c["pas"],
                                    max(c["mini"], min(c["maxi"], round(v * 0.3 / c["pas"]) * c["pas"]))),
                                   info, "Montant levé")
        if i == 0 and montant:
            self.ecrire("💼 " + j.lever(montant), "bon")
            self.maj()

    def racheter(self, cible):
        m, j = self.m, self.m.joueur
        v = cible.valorisation()
        h = cible.historique[-1] if cible.historique else None
        moyens = max(0.0, j.tresorerie + j.placements + j.capacite_emprunt())
        texte = (f"Valeur estimée : {euros(v)}, dont trésorerie {euros(cible.tresorerie)} et dettes "
                 f"{euros(cible.dette)}. Capitaux propres (valeur comptable) : {euros(cible.capitaux_propres)} ; "
                 f"au-delà, le prix payé devient un écart d'acquisition (goodwill) à votre bilan. "
                 f"Note de crédit : {cible.note}.\n{cible.salaries} salarié(s) · {pct(h['part']) if h else '—'} du marché · "
                 f"notoriété {cible.notoriete:.0f}/100"
                 + (f" · investissements : {', '.join(cible.ameliorations_secteur()[c].nom.lower() for c in cible.ameliorations)}"
                    if cible.ameliorations else "")
                 + f"\n\n{m.attitude(cible)}\n\nEn cas d'accord, vous récupérez ses salariés, sa clientèle, sa "
                 "notoriété, ses investissements et sa trésorerie, et vous reprenez ses dettes. Un refus la fâche "
                 "pour 3 mois.")
        mini = max(5_000, int(v * 0.5) // 1000 * 1000)
        maxi = max(mini + 5_000, int(v * 2.2) // 1000 * 1000)
        depart = min(maxi, max(mini, int(v * 1.2) // 1000 * 1000), max(mini, int(moyens) // 1000 * 1000))

        def info(offre):
            if offre > moyens:
                return f"⚠ Au-delà de vos moyens : {euros(moyens)} au maximum (trésorerie, placements, emprunt).", True
            emprunt = max(0.0, offre - j.tresorerie - j.placements + 2_000)
            return ((f"Financement : trésorerie et placements, plus un emprunt d'environ {euros(emprunt)}."
                     if emprunt >= 1000 else "Financement : sur votre trésorerie et vos placements.") + f"  Prime : {pct(offre / max(v, 1) - 1, True)} "
                    "par rapport à la valeur estimée.", False)
        i, offre = self.dialogue(f"Racheter {cible.nom} ?", texte, ("Faire l'offre", "Annuler"), "⚑", cible.couleur,
                                 (mini, maxi, pas_montant(maxi), depart), info, "Votre offre")
        if i != 0 or not offre:
            return
        ok, msg = m.offrir_rachat(j, cible, offre)
        self.ecrire(("🤝 " if ok else "✖ ") + msg, "bon" if ok else "mauvais")
        self.dialogue("Offre acceptée !" if ok else "Offre refusée", msg, icone="✔" if ok else "✖",
                      couleur=VERT if ok else ROUGE)
        self.maj()

    def investir(self, cle):
        j = self.m.joueur
        a = j.ameliorations_secteur()[cle]
        cout = j.cout_amelioration(cle)
        loyer = j.loyer_credit_bail(cle)
        v_mode = tk.StringVar(value="comptant" if j.tresorerie >= cout or j.note == "E" else "credit_bail")

        def info(_):
            if v_mode.get() == "comptant":
                return (f"Payé {euros(cout)} aujourd'hui (trésorerie après : {euros(j.tresorerie - cout)}), puis amorti "
                        f"sur 5 ans : {euros(cout / M.DUREE_AMORT)} de charge par mois au compte de résultat, sans "
                        "sortie d'argent.", j.tresorerie < cout)
            return (f"Rien à payer aujourd'hui : {M.DUREE_CREDIT_BAIL} loyers de {euros(loyer)} (total "
                    f"{euros(loyer * M.DUREE_CREDIT_BAIL)}, soit +{M.MAJ_CREDIT_BAIL:.0%}). Le bien reste au loueur "
                    "jusqu'au dernier loyer : engagement hors bilan, mais la banque en tient compte.", j.note == "E")
        i, _ = self.dialogue(a.nom, f"{a.effet}.\nPrix : {euros(cout)}.",
                             ("Investir", "Annuler"), a.icone, VERT, info_montant=info,
                             segments=("Financement", [("comptant", "Comptant"), ("credit_bail", "Crédit-bail")], v_mode))
        if i != 0:
            return
        if v_mode.get() == "comptant" and j.tresorerie < cout:
            self.dialogue("Trésorerie insuffisante", "Choisissez le crédit-bail, ou empruntez d'abord.", icone="✖",
                          couleur=ROUGE)
            return
        msg = j.ameliorer(cle, v_mode.get())
        self.ecrire("🏗 " + msg, "mauvais" if "refuse" in msg else "bon")
        self.maj()

    def tour(self):
        m = self.m
        if not m or m.fin:
            return
        rang_avant = m.rang_joueur()
        lignes = m.jouer_mois(self.v_prix.get(), self.v_mkt.get(), self.v_qual.get())
        infos = []
        for ligne in lignes:
            if ligne.startswith("—"):
                tag = "titre"
            elif ligne[:1] in "⚠🚨💀🚪❌✖💔":
                tag = "mauvais"
                infos.append(ligne)
            elif ligne[:1] in "✅📦🔬💊🧾🏆":
                tag = "bon"
                infos.append(ligne)
            elif ligne[:1] in "📉📰🤝🆕ℹ🏗📣🏢🏷🏭⚡🎮📜":
                tag = "marche"
                infos.append(ligne)
            elif ligne[:1] in "🏦🔑":
                tag = "mauvais" if ("abaisse" in ligne or "découvert" in ligne) else "event"
                infos.append(ligne)
            elif "résultat net +" in ligne:
                tag = "bon"
            else:
                tag = None
            self.ecrire(ligne, tag)
        ev = m.tirer_evenement()
        rang = m.rang_joueur()
        if not m.fin and rang != rang_avant and len(m.entreprises) > 1:
            infos.insert(0, ("▲ Vous montez " if rang < rang_avant else "▼ Vous reculez ")
                         + f"à la {rang}{'re' if rang == 1 else 'e'} place.")
        self.flash("   ·   ".join(([lignes[1]] if len(lignes) > 1 else []) + infos))
        self.maj()
        if ev:
            self.ecrire(f"★ {ev['titre']} : {ev['texte']}", "event")
            if ev["choix"]:
                i, _ = self.dialogue(ev["titre"], ev["texte"], ev["choix"], "★", AMBRE)
                msg = m.resoudre(ev, i == 0)
                if msg:
                    self.ecrire("→ " + msg, "bon" if i == 0 else "mut")
            else:
                self.dialogue(ev["titre"], ev["texte"], icone="★", couleur=AMBRE)
            self.maj()
        if m.fin:
            self.b_suivant.activer(False)
            self.fin_de_partie()

    # ------------------------------------------------------------ affichage
    def maj_prix_info(self):
        if not self.l_prix_info:
            return
        m, s, j = self.m, self.m.s, self.m.joueur
        p = self.v_prix.get()
        act = j.act
        if isinstance(act, M.ActiviteLuxe):
            pma = act.pma()
            txt = f"Prix maximal accepté par la clientèle : {prix_txt(pma)} (vous : {pct(p / pma)})."
            alerte = p > pma
            if p < act.dernier_prix * 0.99:
                txt += "\n⚠ Baisser le prix abîme la marque : exclusivité et réputation chutent."
                alerte = True
            self.l_prix_info.config(text=txt, fg=ROUGE if alerte else MUT)
            return
        if isinstance(act, M.ActiviteJeu):
            pr = act.projet
            txt = (f"Prix de « {pr.nom} » à sa sortie. Habituel pour un jeu {pr.libelle} : "
                   f"{M.ENVERGURES[pr.envergure][2]} €." if pr else "Aucun jeu en développement.")
            self.l_prix_info.config(text=txt, fg=MUT)
            return
        cout = act.cout_module() if isinstance(act, M.ActiviteIndustrie) else j.cout_unitaire
        marge = (p - cout) / p if p else 0
        ref = 1 - s.cout_unitaire / s.prix_ref if s.prix_ref else 0.3
        txt = f"Marge par unité : {pct(marge)}"
        pm = m.prix_moyen_concurrents()
        if pm:
            e = p / pm - 1
            txt += f"  ·  concurrents : {prix_txt(pm)} en moyenne ("
            txt += (f"vous êtes {pct(abs(e))} plus cher)" if e > 0.005 else
                    f"vous êtes {pct(abs(e))} moins cher)" if e < -0.005 else "même prix)")
        self.l_prix_info.config(text=txt, fg=ROUGE if marge < ref * 0.5 else MUT)

    def conseils(self):
        m, j, s = self.m, self.m.joueur, self.m.s
        h = j.historique[-1] if j.historique else None
        c = []
        charges = j.charges_fixes() + self.v_mkt.get() + self.v_qual.get()
        if j.tresorerie < 0:
            c.append(f"Compte à découvert ({court(j.tresorerie)}) : chaque mois coûte des agios. Renflouez "
                     "(emprunt, levée de fonds, placements).")
        if j.mois_reels() and not m.fin:
            proj = m.projeter(self.v_prix.get(), self.v_mkt.get(), self.v_qual.get(), 3)
            neg = next((x for x in proj if x["tresorerie"] < 0), None)
            if neg and j.tresorerie >= 0:
                c.append(f"Prévisionnel : trésorerie négative en {neg['date']} si rien ne change (page Finances).")
        c += j.act.conseils()
        fache = next((e for e in j.equipe if e.profil != "equipier" and (e.alerte or e.moral < 35)), None)
        if fache:
            c.append(f"{fache.nom} ({j.titre_min(fache)}) est mécontent : voyez la page Équipe avant qu'il parte.")
        if j.note in "DE":
            c.append(f"Note de crédit {j.note} : la banque se méfie. Retrouvez un EBE positif, réduisez les dettes.")
        if 0 <= j.tresorerie < 2 * charges:
            c.append(f"Trésorerie tendue : moins de 2 mois de charges ({court(charges)}/mois).")
        if h and s.modele in ("saas", "distribution"):
            if h["utilisation"] > 1:
                c.append("Équipe débordée : vous perdez des clients. Recrutez (page Équipe).")
            elif j.salaries and h["utilisation"] < 0.5:
                c.append("Équipe sous-employée : trop de monde pour vos ventes.")
        if j.qualite < 35:
            c.append(f"{s.libelle_qualite} faible : augmentez le budget « {s.decisions['qual'][0].lower()} ».")
        if m.opportunites and j.tresorerie + j.capacite_emprunt() > min(f.prix for f in m.opportunites):
            f = min(m.opportunites, key=lambda f: f.prix)
            c.append(f"À vendre : {f.nom}, {f.metier.lower()}, pour {court(f.prix)} (page Rachats).")
        if j.tresorerie > 6 * charges + 20_000 * s.echelle and not j.placements:
            c.append("Beaucoup de trésorerie dort sur le compte : placez-la ou investissez (page Banque).")
        if j.dividende_max() > 20_000 * s.echelle and not j.dividendes_verses:
            c.append("Vos bénéfices en réserve permettent de vous verser un dividende (page Banque).")
        leader = m.classement()[0]
        if leader is not j and leader.actif and len(m.entreprises) > 1:
            c.append(f"Le leader est {leader.nom} ({leader.strategie.nom.lower()} : {leader.act.resume()}).")
        return c[:3] or ["Tout va bien : continuez comme ça !"]

    def maj(self):
        m, j, s = self.m, self.m.joueur, self.m.s
        hist = j.historique
        h = hist[-1] if hist else None
        p = hist[-2] if len(hist) >= 2 else None
        # en-tête et barre latérale
        self.l_date.config(text=m.date().capitalize())
        self.l_treso.config(text=court(j.tresorerie), fg=VERT if j.tresorerie >= 0 else ROUGE)
        self.l_note.config(text=f"Note {j.note}", bg=COULEURS_NOTE[j.note])
        nb = len(m.entreprises)
        rang = m.rang_joueur()
        self.l_rang.config(text=f"#{rang}" if nb > 1 else "Solo")
        self.l_rang2.config(text=f"au classement, sur {nb} entreprises" if nb > 1 else "aucun concurrent")
        self.l_mois.config(text=f"MOIS {min(m.mois + 1, m.duree)} / {m.duree}")
        self.c_temps.update_idletasks()
        lw = self.c_temps.winfo_width()
        self.c_temps.delete("all")
        self.c_temps.create_rectangle(0, 0, lw * m.mois / m.duree, 6, fill=ACC, outline="")

        # tuiles
        def delta(cle, fmt):
            if not (h and p):
                return "", MUT
            d = h[cle] - p[cle]
            return ("▲ " if d >= 0 else "▼ ") + fmt(abs(d)), VERT if d >= 0 else ROUGE
        t = self.tuiles
        dt, dc = delta("ca", court)
        t["ca"].maj(court(h["ca"]) if h else "—", TXT, dt, dc, [x["ca"] for x in hist])
        t["res"].maj(court(h["resultat"], True) if h else "—",
                     (VERT if h["resultat"] >= 0 else ROUGE) if h else TXT,
                     f"cumul {court(sum(x['resultat'] for x in hist), True)}" if h else "", MUT,
                     [x["resultat"] for x in hist], VERT)
        for cle, k, coul in zip(("k1", "k2"), j.act.kpis(), (AMBRE, VIOLET)):
            t[cle].maj(k["valeur"], COUL_K.get(k["couleur"], TXT), k["detail"], MUT, k["serie"], coul, titre=k["titre"])
        valo = j.valorisation()
        moic = (valo + j.dividendes_verses) / max(1.0, j.capital)
        t["valo"].maj(court(valo), TXT, f"MOIC × {moic:.1f}".replace(".", ","),
                      VERT if moic >= 1 else ROUGE, [x["valorisation"] for x in hist], ACC)
        # décisions
        self.l_equipe.config(text=f"vous + {j.salaries}")
        self.l_equipe_info.config(text=f"Masse salariale {euros(j.masse_salariale())}/mois · {len(j.vivier)} "
                                  f"candidat(s) ce mois-ci : " + ", ".join(j.titre_min(c) for c in j.vivier))
        self.maj_prix_info()
        self.l_conseil.config(text="CONSEILLER\n" + "\n".join("•  " + c for c in self.conseils()))
        # jauges
        for cle, val in [("notoriete", j.notoriete), ("qualite", j.qualite), ("satisfaction", j.satisfaction),
                         ("moral", j.moral)]:
            self.anneaux[cle].maj(min(val, 100), f"{val:.0f}", couleur_note(val))
        titre_j, vj, txt_j, inverse = j.act.jauge()
        self.anneaux["jauge"].titre = titre_j
        self.anneaux["jauge"].maj(min(vj, 100), txt_j, couleur_note(vj, inverse))
        graphe_finances(self.g_fin, hist)
        self.maj_conc()
        graphe_parts(self.g_parts, m.entreprises)
        self.maj_inv()
        self.maj_activite()
        self.maj_equipe()
        self.maj_rachats()
        self.maj_fin()
        self.maj_banque()
        dispo = any(j.peut_ameliorer(c) and j.tresorerie >= 2 * j.cout_amelioration(c)
                    for c in j.ameliorations_secteur())
        self.nav["activite"].config(text="◆   " + s.libelle_activite + self.badge_activite())
        self.nav["inv"].config(text="▲   Investir" + ("   ●" if dispo else ""))
        fache = any(e.alerte or e.moral < 35 for e in j.equipe if e.profil != "equipier")
        self.nav["equipe"].config(text="☺   Équipe" + ("   ●" if fache else ""))
        self.nav["rachats"].config(text="⇄   Rachats" + (f"   ● {len(m.opportunites)}" if m.opportunites else ""))
        self.sauvegarder(silencieux=True)

    # ------------------------------------------------------------ fin de partie
    def fin_de_partie(self):
        m = self.m
        b = m.bilan()
        if self.fichier and self.fichier.exists():
            try:
                self.fichier.unlink()
            except OSError:
                pass
        self.l_sauve.config(text="Partie terminée", fg=MUT)
        raison = {"faillite": "Votre entreprise a fait faillite.",
                  "rachat": f"Vous avez vendu votre entreprise à {m.acquereur or 'un repreneur'}.",
                  "terme": f"{M.DUREES_PARTIE.get(m.duree, f'{m.duree} mois').capitalize()} se sont écoulés : "
                           "l'heure du bilan."}[m.fin]
        d = self.fen_fin = tk.Toplevel(self.r, bg=PANNEAU)
        d.title("Bilan")
        d.transient(self.r)
        d.configure(highlightthickness=1, highlightbackground=BORD)
        ok = m.fin != "faillite" and b["moic"] >= 1
        tk.Frame(d, bg=VERT if ok else ROUGE, height=5).pack(fill="x")
        corps = tk.Frame(d, bg=PANNEAU, padx=30, pady=20)
        corps.pack(fill="both")
        tk.Label(corps, text=raison, font=police(11), bg=PANNEAU, fg=MUT).pack(anchor="w")
        tk.Label(corps, text=b["titre"], font=police(26, True), bg=PANNEAU, fg=VERT if ok else ROUGE).pack(anchor="w")
        if b["nb"] > 1:
            tk.Label(corps, text=f"Classement final : {b['rang']}{'re' if b['rang'] == 1 else 'e'} sur {b['nb']}",
                     font=police(13, True), bg=PANNEAU, fg=AMBRE).pack(anchor="w", pady=(2, 0))
        tk.Label(corps, text=b["commentaire"], font=police(11), bg=PANNEAU, fg="#d4d4d4", wraplength=560,
                 justify="left").pack(anchor="w", pady=(10, 12))
        stats = tk.Frame(corps, bg=PANNEAU)
        stats.pack(fill="x")
        for i, (lib, val) in enumerate([("Multiple (MOIC)", f"× {b['moic']:.1f}".replace(".", ",")),
                                        ("Valeur de l'entreprise", court(b["valeur"])),
                                        ("Capital investi", court(b["capital"])),
                                        ("Votre gain", court(b["gain"]))]):
            c = tk.Frame(stats, bg=PANNEAU2, padx=12, pady=8)
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            stats.columnconfigure(i, weight=1)
            tk.Label(c, text=lib.upper(), font=police(8, True), bg=PANNEAU2, fg=MUT).pack(anchor="w")
            tk.Label(c, text=val, font=police(14, True), bg=PANNEAU2, fg=TXT).pack(anchor="w")
        tk.Label(corps, text="Score : MOIC = (valeur finale + dividendes versés) ÷ argent investi par vous et vos "
                 "investisseurs. " f"Valeur de vos parts : {court(b['parts'])} ({pct(b['part'])} du capital) · "
                 f"dividendes nets {court(b['dividendes'])} · CA annuel {court(b['ca'])} · emplois créés : "
                 f"{b['salaries']} · impôt sur les sociétés payé : {euros(b['impots'])} · note de crédit finale : "
                 f"{b['note']}", font=police(9), bg=PANNEAU, fg=MUT, wraplength=560, justify="left"
                 ).pack(anchor="w", pady=(8, 0))
        if b["nb"] > 1:
            tk.Label(corps, text="Classement", font=police(11, True), bg=PANNEAU, fg=TXT).pack(anchor="w", pady=(16, 4))
            for i, e in enumerate(m.classement(), 1):
                l = tk.Frame(corps, bg=PANNEAU)
                l.pack(fill="x", pady=1)
                tk.Label(l, text=f"{i if e.actif else '—'}", font=police(10, True), bg=PANNEAU, fg=MUT, width=3
                         ).pack(side="left")
                tk.Label(l, text="●", font=police(10), bg=PANNEAU, fg=e.couleur if e.actif else DISCRET
                         ).pack(side="left")
                tk.Label(l, text=f" {'★ ' if e.joueur else ''}{e.nom}", font=police(10, e.joueur), bg=PANNEAU,
                         fg=TXT if e.actif else DISCRET).pack(side="left")
                tk.Label(l, text=court(e.valorisation()) if e.actif else e.fin_raison, font=police(10, True),
                         bg=PANNEAU, fg=TXT if e.actif else ROUGE).pack(side="right")
        l = tk.Frame(corps, bg=PANNEAU)
        l.pack(fill="x", pady=(20, 0))
        Bouton(l, "Rejouer", lambda: (d.destroy(), self.ecran_creation()), "primaire", taille=11).pack(side="left")
        Bouton(l, "🖼  Partager mon résultat", self.partager_partie, "vert", taille=11).pack(side="left", padx=8)
        d.protocol("WM_DELETE_WINDOW", lambda: (d.destroy(), self.ecran_creation()))
        Bouton(l, "Quitter", self.r.destroy, "secondaire", taille=11).pack(side="left", padx=8)
        d.update_idletasks()
        x = self.r.winfo_rootx() + (self.r.winfo_width() - d.winfo_reqwidth()) // 2
        y = self.r.winfo_rooty() + max(0, (self.r.winfo_height() - d.winfo_reqheight()) // 3)
        d.geometry(f"+{x}+{y}")
        d.grab_set()

    # ------------------------------------------------------------ carte à partager
    def partager_partie(self):
        """Fenêtre de partage : l'image de la carte (si Pillow est installé) et un résumé texte à coller."""
        m = self.m
        b = m.bilan()
        parent = getattr(self, "fen_fin", None)
        d = tk.Toplevel(self.r, bg=PANNEAU)
        d.title("Partager mon résultat")
        d.transient(self.r)
        d.configure(highlightthickness=1, highlightbackground=BORD)
        corps = tk.Frame(d, bg=PANNEAU, padx=22, pady=16)
        corps.pack(fill="both")

        def fermer():
            d.destroy()
            if parent is not None and parent.winfo_exists():
                parent.grab_set()
        d.protocol("WM_DELETE_WINDOW", fermer)
        haut = tk.Frame(corps, bg=PANNEAU)
        haut.pack(fill="x")
        gauche = tk.Frame(haut, bg=PANNEAU)
        gauche.pack(side="left", anchor="n")
        droite = tk.Frame(haut, bg=PANNEAU, padx=20)
        droite.pack(side="left", anchor="n", fill="y")
        etat = tk.Label(corps, font=police(9), bg=PANNEAU, fg=MUT, wraplength=720, justify="left", anchor="w")

        # --- l'image
        if PIL_DISPONIBLE:
            img = dessiner_carte(m, b)
            apercu = img.copy()
            apercu.thumbnail((380, 475))
            photo = ImageTk.PhotoImage(apercu)
            l_img = tk.Label(gauche, image=photo, bg=PANNEAU)
            l_img.image = photo            # garde une référence : sinon Tkinter l'efface aussitôt
            l_img.pack()
            Bouton(gauche, "Enregistrer l'image (PNG)…", lambda: self.enregistrer_carte(img, etat), "primaire"
                   ).pack(fill="x", pady=(10, 0))
        else:
            c = tk.Frame(gauche, bg=PANNEAU2, padx=16, pady=14, width=380)
            c.pack(fill="both")
            tk.Label(c, text="🖼  Image de la carte", font=police(12, True), bg=PANNEAU2, fg=TXT).pack(anchor="w")
            tk.Label(c, text="Pour créer l'image à poster, le jeu a besoin de la bibliothèque gratuite Pillow. Il "
                     "peut l'installer tout seul (une minute, connexion Internet nécessaire).", font=police(10),
                     bg=PANNEAU2, fg="#d4d4d4", wraplength=340, justify="left").pack(anchor="w", pady=(6, 10))
            Bouton(c, "Installer Pillow maintenant", lambda: self.installer_pil(d, etat, fermer), "primaire"
                   ).pack(fill="x")
            tk.Label(c, text="Ou, dans PowerShell :  python -m pip install pillow", font=police(9), bg=PANNEAU2,
                     fg=MUT).pack(anchor="w", pady=(8, 0))

        # --- le résumé texte
        tk.Label(droite, text="Résumé à coller", font=police(12, True), bg=PANNEAU, fg=TXT).pack(anchor="w")
        tk.Label(droite, text="Pour un message, un post ou un groupe : collez-le tel quel.", font=police(9),
                 bg=PANNEAU, fg=MUT).pack(anchor="w", pady=(2, 8))
        texte = resume_partage(m, b)
        zone = tk.Text(droite, width=46, height=7, wrap="word", font=police(10), bg=PANNEAU2, fg=TXT, relief="flat",
                       padx=10, pady=8, highlightthickness=0)
        zone.insert("1.0", texte)
        zone.configure(state="disabled")
        zone.pack(anchor="w")
        Bouton(droite, "Copier le résumé", lambda: self.copier_resume(texte, etat), "secondaire").pack(
            anchor="w", pady=(10, 0))
        etat.pack(fill="x", pady=(12, 0))
        Bouton(corps, "Fermer", fermer, "fantome").pack(anchor="e", pady=(8, 0))
        d.update_idletasks()
        x = self.r.winfo_rootx() + (self.r.winfo_width() - d.winfo_reqwidth()) // 2
        y = self.r.winfo_rooty() + max(0, (self.r.winfo_height() - d.winfo_reqheight()) // 3)
        d.geometry(f"+{x}+{y}")
        d.grab_set()

    def copier_resume(self, texte, etat):
        self.r.clipboard_clear()
        self.r.clipboard_append(texte)
        etat.config(text="✓ Résumé copié : collez-le (Ctrl+V) dans votre message ou votre post.", fg=VERT)

    def installer_pil(self, fenetre, etat, fermer):
        """Installe Pillow avec pip, sans bloquer la fenêtre, puis rouvre la fenêtre de partage."""
        import subprocess
        import sys
        import threading
        etat.config(text="Installation de Pillow en cours… (jusqu'à une minute)", fg=AMBRE)
        res = {}

        def travail():
            options = {"capture_output": True, "text": True,
                       "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
            base = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--timeout", "20",
                    "pillow"]
            options["timeout"] = 240
            try:
                r = subprocess.run(base, **options)
                if r.returncode != 0:                        # droits insuffisants : installation pour l'utilisateur
                    r = subprocess.run(base + ["--user"], **options)
                res["ok"], res["msg"] = r.returncode == 0, (r.stderr or r.stdout or "")[-300:]
            except Exception as e:                           # pip absent, pas de réseau…
                res["ok"], res["msg"] = False, str(e)

        def attendre():
            if "ok" not in res:
                fenetre.after(300, attendre)
                return
            if res["ok"] and charger_pil():
                fermer()
                self.partager_partie()
            else:
                etat.config(text="Installation impossible. Ouvrez PowerShell et tapez :  python -m pip install pillow  "
                            f"puis relancez le jeu.\n({res['msg'].strip()})", fg=ROUGE)
        threading.Thread(target=travail, daemon=True).start()
        fenetre.after(300, attendre)

    def enregistrer_carte(self, img, etat=None):
        base = unicodedata.normalize("NFKD", self.m.joueur.nom).encode("ascii", "ignore").decode().lower()
        base = re.sub(r"[^a-z0-9]+", "_", base).strip("_") or "ma_boite"
        moic_txt = f"{self.m.bilan()['moic']:.1f}".replace(".", "_")
        nom_defaut = f"{base}_{self.m.s.cle}_x{moic_txt}.png"
        chemin = filedialog.asksaveasfilename(title="Enregistrer la carte", initialfile=nom_defaut,
                                              defaultextension=".png", filetypes=[("Image PNG", "*.png")])
        if not chemin:
            return
        try:
            img.save(chemin)
        except OSError as e:
            self.dialogue("Enregistrement impossible", str(e), icone="✖", couleur=ROUGE)
            return
        msg = f"✓ Carte enregistrée : {chemin}"
        if etat is not None:
            etat.config(text=msg, fg=VERT)
        self.flash(msg)


if __name__ == "__main__":
    racine = tk.Tk()
    Application(racine)
    racine.mainloop()
