"""
moteur.py — logique du jeu « Ma Boîte » (simulation de création d'entreprise, face à des concurrents).

Huit secteurs aux mécaniques très différentes : industrie lourde, logiciel SaaS, biotech, jeu vidéo, luxe,
aéronautique, grande distribution, énergie. Chaque entreprise a une « activité » (classe Activite…) qui porte
les règles propres à son secteur ; la comptabilité, la banque, l'équipe et les rachats sont communs.
Aucune interface ici : l'interface graphique est dans ma_boite.py.
"""
from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass, field

MOIS_NOMS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
             "septembre", "octobre", "novembre", "décembre"]
DUREE = 36                     # durée par défaut d'une partie (mois)
DUREES_PARTIE = {36: "3 ans", 60: "5 ans", 96: "8 ans"}
APPORT = 100_000               # la mise personnelle du fondateur
SALAIRE_CHARGE = 3_600         # salaire de référence des profils (ajusté ensuite au secteur)
TAUX_PRET = 0.05               # taux du prêt de départ (hors secteurs particuliers)
DUREE_PRET = 60                # mois
TAUX_REF_INITIAL = 0.03        # taux interbancaire (type Euribor) au début de la partie

# ---------------------------------------------------------------- finance et comptabilité
DUREE_AMORT = 60               # les investissements s'amortissent sur 5 ans (sauf usines, centrales…)
TAUX_LIVRET = 0.03             # rémunération des placements (compte à terme)
TAUX_DECOUVERT = 0.12          # agios annuels sur le découvert
FLAT_TAX = 0.30                # prélèvement forfaitaire unique sur les dividendes
FRAIS_AFFACTURAGE = 0.03       # commission de l'affactureur
MAJ_CREDIT_BAIL = 0.15         # le crédit-bail coûte 15 % de plus qu'un achat comptant…
DUREE_CREDIT_BAIL = 36         # … étalé sur 36 loyers
MOIS_SOLDE_IS = 4              # l'impôt d'un exercice est payé en mai de l'année suivante
SEUIL_IS = 42_500              # bénéfice taxé à 15 % jusqu'à ce seuil, 25 % au-delà
# note de crédit : (taux d'emprunt quand le taux de référence est à 3 %, facteur de capacité d'emprunt,
# découvert autorisé en mois de charges fixes)
NOTES = {"A": (0.040, 1.3, 1.0), "B": (0.050, 1.0, 0.75), "C": (0.065, 0.8, 0.5),
         "D": (0.085, 0.5, 0.25), "E": (None, 0.0, 0.0)}
NOTES_TXT = {"A": "Excellente", "B": "Bonne", "C": "Moyenne", "D": "Fragile", "E": "Critique"}
DUREES_PRET = {2: -0.005, 5: 0.0, 7: 0.005}            # durée en années → ajustement du taux
DELAIS_CLIENTS = {0: (1.00, 0.000), 30: (1.05, 0.010), 60: (1.10, 0.025)}   # (attrait auprès des pros, impayés)
DELAIS_FOURN = {0: 0.98, 30: 1.00, 60: 1.015}          # comptant : 2 % d'escompte ; 60 jours : 1,5 % plus cher
POSTES_PRODUITS = ("ca", "subventions", "produits_fin", "exceptionnel")
POSTES_CHARGES = ("achats", "salaires", "loyer", "operations", "marketing", "qualite", "credit_bail", "divers",
                  "impayes", "dotations", "charges_fin", "impot")
CHARGES_EXPLOITATION = ("salaires", "loyer", "operations", "marketing", "qualite", "credit_bail", "divers", "impayes")
FLUX_EXPLOITATION = ("clients", "fournisseurs", "salaires", "charges", "impots", "financier", "exceptionnel",
                     "subventions")
FLUX_INVESTISSEMENT = ("investissements", "acquisitions", "placements")
FLUX_FINANCEMENT = ("emprunts", "remboursements", "levees", "dividendes")
FLUX = FLUX_EXPLOITATION + FLUX_INVESTISSEMENT + FLUX_FINANCEMENT


def pl_vide() -> dict:
    return {k: 0.0 for k in POSTES_PRODUITS + POSTES_CHARGES}


def flux_vide() -> dict:
    return {k: 0.0 for k in FLUX}


def soldes(pl: dict) -> dict:
    """Soldes intermédiaires de gestion d'un compte de résultat."""
    mb = pl["ca"] - pl["achats"]
    ebe = mb + pl["subventions"] - sum(pl[k] for k in CHARGES_EXPLOITATION)
    rex = ebe - pl["dotations"]
    rcai = rex + pl["produits_fin"] - pl["charges_fin"]
    rai = rcai + pl["exceptionnel"]
    return {"ca": pl["ca"], "marge_brute": mb, "ebe": ebe, "rex": rex, "rcai": rcai, "rai": rai,
            "net": rai - pl["impot"]}


def somme_pl(liste: list[dict]) -> dict:
    tot = pl_vide()
    for pl in liste:
        for k, v in pl.items():
            tot[k] = tot.get(k, 0.0) + v
    return tot


def annuite(capital: float, taux: float, mois: int) -> float:
    r = taux / 12
    mois = max(1, mois)
    return capital / mois if r == 0 else capital * r / (1 - (1 + r) ** -mois)


# =============================================================================
# les secteurs
@dataclass
class Secteur:
    cle: str
    nom: str
    icone: str
    modele: str                # mécanique : industrie, saas, biotech, jeu, luxe, aero, distribution, energie
    tag: str                   # modèle économique en quelques mots
    description: str
    metrique: str              # la métrique clé du secteur
    gameplay: str
    unite: str                 # ce que l'on vend
    prix_ref: float            # prix de référence (0 : pas de prix de vente à fixer chaque mois)
    cout_unitaire: float       # coût variable par unité vendue
    noms: tuple                # noms des concurrents
    marche: float = 0.0        # demande potentielle par mois (secteurs où la clientèle est partagée)
    part_max: float = 0.5
    elasticite: float = 1.0
    extension: float = 0.8     # le marché total grandit-il quand les acteurs se multiplient ?
    saturation: float = 0.6
    capacite: float = 0.0      # unités par personne et par mois (quand la capacité vient de l'équipe)
    loyer: float = 0.0
    installation: float = 0.0  # investissement de départ
    libelle_installation: str = "Installation de départ"
    duree_installation: int = 60
    multiple: float = 1.0      # valorisation ≈ multiple × chiffre d'affaires annuel
    bonus_croissance: float = 0.5
    saison: list = field(default_factory=lambda: [1.0] * 12)
    recurrent: bool = False    # abonnements : les clients restent d'un mois sur l'autre
    churn: float = 0.0
    salaire: float = 3_600     # coût mensuel chargé d'un salarié type
    salaire_dirigeant: float = 2_000
    frais_generaux: float = 400
    equipe_initiale: int = 0
    investisseurs: float = 0.0          # fonds apportés par des investisseurs au départ
    part_investisseurs: float = 0.0     # part du capital qu'ils reçoivent
    pret_conseille: float = 0.0
    pret_max: float = 0.0
    pas_pret: float = 10_000
    duree_pret_initial: int = 60
    taux_pret_initial: float = TAUX_PRET
    differe_initial: int = 0
    pret_variable: bool = False
    libelle_pret: str = "Prêt de création"
    subvention_initiale: float = 0.0
    libelle_subvention: str = "Subvention"
    b2b: float = 0.0           # part des ventes faites à des professionnels (paiement à terme)
    delai_clients: int = 0
    delai_fournisseurs: int = 30
    bancabilite: float = 1.0   # appétit des banques pour ce secteur
    credit_impot: float = 0.2  # crédit d'impôt (innovation, recherche, jeu vidéo)
    base_credit: str = "qualite"
    levees_max: int = 3
    echelle: float = 1.0       # taille relative (montants des événements, budgets)
    notoriete_initiale: float = 8.0
    qualite_initiale: float = 45.0
    noto_gain: float = 4.0     # efficacité du marketing sur la notoriété
    noto_echelle: float = 1_000
    noto_declin: float = 0.08
    qual_echelle: float = 1_000
    confinement: float = 1.0   # effet d'un confinement sur la demande
    cout_fixe_ops: float = 0.0            # coûts fixes d'exploitation propres au secteur (par mois)
    libelle_ops: str = "Coûts d'exploitation"
    libelle_ca: str = "Chiffre d'affaires"
    ca_cible: float = 50_000              # taille (CA mensuel) des sociétés à racheter
    decisions: dict = field(default_factory=dict)   # {"prix"|"mkt"|"qual": (libellé, min, max, pas) ou None}
    titre_star: str = "CTO star"
    libelle_notoriete: str = "Notoriété"
    libelle_qualite: str = "Qualité"
    libelle_activite: str = "Activité"
    exclus: tuple = ()                    # événements qui n'ont pas de sens dans ce secteur
    marge_commande: float = 0.35


SECTEURS = {
    "industrie": Secteur(
        "industrie", "Industrie lourde / Automobile", "🏭", "industrie", "Usines · gros volumes · marges faibles",
        "Vous fabriquez des modules (batteries, trains avant, sièges…) pour les constructeurs automobiles. "
        "Une usine hors de prix, des marges fines sur de très gros volumes.",
        "Taux d'utilisation des usines",
        "Emprunt bancaire colossal au départ. Tout se joue sur les économies d'échelle : si la demande baisse "
        "de 15 %, les coûts fixes de l'usine écrasent la trésorerie.",
        "modules", 2_000, 1_650,
        ("Forgeval", "Métallia Auto", "Batterix", "Axiom Mobility", "Groupe Castelnau", "Ferromec"),
        marche=7_800, part_max=0.9, elasticite=3.0, extension=0.1, saturation=0.9,
        loyer=15_000, installation=9_000_000, libelle_installation="Usine n°1", duree_installation=120,
        multiple=0.6, saison=[1.0, 1.0, 1.05, 1.0, 1.0, 1.0, 0.9, 0.55, 1.0, 1.05, 1.0, 0.85],
        salaire=5_000, salaire_dirigeant=9_000, frais_generaux=25_000, equipe_initiale=4,
        investisseurs=3_400_000, part_investisseurs=0.60, pret_conseille=6_500_000, pret_max=8_000_000,
        pas_pret=250_000, duree_pret_initial=96, differe_initial=6, libelle_pret="Prêt bancaire industriel",
        b2b=1.0, delai_clients=30, delai_fournisseurs=30, bancabilite=1.0, credit_impot=0.2, levees_max=2,
        echelle=30, notoriete_initiale=30, qualite_initiale=50, noto_gain=2.0, noto_echelle=10_000,
        noto_declin=0.03, qual_echelle=10_000, confinement=0.4, cout_fixe_ops=200_000,
        libelle_ops="Coûts fixes des usines", ca_cible=400_000, marge_commande=0.15,
        decisions={"prix": ("Prix par module", 1_400, 2_800, 10),
                   "mkt": ("Prospection commerciale", 0, 200_000, 5_000),
                   "qual": ("R&D et qualité process", 0, 200_000, 5_000)},
        titre_star="Directeur d'usine star", libelle_notoriete="Réputation", libelle_activite="Usines",
        exclus=("buzz", "ch_influenceur")),
    "saas": Secteur(
        "saas", "Logiciel SaaS B2B", "💻", "saas", "Abonnements · marge brute 80 %",
        "Un logiciel en ligne vendu par abonnement aux entreprises. Chaque client paie tous les mois ; "
        "l'hébergement coûte peu.",
        "Taux d'attrition (churn) et valeur vie client (LTV)",
        "Croissance lente au début (R&D et prospection). Une fois la base de clients installée, la trésorerie "
        "devient prévisible et la valorisation explose lors des levées de fonds.",
        "clients", 450, 90,
        ("Gestio", "Planify", "Factura", "Pilotéo", "Kalkul", "Syncrone"),
        marche=180, part_max=0.5, elasticite=1.3, extension=0.5, saturation=0.6, capacite=60,
        loyer=6_000, installation=250_000, libelle_installation="Logiciel (première version)",
        duree_installation=36, multiple=2.4, bonus_croissance=0.6, recurrent=True, churn=0.03,
        salaire=5_500, salaire_dirigeant=6_000, frais_generaux=6_000, equipe_initiale=3,
        investisseurs=1_400_000, part_investisseurs=0.25, pret_conseille=300_000, pret_max=800_000,
        pas_pret=50_000, libelle_pret="Prêt d'amorçage Bpifrance", subvention_initiale=90_000,
        libelle_subvention="Bourse French Tech", b2b=1.0, delai_clients=30, bancabilite=0.7,
        credit_impot=0.3, levees_max=4, echelle=5, notoriete_initiale=10, qualite_initiale=50, noto_gain=3.0,
        noto_echelle=5_000, noto_declin=0.06, qual_echelle=5_000, confinement=1.1,
        cout_fixe_ops=0, libelle_ops="Infrastructure", ca_cible=60_000, marge_commande=0.6,
        decisions={"prix": ("Prix par client et par mois", 100, 1_500, 10),
                   "mkt": ("Marketing et prospection", 0, 150_000, 2_500),
                   "qual": ("R&D produit", 0, 150_000, 2_500)},
        titre_star="CTO star", libelle_qualite="Qualité du produit", libelle_activite="Produit et abonnés",
        exclus=("ch_greve",)),
    "biotech": Secteur(
        "biotech", "Biotech / Pharma", "🧬", "biotech", "Zéro CA pendant des années · pari binaire",
        "Vous développez des médicaments. Pas de chiffre d'affaires pendant des années : tout part en recherche "
        "et en essais cliniques, financés par les fonds de capital-risque et les subventions.",
        "Phase de validation clinique (1, 2, 3) et portefeuille de brevets",
        "Survie assurée par les subventions et les fonds VC. Risque binaire : si l'essai réussit, la valorisation "
        "est multipliée ; s'il échoue et que vous n'avez rien d'autre en clinique, c'est la faillite immédiate.",
        "traitements", 0, 0,
        ("Genoptys", "Immunova", "CellAxis", "Neurolys", "BioStral", "Thérapix"),
        loyer=20_000, installation=1_500_000, libelle_installation="Laboratoire", duree_installation=60,
        multiple=4.0, salaire=6_500, salaire_dirigeant=9_000, frais_generaux=20_000, equipe_initiale=5,
        investisseurs=5_900_000, part_investisseurs=0.50, pret_conseille=1_000_000, pret_max=1_500_000,
        pas_pret=100_000, taux_pret_initial=0.0, differe_initial=24, duree_pret_initial=60,
        libelle_pret="Avance remboursable Bpifrance", subvention_initiale=1_000_000,
        libelle_subvention="Subvention européenne (EIC)", b2b=1.0, delai_clients=60, bancabilite=0.2,
        credit_impot=0.3, base_credit="recherche", levees_max=5, echelle=20, notoriete_initiale=15,
        qualite_initiale=55, noto_gain=1.5, noto_echelle=10_000, noto_declin=0.03, qual_echelle=20_000,
        confinement=1.0, libelle_ops="Essais cliniques", libelle_ca="Licences et ventes", ca_cible=50_000,
        decisions={"prix": None, "mkt": ("Communication et partenariats", 0, 150_000, 5_000),
                   "qual": ("Recherche (nouvelles molécules)", 0, 400_000, 10_000)},
        titre_star="Directeur scientifique star", libelle_notoriete="Crédibilité",
        libelle_qualite="Qualité scientifique", libelle_activite="Pipeline clinique",
        exclus=("commande", "fournisseur", "crise", "avis", "buzz", "ch_greve", "ch_geant", "ch_influenceur",
                "ch_confinement")),
    "jeu": Secteur(
        "jeu", "Studio de jeu vidéo", "🎮", "jeu", "Des hits : longs développements, ventes au lancement",
        "Vous développez des jeux vidéo. Rien à vendre pendant 12 à 24 mois, puis tout se joue au lancement.",
        "Wishlists (précommandes) et note de la critique",
        "Aucun revenu pendant le développement. Le succès du mois de lancement, porté par la qualité et la "
        "communauté accumulées, conditionne la survie du studio.",
        "copies", 25, 0,
        ("Pixel Forge", "Studio Lueur", "Nébuleuse Games", "Orbital Arts", "Kraken Interactive", "Moonveil"),
        loyer=6_000, installation=150_000, libelle_installation="Matériel et licences", duree_installation=36,
        multiple=2.5, salaire=4_800, salaire_dirigeant=5_500, frais_generaux=5_000, equipe_initiale=6,
        investisseurs=700_000, part_investisseurs=0.30, pret_conseille=200_000, pret_max=500_000, pas_pret=25_000,
        subvention_initiale=150_000, libelle_subvention="Fonds d'aide au jeu vidéo (CNC)", bancabilite=0.5,
        credit_impot=0.3, base_credit="developpement", levees_max=3, echelle=3, notoriete_initiale=10,
        qualite_initiale=55, noto_gain=3.0, noto_echelle=5_000, noto_declin=0.05, qual_echelle=5_000,
        confinement=1.3, libelle_ops="Plateformes (Steam, consoles)", libelle_ca="Ventes de jeux",
        ca_cible=40_000,
        decisions={"prix": ("Prix du jeu", 5, 80, 1), "mkt": ("Marketing (wishlists)", 0, 150_000, 2_500),
                   "qual": ("Polish et tests", 0, 100_000, 2_500)},
        titre_star="Game director star", libelle_notoriete="Communauté", libelle_qualite="Savoir-faire",
        libelle_activite="Projets de jeux",
        exclus=("commande", "fournisseur", "ch_greve")),
    "luxe": Secteur(
        "luxe", "Luxe & Haute Couture", "💎", "luxe", "Marges > 80 % · volumes très faibles",
        "Une maison de luxe : sacs, prêt-à-porter, pièces d'exception fabriquées par vos artisans. Des marges "
        "extrêmes, des volumes minuscules, une clientèle insensible au prix… tant que la marque fait rêver.",
        "Indice d'exclusivité et réputation",
        "Interdiction de baisser les prix sous peine de ruiner la marque. Le marketing n'augmente pas le volume : "
        "il rehausse le prix maximal que les clientes acceptent de payer.",
        "pièces", 5_000, 700,
        ("Maison Delacour", "Atelier Verlaine", "Maison Solène", "Orsay & Fils", "Maison Évanne", "Castiglione"),
        marche=420, part_max=0.5, elasticite=0.3, extension=0.5, saturation=0.6, capacite=5,
        loyer=55_000, installation=1_200_000, libelle_installation="Atelier et boutique", duree_installation=60,
        multiple=2.5, salaire=4_200, salaire_dirigeant=8_000, frais_generaux=15_000, equipe_initiale=5,
        investisseurs=1_900_000, part_investisseurs=0.40, pret_conseille=500_000, pret_max=1_500_000,
        pas_pret=50_000, bancabilite=0.8, credit_impot=0.2, levees_max=3, echelle=8, notoriete_initiale=20,
        qualite_initiale=65, noto_gain=3.2, noto_echelle=20_000, noto_declin=0.05, qual_echelle=5_000,
        confinement=0.5, ca_cible=120_000, marge_commande=0.8,
        decisions={"prix": ("Prix par pièce", 1_000, 40_000, 100),
                   "mkt": ("Défilés, égéries et image", 0, 400_000, 5_000),
                   "qual": ("Savoir-faire et matières", 0, 100_000, 2_500)},
        titre_star="Directeur artistique star", libelle_notoriete="Réputation", libelle_qualite="Savoir-faire",
        libelle_activite="La maison",
        exclus=("commande", "buzz")),
    "aero": Secteur(
        "aero", "Aéronautique / Spatial", "🚀", "aero", "Contrats de plusieurs millions · cycles de 18 mois",
        "Deeptech B2B : vous concevez et fabriquez des sous-ensembles pour l'aviation et l'espace, sur des "
        "contrats pluriannuels remportés par appels d'offres.",
        "Carnet de commandes et pénalités de retard",
        "Des rentrées d'argent rares mais massives (acomptes, jalons). Il faut 18 mois de prospection pour "
        "viser les gros contrats, et une capacité insuffisante coûte de lourdes pénalités.",
        "contrats", 0, 1.0,
        ("Astralis", "Aéroméca", "Orbitech", "Stratos Systems", "Celestia Space", "Propulsa"),
        loyer=30_000, installation=4_000_000, libelle_installation="Salles blanches et bancs d'essai",
        duree_installation=120, multiple=1.2, salaire=6_500, salaire_dirigeant=9_000, frais_generaux=25_000,
        equipe_initiale=12, investisseurs=4_400_000, part_investisseurs=0.55, pret_conseille=2_000_000,
        pret_max=5_000_000, pas_pret=100_000, duree_pret_initial=84, subvention_initiale=1_500_000,
        libelle_subvention="Subvention France 2030", b2b=1.0, delai_clients=30, bancabilite=1.0,
        credit_impot=0.2, levees_max=3, echelle=25, notoriete_initiale=25, qualite_initiale=60, noto_gain=1.2,
        noto_echelle=20_000, noto_declin=0.02, qual_echelle=20_000, confinement=0.8, cout_fixe_ops=60_000,
        libelle_ops="Salles blanches et pénalités", ca_cible=500_000,
        decisions={"prix": None, "mkt": ("Prospection et qualification", 0, 200_000, 5_000),
                   "qual": ("R&D technologique", 0, 300_000, 5_000)},
        titre_star="Ingénieur en chef star", libelle_notoriete="Crédibilité technique",
        libelle_activite="Contrats et appels d'offres",
        exclus=("commande", "avis", "buzz", "ch_influenceur")),
    "distribution": Secteur(
        "distribution", "Grande distribution / E-commerce", "🛒", "distribution", "Marges de 2 à 5 % · stocks",
        "Un géant du commerce en ligne : des centaines de milliers de commandes, des marges au centime près, "
        "des stocks à piloter et des fournisseurs à payer.",
        "Rotation des stocks et délai de paiement fournisseurs",
        "Gestion financière au centime près : risque constant de rupture de stock, ou d'impayé fournisseur si "
        "la trésorerie flanche.",
        "commandes", 60, 47,
        ("Cartalys", "PanierPlus", "MégaMarché", "Livrée", "DistriNord", "ClicCourses"),
        marche=420_000, part_max=0.6, elasticite=3.5, extension=0.2, saturation=0.8, capacite=2_500,
        loyer=90_000, installation=3_000_000, libelle_installation="Entrepôt automatisé et site",
        duree_installation=60, multiple=0.5, saison=[1.1, 0.9, 0.95, 0.95, 1.0, 0.95, 0.95, 0.85, 1.0, 1.05, 1.35,
                                                     1.6],
        salaire=2_900, salaire_dirigeant=8_000, frais_generaux=40_000, equipe_initiale=20,
        investisseurs=2_900_000, part_investisseurs=0.60, pret_conseille=2_000_000, pret_max=4_000_000,
        pas_pret=100_000, b2b=0.0, delai_fournisseurs=60, bancabilite=1.0, credit_impot=0.2, levees_max=3,
        echelle=40, notoriete_initiale=20, qualite_initiale=50, noto_gain=4.0, noto_echelle=20_000,
        noto_declin=0.08, qual_echelle=10_000, confinement=1.3, cout_fixe_ops=60_000,
        libelle_ops="Logistique, stockage et plateforme", ca_cible=600_000, marge_commande=0.08,
        decisions={"prix": ("Panier moyen (prix)", 45, 80, 0.5), "mkt": ("Marketing", 0, 500_000, 10_000),
                   "qual": ("Service et logistique", 0, 200_000, 5_000)},
        titre_star="Directeur supply chain star", libelle_activite="Stocks et logistique"),
    "energie": Secteur(
        "energie", "Greentech / Énergie", "⚡", "energie", "Centrales financées par la dette · contrats longs",
        "Vous construisez et exploitez des parcs solaires, éoliens et des batteries, financés par de la dette de "
        "projet, et vendez l'électricité par contrats de long terme (PPA) ou sur le marché.",
        "Rendement des actifs (ROIC) et subventions environnementales",
        "Faible risque d'exploitation une fois les centrales construites, mais très sensible aux taux d'intérêt, "
        "aux prix de l'électricité et aux réglementations.",
        "MWh", 70, 0,
        ("Solvéo", "Éolia Énergies", "Voltaïs", "Terra Watt", "Hélios Capital", "NéoWatt"),
        loyer=5_000, installation=28_000_000, libelle_installation="Parc solaire n°1", duree_installation=240,
        multiple=6.0, salaire=5_800, salaire_dirigeant=8_000, frais_generaux=10_000, equipe_initiale=3,
        investisseurs=5_900_000, part_investisseurs=0.60, pret_conseille=22_400_000, pret_max=22_400_000,
        pas_pret=400_000, duree_pret_initial=180, differe_initial=8, pret_variable=True,
        libelle_pret="Dette de projet (taux variable)", subvention_initiale=2_800_000,
        libelle_subvention="Subvention d'investissement (ADEME)", b2b=1.0, delai_clients=30, bancabilite=2.0,
        credit_impot=0.2, levees_max=3, echelle=30, notoriete_initiale=25, qualite_initiale=60, noto_gain=1.5,
        noto_echelle=10_000, noto_declin=0.03, qual_echelle=5_000, confinement=0.9,
        libelle_ops="Exploitation et maintenance des centrales", libelle_ca="Ventes d'électricité",
        ca_cible=150_000,
        decisions={"prix": None, "mkt": ("Développement de projets (permis)", 0, 200_000, 5_000),
                   "qual": ("Maintenance (disponibilité)", 0, 150_000, 5_000)},
        titre_star="Ingénieur énergie star", libelle_notoriete="Crédibilité", libelle_qualite="Fiabilité",
        libelle_activite="Parc de centrales",
        exclus=("commande", "avis", "buzz", "fournisseur", "ch_greve", "ch_influenceur", "ch_geant")),
}


# ---------------------------------------------------------------- investissements stratégiques par secteur
@dataclass
class Amelioration:
    cle: str
    nom: str
    icone: str
    effet: str
    cout: float
    niveaux: int
    effets: dict


def _a(cle_, nom_, icone_, effet_, prix_, niveaux_, **effets):
    return Amelioration(cle_, nom_, icone_, effet_, prix_, niveaux_, effets)


AMELIORATIONS_SECTEUR = {
    "industrie": [
        _a("robotisation", "Robotisation des lignes", "⚙", "Coût de production par module −5 %", 1_500_000, 2,
           cout=-0.05),
        _a("ligne", "Nouvelle ligne de production", "🏗", "Capacité des usines +30 %, coûts fixes +15 %",
           2_000_000, 2, capa=0.30, ops=0.15),
        _a("certification", "Certification qualité constructeurs", "✅", "Clients attirés +12 % et qualité +8",
           400_000, 1, portee=0.12, qualite=8),
        _a("energie", "Efficacité énergétique", "♻", "Coûts fixes des usines −10 %", 900_000, 1, ops=-0.10),
        _a("bureau", "Bureau d'études intégré", "📐", "Qualité +10 et clients attirés +8 %", 800_000, 1,
           qualite=10, portee=0.08)],
    "saas": [
        _a("ia", "Module d'intelligence artificielle", "🤖", "Maturité du produit +15 et clients attirés +10 %",
           180_000, 2, maturite=15, portee=0.10),
        _a("international", "Version internationale", "🌍", "Marché accessible +35 %", 250_000, 1, portee=0.35),
        _a("success", "Équipe customer success", "💬", "Attrition −25 %", 120_000, 1, churn=-0.25),
        _a("integrations", "Place de marché d'intégrations", "🧩", "Attrition −15 % et clients attirés +8 %",
           150_000, 1, churn=-0.15, portee=0.08),
        _a("automatisation", "Automatisation du marketing", "📱", "Marketing 25 % plus efficace", 90_000, 1,
           mkt=0.25)],
    "biotech": [
        _a("criblage", "Plateforme de criblage", "🔬", "Découverte de nouvelles molécules ×1,5", 1_200_000, 2,
           decouverte=0.5),
        _a("ia", "Modélisation par IA", "🤖", "Probabilité de succès des essais +5 points", 900_000, 1,
           succes=0.05),
        _a("cro", "Partenariat avec un centre d'essais", "🏥", "Essais cliniques 20 % plus rapides", 600_000, 1,
           vitesse=0.20),
        _a("brevets", "Portefeuille de brevets renforcé", "📜", "Valeur des molécules +15 %", 350_000, 1,
           brevets=0.15)],
    "jeu": [
        _a("moteur", "Moteur de jeu maison", "⚙", "Développement 20 % plus rapide", 250_000, 1, capa=0.20),
        _a("mocap", "Studio de motion capture", "🎬", "Qualité des jeux +1,5 par mois de développement", 200_000,
           1, polish=1.5),
        _a("communaute", "Équipe communauté", "💬", "Wishlists 30 % plus nombreuses", 90_000, 1, mkt=0.30),
        _a("portage", "Portage consoles", "🎮", "Ventes +40 % à chaque sortie", 300_000, 1, portee=0.40),
        _a("localisation", "Localisation en 10 langues", "🌍", "Ventes +20 %", 80_000, 1, portee=0.20)],
    "luxe": [
        _a("newyork", "Boutique à New York", "🗽", "Clientèle accessible +40 %, loyer ×1,6", 1_500_000, 1,
           portee=0.40, loyer=0.6),
        _a("ecole", "École des métiers d'art", "🧵", "Capacité des artisans +20 % et savoir-faire +8", 500_000, 1,
           capa=0.20, qualite=8),
        _a("heritage", "Musée et archives de la maison", "🏛", "Réputation +10 et exclusivité +10", 700_000, 1,
           notoriete=10, exclusivite=10),
        _a("tannerie", "Tannerie intégrée", "🐂", "Coût des matières −20 %", 900_000, 1, cout=-0.20),
        _a("hautecouture", "Collection haute couture", "👗", "Prix maximal acceptable +15 %", 800_000, 2,
           pma=0.15)],
    "aero": [
        _a("salle", "Nouvelle salle blanche", "🏗", "Capacité de production +25 %, coûts fixes +15 %", 2_500_000,
           2, capa=0.25, ops=0.15),
        _a("certif", "Certification EN 9100 renforcée", "✅", "Crédibilité +10 et qualité +5", 400_000, 1,
           notoriete=10, qualite=5),
        _a("jumeau", "Jumeau numérique", "💻", "Productivité des équipes +15 %", 900_000, 1, capa=0.15),
        _a("composites", "Atelier composites", "🛠", "Achats de composants −15 %", 1_200_000, 1, cout=-0.15)],
    "distribution": [
        _a("robots", "Entrepôt robotisé", "🤖", "Capacité logistique +40 %", 2_500_000, 2, capa=0.40),
        _a("mdd", "Marque de distributeur", "🏷", "Coût des marchandises −4 %", 1_000_000, 1, cout=-0.04),
        _a("livraison", "Livraison en 24 h", "🚚", "Clients attirés +15 %", 1_200_000, 1, portee=0.15),
        _a("fidelite", "Programme de fidélité", "💳", "Satisfaction +10 et clients attirés +5 %", 400_000, 1,
           satisfaction=10, portee=0.05),
        _a("prevision", "Prévision des ventes par IA", "📈", "Erreurs de prévision divisées par deux", 600_000, 1,
           prevision=0.5)],
    "energie": [
        _a("pilotage", "Centre de pilotage à distance", "🖥", "Disponibilité des centrales +2 points", 800_000, 1,
           dispo=0.02),
        _a("predictive", "Maintenance prédictive", "🔧", "Coûts d'exploitation −15 %", 600_000, 1, ops=-0.15),
        _a("trading", "Desk de trading énergie", "📈", "Ventes sur le marché 5 % mieux valorisées", 500_000, 1,
           trading=0.05),
        _a("foncier", "Réserve foncière", "🗺", "Développement de projets 40 % plus rapide", 700_000, 1,
           developpement=0.40)],
}
AMELIORATIONS = {s: {a.cle: a for a in lst} for s, lst in AMELIORATIONS_SECTEUR.items()}


# ---------------------------------------------------------------- stratégies des concurrents
@dataclass
class Strategie:
    cle: str
    nom: str
    description: str
    prix: float                # prix visé, en multiple du prix de marché
    mkt: float                 # marketing, en part du chiffre d'affaires
    mkt_min: float             # plancher (× échelle du secteur)
    qual: float                # investissement qualité / R&D, en part du chiffre d'affaires
    qual_min: float
    seuil_recrutement: float   # charge de travail qui déclenche une embauche
    capital: float             # multiplicateur des fonds levés au départ


STRATEGIES = {
    "lowcost": Strategie("lowcost", "Low-cost", "prix cassés et volumes", 0.85, 0.05, 1_500, 0.02, 800, 0.95, 1.0),
    "premium": Strategie("premium", "Premium", "prix élevés et qualité irréprochable", 1.20, 0.05, 1_500, 0.08,
                         2_500, 0.85, 1.1),
    "equilibre": Strategie("equilibre", "Équilibré", "gestion prudente, croissance régulière", 1.00, 0.06, 2_000,
                           0.04, 1_500, 0.92, 1.0),
    "startup": Strategie("startup", "Start-up financée", "fonds levés, croissance à tout prix", 0.92, 0.12, 4_000,
                         0.05, 2_000, 0.80, 1.6),
}
DIFFICULTES = {"Facile": 0.7, "Normal": 1.0, "Difficile": 1.35}
COULEURS = ["#2f5bea", "#e5484d", "#f0a020", "#12a594", "#8e4ec6", "#d6409f"]   # la première : le joueur


# ---------------------------------------------------------------- prêts
@dataclass
class Pret:
    capital_restant: float
    mensualite: float
    taux: float = TAUX_PRET
    duree: int = DUREE_PRET        # mois
    libelle: str = "Prêt bancaire"
    montant: float = 0.0           # capital emprunté à l'origine
    restant: int = DUREE_PRET      # mensualités restantes
    differe: int = 0               # mois pendant lesquels on ne paie que les intérêts
    variable: bool = False         # taux indexé sur le taux de référence
    marge: float = 0.0             # marge au-dessus du taux de référence (prêts variables)

    def interets_mois(self) -> float:
        return self.capital_restant * self.taux / 12

    def amortissement_mois(self) -> float:
        if self.differe > 0:
            return 0.0
        return min(self.capital_restant, max(0.0, self.mensualite - self.interets_mois()))

    def interets_restants(self) -> float:
        """Intérêts qu'il reste à payer si le prêt va à son terme (au taux actuel)."""
        c, tot, d = self.capital_restant, 0.0, self.differe
        mens = self.mensualite
        for _ in range(self.restant + d + 1):
            if c <= 1:
                break
            i = c * self.taux / 12
            tot += i
            if d > 0:
                d -= 1
                continue
            c -= min(c, max(0.0, mens - i))
        return tot

    def mois_restants(self) -> int:
        return self.restant + self.differe

    def penalite(self) -> float:
        """Indemnité de remboursement anticipé : 6 mois d'intérêts, plafonnée à 3 % du capital."""
        return min(0.03 * self.capital_restant, 6 * self.interets_mois())


def nouveau_pret(montant: float, taux: float = TAUX_PRET, duree: int = DUREE_PRET,
                 libelle: str = "Prêt bancaire", differe: int = 0, variable: bool = False,
                 marge: float = 0.0) -> Pret:
    return Pret(montant, annuite(montant, taux, duree), taux, duree, libelle, montant, duree, differe, variable,
                marge)


# ---------------------------------------------------------------- les profils de l'équipe
@dataclass
class Profil:
    cle: str
    titre: str
    icone: str
    salaire: float             # prétention mensuelle chargée de base (avant talent et secteur)
    capacite: float            # production, en part d'un salarié standard
    effet: str                 # ce qu'il apporte
    exigence: str              # sa condition morale (clé)
    exigence_txt: str          # {montant} est remplacé selon le secteur
    frequence: float           # fréquence dans le vivier de candidats


PROFILS = {
    "equipier": Profil("equipier", "Équipier polyvalent", "👤", 3_600, 1.0, "Produit comme un salarié standard.",
                       "", "Aucune exigence particulière.", 3.0),
    "junior": Profil("junior", "Junior motivé", "🌱", 2_500, 0.6, "Capacité 60 % au départ, qui progresse chaque "
                     "mois jusqu'à 110 %. Pas cher.", "formation",
                     "Veut apprendre : au moins {montant} par mois de budget qualité / R&D.", 2.0),
    "star": Profil("star", "CTO star", "⭐", 6_500, 1.3, "Capacité ×1,3 et qualité +2,5 par mois.", "parts",
                   "Veut 2 % du capital (BSPCE) à l'embauche.", 1.0),
    "commercial": Profil("commercial", "Commercial agressif", "📈", 2_800, 0.5, "Attire 10 % de clients en plus, mais "
                         "les brusque : satisfaction −1,5 par mois. Capacité 50 %.", "commission",
                         "Fixe réduit + 3 % de commission sur tout le chiffre d'affaires.", 1.5),
    "rh": Profil("rh", "RH rassurant", "🤝", 3_800, 0.3, "Moral de l'équipe +2,5 par mois, et chacun se sent "
                 "mieux traité. Capacité 30 %.", "licenciement",
                 "Refuse les licenciements : au premier départ forcé, il démissionne.", 1.0),
    "growth": Profil("growth", "Growth hacker", "🚀", 4_600, 0.4, "Marketing 30 % plus efficace et notoriété +1,5 "
                     "par mois. Capacité 40 %.", "budget_mkt", "Exige au moins {montant} de marketing par mois.", 1.0),
    "daf": Profil("daf", "Directeur financier prudent", "🧮", 5_200, 0.2, "Impayés −60 %, note bancaire améliorée, "
                  "emprunts 0,5 point moins chers. Capacité 20 %.", "decouvert",
                  "Ne tolère pas le découvert : démissionne après 2 mois dans le rouge.", 0.7),
    "mercenaire": Profil("mercenaire", "Mercenaire expérimenté", "💼", 5_200, 1.5, "Capacité ×1,5 dès le premier "
                         "jour.", "argent", "Suit l'argent : cible favorite des concurrents, qui tenteront de le "
                         "débaucher.", 1.0),
    "perfectionniste": Profil("perfectionniste", "Perfectionniste de la qualité", "✨", 4_200, 0.8,
                              "Qualité +1,5 et satisfaction clients +1,5 par mois. Capacité 80 %.", "premium",
                              "Refuse de brader : ne supporte pas un prix plus de 10 % sous celui du marché.", 1.0),
}
PRENOMS = ["Camille", "Léa", "Hugo", "Inès", "Karim", "Sofia", "Thomas", "Yasmine", "Lucas", "Chloé", "Mehdi",
           "Emma", "Julien", "Aïcha", "Nathan", "Manon", "Samuel", "Zoé", "Antoine", "Nadia", "Paul", "Jade",
           "Rayan", "Clara", "Louis", "Salomé", "Théo", "Lina", "Maxime", "Eva", "Bastien", "Fatou", "Victor",
           "Margaux", "Adrien", "Leïla"]


@dataclass
class Employe:
    nom: str
    profil: str
    salaire: float             # salaire mensuel chargé convenu
    pretention: float          # ce qu'il demandait
    talent: float = 1.0        # 0,85 à 1,25 : module ses effets
    moral: float = 70.0
    anciennete: int = 0
    progression: float = 1.0   # juniors : capacité qui grandit
    alerte: int = 0            # mois d'affilée où son exigence n'est pas respectée
    parts: float = 0.0         # part du capital reçue
    origine: str = ""          # entreprise d'origine (rachat, débauchage)

    @property
    def p(self) -> Profil:
        return PROFILS[self.profil]

    def capa(self) -> float:
        if self.profil == "junior":
            return self.progression * self.talent
        base = self.p.capacite
        return base * self.talent if base >= 0.8 else base


def chance_acceptation(ratio: float) -> float:
    """Probabilité qu'une offre à ratio × le prix demandé soit acceptée (candidat, vendeur…)."""
    return 1.0 if ratio >= 1 else max(0.0, (ratio - 0.85) / 0.15)


# ---------------------------------------------------------------- croissance externe : filiales à racheter
# types de cibles : (libellé, taille relative, marge d'EBE, multiple de valorisation)
TYPES_CIBLE = {
    "fournisseur": ("Fournisseur", 0.8, 0.12, 0.6),
    "sous_traitant": ("Sous-traitant", 1.0, 0.10, 0.5),
    "niche": ("Concurrent de niche", 0.8, 0.08, None),
    "complementaire": ("Activité complémentaire", 1.3, 0.15, 0.8),
    "techno": ("Start-up technologique", 0.3, -0.5, 1.5),
}
# effets durables des filiales selon le type de secteur : (texte, effets)
EFFETS_CIBLE_DEFAUT = {
    "fournisseur": ("Vos achats coûtent 10 % de moins et vous êtes à l'abri des pénuries.", {"cout": -0.10,
                                                                                          "amont": 1}),
    "sous_traitant": ("Capacité de production +15 %.", {"capa": 0.15}),
    "niche": ("Fusion : ses clients et son équipe rejoignent votre entreprise, notoriété +5.", {}),
    "complementaire": ("Nouvelle source de revenus et ventes croisées : clientèle accessible +6 %, notoriété +5.",
                       {"portee": 0.06, "notoriete": 5}),
    "techno": ("Qualité +8 tout de suite et marketing 15 % plus efficace. Elle perd encore de l'argent.",
               {"qualite": 8, "mkt": 0.15}),
}
EFFETS_CIBLE_SECTEUR = {
    "biotech": {"fournisseur": ("Coûts des essais cliniques −10 %.", {"ops": -0.10}),
                "sous_traitant": ("Essais cliniques 15 % plus rapides.", {"vitesse": 0.15}),
                "niche": ("Fusion : sa molécule rejoint votre pipeline, avec son équipe.", {}),
                "techno": ("Qualité scientifique +8 et découverte de molécules +30 %.", {"qualite": 8,
                                                                                         "decouverte": 0.3})},
    "jeu": {"fournisseur": ("Développement 10 % plus rapide.", {"capa": 0.10}),
            "sous_traitant": ("Qualité des jeux +1 par mois de développement.", {"polish": 1.0}),
            "niche": ("Fusion : son équipe et sa communauté vous rejoignent.", {}),
            "complementaire": ("Nouveaux revenus d'édition, et ventes de vos jeux +10 %.", {"portee": 0.10,
                                                                                           "notoriete": 5})},
    "aero": {"niche": ("Fusion : ses ingénieurs et sa crédibilité technique vous rejoignent.", {}),
             "complementaire": ("Nouvelle source de revenus, et crédibilité technique +8.", {"notoriete": 8})},
    "energie": {"fournisseur": ("Vos prochaines centrales coûtent 8 % de moins.", {"capex": -0.08}),
                "sous_traitant": ("Disponibilité des centrales +1 point et exploitation −8 %.",
                                  {"dispo": 0.01, "ops": -0.08}),
                "niche": ("Fusion : sa centrale rejoint votre parc.", {}),
                "complementaire": ("Nouvelle source de revenus, et crédibilité +5.", {"notoriete": 5}),
                "techno": ("Fiabilité +8 et développement de projets 15 % plus rapide.", {"qualite": 8,
                                                                                          "developpement": 0.15})},
}


def effet_cible(modele: str, type_: str) -> tuple[str, dict]:
    return EFFETS_CIBLE_SECTEUR.get(modele, {}).get(type_, EFFETS_CIBLE_DEFAUT[type_])


# pour chaque secteur : un nom de métier et des noms d'entreprises par type de cible
CIBLES = {
    "industrie": {"fournisseur": ("Fonderie d'aluminium", ["Fonderies du Rhône", "AluCast"]),
                  "sous_traitant": ("Usine d'emboutissage", ["Emboutis Lorraine", "PressTech"]),
                  "niche": ("Équipementier de niche", ["Précimeca", "Hydrofluid", "Visserie Morand"]),
                  "complementaire": ("Réseau de pièces de rechange", ["PiècesExpress", "Rechange Pro"]),
                  "techno": ("Start-up de batteries solides", ["SolidCell", "Ionik"])},
    "saas": {"fournisseur": ("Hébergeur cloud", ["NuageFR", "Datacentre Bleu"]),
             "sous_traitant": ("Studio de développement", ["CodeFactory", "DevNation"]),
             "niche": ("Logiciel SaaS de niche", ["Payzen RH", "Notefrais", "Stockly"]),
             "complementaire": ("Cabinet d'intégration et de formation", ["Onboard Conseil", "Formapro"]),
             "techno": ("Start-up d'intelligence artificielle", ["Neuronix", "Predicta"])},
    "biotech": {"fournisseur": ("Façonnier pharmaceutique", ["PharmaFab", "BioProd Lyon"]),
                "sous_traitant": ("Société de recherche clinique", ["ClinEurope", "TrialCare"]),
                "niche": ("Biotech avec une molécule", ["Oncovia", "RareGen", "NeuroPep"]),
                "complementaire": ("Laboratoire de diagnostic", ["DiagnoLab", "BioMarqueurs"]),
                "techno": ("Start-up d'IA pour la découverte", ["MoleculIA", "DeepPharma"])},
    "jeu": {"fournisseur": ("Studio d'animation 3D", ["Anim3D", "Polygone"]),
            "sous_traitant": ("Studio de tests", ["BugHunters", "QA Factory"]),
            "niche": ("Petit studio indépendant", ["Lumen Games", "Petit Pixel", "Studio Bocage"]),
            "complementaire": ("Éditeur de jeux", ["Nébula Publishing", "Indie Box"]),
            "techno": ("Start-up d'outils d'IA générative", ["GenAsset", "ProcedurIA"])},
    "luxe": {"fournisseur": ("Tannerie", ["Tannerie Dumas", "Cuirs d'Annonay"]),
             "sous_traitant": ("Atelier de maroquinerie", ["Atelier Morel", "Maroquinerie du Marais"]),
             "niche": ("Jeune créateur", ["Maison Arlette", "Studio Céleste", "Louvain Paris"]),
             "complementaire": ("Joaillier", ["Joaillerie Verneuil", "Or & Lumière"]),
             "techno": ("Start-up de traçabilité", ["TraceLux", "AuthentiQ"])},
    "aero": {"fournisseur": ("Fabricant de composants électroniques", ["ElectroSpace", "RadHard"]),
             "sous_traitant": ("Atelier d'usinage de précision", ["Usinage Aquitaine", "PrecisAéro"]),
             "niche": ("Start-up de micro-satellites", ["NanoSat", "OrbiLab", "CubeSpace"]),
             "complementaire": ("Société de services en orbite", ["OrbitCare", "SpaceOps"]),
             "techno": ("Start-up de propulsion électrique", ["IonDrive", "PlasmaThrust"])},
    "distribution": {"fournisseur": ("Grossiste", ["GrossiNord", "Centrale Achats"]),
                     "sous_traitant": ("Transporteur", ["TransExpress", "Roule Vite"]),
                     "niche": ("Site e-commerce de niche", ["BioMarché", "Animalis", "BricoClic"]),
                     "complementaire": ("Réseau de magasins de proximité", ["Proxi Coin", "Épicerie Plus"]),
                     "techno": ("Start-up de logistique robotisée", ["RoboPick", "StockBot"])},
    "energie": {"fournisseur": ("Fabricant de panneaux solaires", ["SolarFab", "Photonix"]),
                "sous_traitant": ("Société de maintenance éolienne", ["WindCare", "Éol Services"]),
                "niche": ("Petit producteur d'électricité", ["Hydro Vallée", "Méthagri", "Soleil du Sud"]),
                "complementaire": ("Fournisseur d'électricité verte", ["VertWatt", "Énergie Citoyenne"]),
                "techno": ("Start-up d'hydrogène vert", ["H2Val", "Hydrogenia"])},
}


@dataclass
class Filiale:
    nom: str
    type: str
    metier: str
    ca: float                  # chiffre d'affaires mensuel de base
    marge: float               # marge d'EBE
    salaries: int
    tresorerie: float
    dette: float
    immos: float
    prix: float                # prix demandé par les vendeurs
    dispo: int = 4             # mois pendant lesquels l'occasion reste ouverte
    refus: int = 0             # offres déjà refusées
    goodwill: float = 0.0      # une fois achetée
    acquise_le: str = ""
    immo_ref: dict | None = None
    pret_ref: "Pret | None" = None
    niveau: int = 0            # développements réalisés depuis le rachat (0 à 3)
    investi: float = 0.0       # argent investi pour la développer
    dev_refs: list = field(default_factory=list)   # immobilisations de développement
    effet: str = ""            # effet durable (texte), selon le secteur de l'acheteur
    effets: dict = field(default_factory=dict)

    def valeur_entreprise(self, multiple_secteur: float) -> float:
        m = TYPES_CIBLE[self.type][3] or multiple_secteur
        return max(10_000.0, self.ca * 12 * m * max(0.5, 1 + self.marge))

    @property
    def libelle_type(self) -> str:
        return TYPES_CIBLE[self.type][0]

    def valeur(self, multiple_secteur: float) -> float:
        return self.valeur_entreprise(multiple_secteur) + self.tresorerie - self.dette


# =============================================================================
# Mécaniques propres à chaque secteur
# =============================================================================
class Activite:
    """Règles propres à un secteur. Chaque entreprise possède la sienne, avec son état (usines, pipeline…).
    La base décrit un marché classique : une clientèle partagée entre concurrents selon leur attrait."""
    partage = True             # la demande vient d'un marché partagé entre concurrents
    unite_capacite = "unités / mois"
    k_mkt, k_qual = 1.0, 1.0   # poids du marketing et de la R&D dans les budgets des concurrents

    def __init__(self, e: "Entreprise"):
        self.e = e

    # ------------------------------------------------------------ demande et capacité
    def capacite(self) -> float:
        e = self.e
        penurie = 0.6 if e.penurie > 0 else 1.0
        return ((1 + sum(x.capa() for x in e.equipe)) * e.s.capacite * e.capa_mult
                * (0.75 + e.moral / 400) * penurie)

    def attrait(self) -> float:
        e, s = self.e, self.e.s
        ratio_prix = e.prix / s.prix_ref if s.prix_ref else 1.0
        a = (0.1 + e.notoriete / 50) * (0.4 + e.qualite / 80) * ratio_prix ** (-s.elasticite)
        # les clients professionnels préfèrent les fournisseurs qui les laissent payer à 30 ou 60 jours
        delai = 1 + (DELAIS_CLIENTS[e.delai_clients][0] - 1) * s.b2b
        equipe = 1 + min(0.4, e.effet("attrait"))  # force de vente
        return a * (0.6 + e.satisfaction / 175) * e.portee * delai * equipe

    def preparer(self) -> None:
        pass

    def exploiter(self, demande: float, mois_cal: int, t: int, marche: "Marche") -> dict:
        e = self.e
        capa = self.capacite()
        ventes = min(demande, capa)
        e.vendre(ventes * e.prix, t)
        e.acheter(ventes * e.cout_unitaire, t)
        return {"ventes": ventes, "capacite": capa, "utilisation": demande / capa if capa else 0.0,
                "manques": max(0.0, demande - capa)}

    def payer_fournisseurs(self, t: int) -> bool:
        return False           # False : le paiement standard s'applique

    def fixes(self) -> float:
        return 0.0

    def ajuster_valeur(self, ev: float) -> float:
        return ev

    def levee_possible(self) -> bool:
        return len(self.e.mois_reels()) >= 6 and self.e.ca_annualise() > 0

    # ------------------------------------------------------------ concurrents pilotés par l'ordinateur
    def decider_ia(self, marche: "Marche", force: float) -> None:
        """Prix et équipe pour un marché classique."""
        e, s, st = self.e, self.e.s, self.e.strategie
        h = e.historique[-1] if e.historique else None
        if s.prix_ref:
            reels = e.mois_reels()
            if len(reels) >= 3 and len(reels) % 3 == 0:
                der = reels[-3:]
                res = sum(x.get("rcai", x["resultat"]) for x in der)
                part = sum(x["part"] for x in der) / 3
                juste = 1 / max(1, len(marche.actives))
                if res < 0 and part >= juste * 0.8:
                    e.mult_prix = min(1.5, e.mult_prix * 1.04)
                elif part < juste * 0.6 and e.mult_prix > 0.85:
                    e.mult_prix *= 0.97
            cible = s.prix_ref * e.mult_prix * (e.cout_unitaire / s.cout_unitaire) ** 0.6 if s.cout_unitaire else \
                s.prix_ref * e.mult_prix
            j = marche.joueur
            if (j.actif and len(e.historique) >= 3 and j.prix < e.prix * 0.9
                    and e.historique[-1]["part"] < e.historique[-3]["part"] - 0.02 and not e.guerre_prix):
                e.guerre_prix = 4
                marche.nouvelles.append(f"📉 {e.nom} riposte à vos prix bas : −8 % sur ses tarifs pendant 4 mois.")
            if e.guerre_prix:
                cible *= 0.92
                e.guerre_prix -= 1
            e.prix = round(max(e.cout_unitaire * 1.08, cible), 2)
        if h and self.recrute_selon_charge():
            n = e.salaries
            if h["utilisation"] > st.seuil_recrutement and e.tresorerie > 6 * s.salaire:
                e.recruter()
            elif n > s.equipe_initiale and h["utilisation"] * (n + 1) / n < 0.7:
                e.salaries -= 1                  # départ non remplacé

    def recrute_selon_charge(self) -> bool:
        return True

    def budgets_ia(self, force: float) -> tuple[float, float]:
        e, s, st = self.e, self.e.s, self.e.strategie
        h = e.historique[-1] if e.historique else None
        ca = h["ca"] if h else 0.0
        mk = max(st.mkt_min * s.echelle, ca * st.mkt * self.k_mkt) * force
        q = max(st.qual_min * s.echelle, ca * st.qual * self.k_qual) * force
        return mk, q

    # ------------------------------------------------------------ affichage
    def metriques(self) -> dict:
        return {}

    def kpis(self) -> list[dict]:
        return []

    def jauge(self) -> tuple[str, float, str, bool]:
        h = self.e.historique[-1] if self.e.historique else None
        u = h["utilisation"] * 100 if h else 0.0
        return "Charge de travail", u, f"{u:.0f} %", True

    def resume(self) -> str:
        return ""

    def conseils(self) -> list[str]:
        return []

    # ------------------------------------------------------------ rachats et événements propres
    def fusion_niche(self, f: "Filiale") -> str:
        e, s = self.e, self.e.s
        if s.recurrent:
            clients = f.ca / max(1.0, e.prix) * 0.85
            e.abonnes += clients
            return f"{fmt_n(clients)} {s.unite} (15 % partent pendant la migration)"
        e.portee *= 1.12
        return "sa clientèle (clientèle accessible +12 %)"

    def evenement(self, marche: "Marche") -> dict | None:
        return None

    def resoudre(self, ev: dict, oui: bool, marche: "Marche") -> str:
        return ""


# ---------------------------------------------------------------- industrie lourde
class ActiviteIndustrie(Activite):
    unite_capacite = "modules par mois (usines)"
    k_mkt, k_qual = 0.3, 0.3
    COUT_USINE, CAPA_USINE, FIXE_USINE, TRAVAUX_USINE = 7_500_000, 1_200.0, 170_000.0, 6

    def __init__(self, e):
        super().__init__(e)
        self.usines = [{"nom": "Usine n°1", "capacite": 1_500.0, "fixe": e.s.cout_fixe_ops, "etat": "active",
                        "travaux": 0}]
        self.cumul = 0.0              # production cumulée : l'expérience fait baisser les coûts
        self.production = 0.0
        self.utilisation = 0.0

    def facteur_experience(self) -> float:
        ref = 9_000.0
        return max(0.88, (max(self.cumul, ref) / ref) ** -0.044)

    def cout_module(self) -> float:
        return self.e.cout_unitaire * self.facteur_experience()

    def capacite_nominale(self) -> float:
        return sum(u["capacite"] for u in self.usines if u["etat"] == "active") * self.e.capa_mult

    def capacite(self) -> float:
        e = self.e
        penurie = 0.6 if e.penurie > 0 else 1.0
        bonus = min(0.10, 0.01 * sum(x.capa() for x in e.equipe))   # ingénieurs et techniciens fiabilisent
        return self.capacite_nominale() * (1 + bonus) * (0.9 + e.moral / 1000) * penurie

    def fixes(self) -> float:
        k = {"active": 1.0, "sommeil": 0.3, "travaux": 0.0}
        return sum(u["fixe"] * k[u["etat"]] for u in self.usines) * self.e.ops_mult

    def exploiter(self, demande, mois_cal, t, marche):
        e = self.e
        capa = self.capacite()
        ventes = min(demande, capa)
        e.vendre(ventes * e.prix, t)
        e.acheter(ventes * self.cout_module(), t)
        e.charge("operations", self.fixes(), "charges")
        self.cumul += ventes
        self.production = ventes
        nominale = self.capacite_nominale()
        self.utilisation = ventes / nominale if nominale else 0.0
        msgs = []
        for u in self.usines:
            if u["etat"] == "travaux":
                u["travaux"] -= 1
                if u["travaux"] <= 0:
                    u["etat"] = "active"
                    msgs.append(f"🏭 {u['nom']} entre en service : +{fmt_n(u['capacite'])} modules par mois.")
        if self.utilisation < 0.7 and nominale and e.joueur:
            msgs.append(f"⚠ Usines utilisées à {self.utilisation:.0%} seulement : les coûts fixes pèsent lourd.")
        return {"ventes": ventes, "capacite": capa, "utilisation": demande / capa if capa else 0.0,
                "manques": max(0.0, demande - capa), "messages": msgs}

    def point_mort(self) -> float:
        """Taux d'utilisation à partir duquel l'entreprise gagne de l'argent (après amortissements et intérêts)."""
        e = self.e
        contrib = e.prix - self.cout_module()
        nominale = self.capacite_nominale()
        if contrib <= 0 or not nominale:
            return float("inf")
        fixes = (self.fixes() + e.charges_fixes() - self.fixes() + e.mkt + e.qinv
                 + sum(i["brut"] / i["duree"] for i in e.immos if i["amorti"] < i["brut"])
                 + sum(p.interets_mois() for p in e.prets))
        return fixes / (contrib * nominale)

    def construire(self) -> str:
        e = self.e
        if any(u["etat"] == "travaux" for u in self.usines):
            return "Une usine est déjà en construction."
        if e.tresorerie < self.COUT_USINE:
            return (f"Trésorerie insuffisante : il faut {fmt(self.COUT_USINE)} pour construire une usine "
                    "(empruntez ou levez des fonds d'abord).")
        n = len(self.usines) + 1
        e.investir(f"Usine n°{n}", self.COUT_USINE, 120)
        self.usines.append({"nom": f"Usine n°{n}", "capacite": self.CAPA_USINE, "fixe": self.FIXE_USINE,
                            "etat": "travaux", "travaux": self.TRAVAUX_USINE})
        return (f"Construction de l'usine n°{n} lancée pour {fmt(self.COUT_USINE)} : mise en service dans "
                f"{self.TRAVAUX_USINE} mois (+{fmt_n(self.CAPA_USINE)} modules par mois, {fmt(self.FIXE_USINE)} de "
                "coûts fixes mensuels).")

    def mettre_en_sommeil(self, i: int) -> str:
        u = self.usines[i]
        if u["etat"] != "active":
            return f"{u['nom']} n'est pas en activité."
        if sum(1 for x in self.usines if x["etat"] == "active") <= 1:
            return "Impossible : c'est votre dernière usine en activité."
        u["etat"] = "sommeil"
        self.e.moral = max(0.0, self.e.moral - 10)
        return (f"{u['nom']} mise en sommeil (chômage partiel) : ses coûts fixes baissent de 70 %, mais sa capacité "
                "est perdue. Le moral de l'équipe baisse.")

    def relancer(self, i: int) -> str:
        u = self.usines[i]
        if u["etat"] != "sommeil":
            return f"{u['nom']} n'est pas en sommeil."
        cout = u["fixe"] * 0.5
        self.e.charge("operations", cout, "charges")
        u["etat"] = "active"
        return f"{u['nom']} redémarre : {fmt(cout)} de remise en route."

    def recrute_selon_charge(self) -> bool:
        return False

    def decider_ia(self, marche, force):
        super().decider_ia(marche, force)
        e = self.e
        reels = e.mois_reels()
        if (len(reels) >= 4 and all(h["utilisation"] > 1.05 for h in reels[-3:])
                and not any(u["etat"] == "travaux" for u in self.usines) and self.e.rng.random() < 0.3):
            besoin = self.COUT_USINE * 1.1 - e.tresorerie
            if besoin > 0 and e.capacite_emprunt() >= besoin:
                e.emprunter(besoin, 7)
            if e.tresorerie >= self.COUT_USINE * 1.05:
                self.construire()
                marche.nouvelles.append(f"🏭 {e.nom} construit une nouvelle usine.")

    def metriques(self):
        return {"utilisation": self.utilisation, "cout": self.cout_module()}

    def kpis(self):
        e = self.e
        serie_u = [h.get("kpi", {}).get("utilisation", 0.0) for h in e.mois_reels()]
        pm = self.point_mort()
        coul = VERT_K if self.utilisation >= min(pm, 1.0) else ROUGE_K
        return [{"titre": "Utilisation des usines", "valeur": f"{self.utilisation:.0%}".replace("%", " %"),
                 "detail": ("point mort ≈ " + (f"{pm:.0%}".replace("%", " %") if pm < 5 else "hors d'atteinte")),
                 "serie": serie_u, "couleur": coul},
                {"titre": "Coût de production", "valeur": fmt(self.cout_module()),
                 "detail": f"par module · −{1 - self.facteur_experience():.0%} d'expérience".replace("%", " %"),
                 "serie": [h.get("kpi", {}).get("cout", 0.0) for h in e.mois_reels()], "couleur": None}]

    def jauge(self):
        u = self.utilisation * 100
        return "Utilisation usine", u, f"{u:.0f} %", False

    def resume(self):
        return f"Usines {self.utilisation:.0%} · coût {fmt(self.cout_module())}".replace("%", " %")

    def conseils(self):
        c = []
        pm = self.point_mort()
        if self.e.mois_reels() and self.utilisation < pm:
            c.append(f"Usines utilisées à {self.utilisation:.0%}, sous le point mort ({min(pm, 9.99):.0%}) : gagnez des "
                     "parts de marché (prix, prospection) ou mettez une usine en sommeil.".replace("%", " %"))
        h = self.e.historique[-1] if self.e.historique else None
        if h and h["utilisation"] > 1.05:
            c.append("Usines saturées : vous perdez des commandes. Nouvelle ligne ou nouvelle usine (page Usines).")
        return c


# ---------------------------------------------------------------- logiciel SaaS
class ActiviteSaaS(Activite):
    unite_capacite = "clients suivis"
    k_mkt, k_qual = 4.0, 3.0

    def __init__(self, e):
        super().__init__(e)
        self.maturite = 20.0          # maturité du produit (0 → 100)
        self.nouveaux = self.perdus = 0.0
        self.churn_mois = 0.0

    def preparer(self):
        e = self.e
        gain = 3.0 * math.log1p(e.qinv / (2_000 * e.s.echelle)) + 0.8 * e.effet("qualite") - 0.4
        self.maturite = max(0.0, min(100.0, self.maturite + gain))

    def attrait(self):
        return super().attrait() * (self.maturite / 100) ** 1.5

    def taux_churn(self) -> float:
        e, s = self.e, self.e.s
        ratio = e.prix / s.prix_ref
        return s.churn * max(0.4, 1.5 - self.maturite / 200 - e.qualite / 200) * ratio ** 0.6 * e.churn_mult

    def exploiter(self, demande, mois_cal, t, marche):
        e = self.e
        capa = self.capacite()
        avant = e.abonnes
        perdus = avant * min(0.5, self.taux_churn())
        e.abonnes = max(0.0, avant - perdus + demande)
        manques = 0.0
        if e.abonnes > capa:                     # support saturé : une partie des clients en trop s'en va
            manques = (e.abonnes - capa) * 0.3
            e.abonnes -= manques
            perdus += manques
        self.nouveaux, self.perdus = demande, perdus
        self.churn_mois = perdus / avant if avant > 1 else 0.0
        e.vendre(e.abonnes * e.prix, t)
        e.acheter(e.abonnes * e.cout_unitaire, t)
        return {"ventes": e.abonnes, "capacite": capa, "utilisation": e.abonnes / capa if capa else 0.0,
                "manques": manques}

    def ltv(self) -> float:
        e = self.e
        churn = max(0.004, self.churn_mois or self.taux_churn())
        return e.prix * (1 - e.cout_unitaire / max(1.0, e.prix)) / churn

    def cac(self) -> float:
        return self.e.mkt / self.nouveaux if self.nouveaux > 0.5 else float("inf")

    def ajuster_valeur(self, ev):
        # un produit mûr vaut quelque chose, même avant d'avoir beaucoup de clients
        return ev + self.e.s.installation * 2 * (self.maturite / 100) ** 2

    def levee_possible(self):
        e = self.e
        return len(e.mois_reels()) >= 3 and (self.maturite >= 40 or e.abonnes * e.prix >= 10_000)

    def metriques(self):
        e = self.e
        return {"mrr": e.abonnes * e.prix, "churn": self.churn_mois, "maturite": self.maturite,
                "nouveaux": self.nouveaux}

    def kpis(self):
        e = self.e
        reels = e.mois_reels()
        mrr = e.abonnes * e.prix
        ratio = self.ltv() / self.cac() if self.cac() not in (0, float("inf")) else None
        return [{"titre": "Revenu récurrent (MRR)", "valeur": fmt(mrr), "detail": f"ARR {fmt_c(mrr * 12)}",
                 "serie": [h.get("kpi", {}).get("mrr", 0.0) for h in reels], "couleur": None},
                {"titre": "Attrition mensuelle", "valeur": f"{self.churn_mois * 100:.1f} %".replace(".", ","),
                 "detail": f"LTV {fmt_c(self.ltv())}" + (f" · LTV/CAC {ratio:.1f}".replace(".", ",") if ratio else ""),
                 "serie": [h.get("kpi", {}).get("churn", 0.0) for h in reels],
                 "couleur": ROUGE_K if self.churn_mois > 0.04 else VERT_K if self.churn_mois < 0.02 else None}]

    def jauge(self):
        return "Maturité produit", self.maturite, f"{self.maturite:.0f} %", False

    def resume(self):
        e = self.e
        return f"{fmt_n(e.abonnes)} clients · MRR {fmt_c(e.abonnes * e.prix)}"

    def conseils(self):
        c = []
        if self.maturite < 50:
            c.append(f"Produit encore jeune (maturité {self.maturite:.0f} %) : la R&D fera venir les clients.")
        if self.churn_mois > 0.035 and self.e.abonnes > 20:
            c.append(f"Attrition élevée ({self.churn_mois * 100:.1f} %/mois) : améliorez le produit et le support."
                     .replace(".", ",", 1))
        cac = self.cac()
        if self.e.abonnes > 20 and cac != float("inf") and self.ltv() < 3 * cac:
            c.append("LTV inférieure à 3 × le coût d'acquisition : votre marketing coûte trop cher par client.")
        return c


# ---------------------------------------------------------------- biotech
PHASES = [("Préclinique", 6, 80_000, 0.65, 2), ("Phase 1", 8, 250_000, 0.65, 3), ("Phase 2", 10, 600_000, 0.45, 5),
          ("Phase 3", 12, 1_500_000, 0.65, 8), ("Enregistrement", 3, 100_000, 0.90, 2)]
INDICATIONS = [("fibrose pulmonaire", 220e6), ("maladie de Parkinson", 400e6), ("cancer du pancréas", 350e6),
               ("lupus", 180e6), ("mucoviscidose", 250e6), ("migraine chronique", 150e6),
               ("stéatose hépatique", 300e6), ("dégénérescence maculaire", 280e6), ("sclérose en plaques", 320e6),
               ("maladie rare de l'enfant", 120e6), ("psoriasis sévère", 200e6), ("leucémie", 260e6)]
LABORATOIRES = ["Novagen Pharma", "Helvetia Pharma", "Laboratoires Aurèle", "Mérival Santé", "Atlantis Therapeutics",
                "Groupe Pharmacia Nova", "Rhône Biosciences", "Nordic Pharma"]


@dataclass
class Molecule:
    nom: str
    indication: str
    potentiel: float            # ventes annuelles au pic si le médicament est autorisé
    phase: int = 0              # indice dans PHASES ; 5 = autorisée
    avancement: float = 0.0     # 0 → 1 dans la phase en cours
    statut: str = "actif"       # actif, pause, licencie, echec, abandonne, commercialise
    accelere: bool = False
    partenaire: str = ""
    royalties: float = 0.0
    jalon: float = 0.0          # paiement du partenaire à chaque succès (molécule licenciée)
    mois_vente: int = 0
    recherche_partenaire: bool = False

    @property
    def libelle_phase(self) -> str:
        return "Autorisé" if self.phase >= 5 else PHASES[self.phase][0]

    @property
    def en_clinique(self) -> bool:
        return self.phase >= 1 and self.statut in ("actif", "pause", "licencie", "commercialise")


class ActiviteBiotech(Activite):
    partage = False
    unite_capacite = "chercheurs (essais cliniques)"

    def __init__(self, e):
        super().__init__(e)
        r = e.rng
        self.numero = 100 + r.randint(1, 8) * 100
        self.prefixe = "".join(c for c in e.nom.upper() if c.isalpha())[:3] or "BIO"
        self.molecules: list[Molecule] = []
        self.nouvelle_molecule(phase=1)
        self.nouvelle_molecule(phase=0)
        self.cout_mois = 0.0
        self.faillite = False
        self.offres: list[Molecule] = []      # molécules pour lesquelles un laboratoire va faire une offre

    def nouvelle_molecule(self, phase: int = 0, potentiel: float | None = None) -> Molecule:
        r = self.e.rng
        self.numero += 1
        ind, pot = r.choice(INDICATIONS)
        m = Molecule(f"{self.prefixe}-{self.numero}", ind, potentiel or pot * r.uniform(0.7, 1.3), phase)
        self.molecules.append(m)
        return m

    # ------------------------------------------------------------ probabilités et valeur
    def proba(self, i: int) -> float:
        e = self.e
        return min(0.95, PHASES[i][3] * (0.75 + e.qualite / 200) + e.bonus("succes"))

    def proba_approbation(self, m: Molecule) -> float:
        p = 1.0
        for i in range(m.phase, 5):
            p *= self.proba(i)
        return p

    def rnpv(self, m: Molecule) -> float:
        """Valeur actuelle ajustée du risque d'une molécule."""
        if m.statut in ("echec", "abandonne"):
            return 0.0
        franchise = m.potentiel * 0.6 * (1 + self.e.bonus("brevets"))
        if m.statut == "commercialise" or m.phase >= 5:
            v = franchise
        else:
            p, mois, couts = 1.0, 0.0, 0.0
            for i in range(m.phase, 5):
                _, duree, cout, _, _ = PHASES[i]
                reste = duree * (1 - m.avancement) if i == m.phase else duree
                couts += p * reste * cout
                mois += reste
                p *= self.proba(i)
            v = franchise * p * 0.9 ** (mois / 12)
            if m.statut != "licencie":
                v -= couts
        if m.statut == "licencie":
            v = max(0.0, v) * 0.3 + (m.jalon * max(0, 4 - m.phase) * 0.5 if m.phase < 5 else 0.0)
        return max(0.0, v)

    def pipeline(self) -> float:
        return sum(self.rnpv(m) for m in self.molecules)

    def ajuster_valeur(self, ev):
        return max(ev, self.pipeline())

    def levee_possible(self):
        return len(self.e.mois_reels()) >= 2 and self.pipeline() > 0

    def phare(self) -> Molecule | None:
        vivantes = [m for m in self.molecules if m.statut not in ("echec", "abandonne")]
        return max(vivantes, key=lambda m: (m.phase, m.avancement), default=None)

    # ------------------------------------------------------------ un mois
    def capacite(self) -> float:
        e = self.e
        return (1 + sum(x.capa() for x in e.equipe)) * e.capa_mult * (0.75 + e.moral / 400)

    def besoin_personnel(self) -> float:
        return sum(PHASES[m.phase][4] for m in self.molecules if m.statut == "actif" and m.phase < 5)

    def exploiter(self, demande, mois_cal, t, marche):
        e, r = self.e, self.e.rng
        msgs = []
        besoin = self.besoin_personnel()
        capa = self.capacite()
        ratio = min(1.0, capa / besoin) if besoin else 1.0
        vitesse = (1 + e.bonus("vitesse")) * (0.6 if marche.confinement else 1.0)
        cout = 0.0
        for m in list(self.molecules):
            if m.statut == "actif" and m.phase < 5:
                nom, duree, c, _, _ = PHASES[m.phase]
                cout += c * (1.6 if m.accelere else 1.0) * e.ops_mult
                m.avancement += ratio * vitesse * (1.5 if m.accelere else 1.0) / duree
                if m.avancement >= 1:
                    msgs += self.resultat_phase(m, t)
            elif m.statut == "licencie" and m.phase < 5:
                m.avancement += 1 / PHASES[m.phase][1]
                if m.avancement >= 1:
                    msgs += self.resultat_phase(m, t)
            elif m.statut in ("commercialise", "licencie") and m.phase >= 5:
                m.mois_vente += 1
                ventes = m.potentiel / 12 * min(1.0, m.mois_vente / 24) * r.uniform(0.9, 1.1)
                if m.statut == "licencie":
                    e.vendre(ventes * m.royalties, t)
                else:
                    e.vendre(ventes, t)
                    e.acheter(ventes * 0.12, t)
                    cout += ventes * 0.10                    # force de vente, pharmacovigilance
        e.charge("operations", cout, "charges")
        self.cout_mois = cout
        # recherche : de nouvelles molécules sortent du laboratoire
        p = (0.03 + 0.05 * math.log1p(e.qinv / 100_000)) * (1 + e.bonus("decouverte"))
        if r.random() < p:
            m = self.nouvelle_molecule(0)
            msgs.append(f"🔬 Votre recherche découvre une nouvelle molécule : {m.nom} ({m.indication}), en "
                        "préclinique.")
        for m in self.molecules:
            if m.recherche_partenaire and m not in self.offres and m.statut == "actif":
                m.recherche_partenaire = False
                if r.random() < 0.5 + e.notoriete / 200:
                    self.offres.append(m)
        if not any(m.en_clinique for m in self.molecules) and any(m.statut == "echec" and m.phase >= 1
                                                                  for m in self.molecules):
            self.faillite = True
        return {"ventes": 0.0, "capacite": capa, "utilisation": besoin / capa if capa else 0.0, "manques": 0.0,
                "messages": msgs}

    def resultat_phase(self, m: Molecule, t: int) -> list[str]:
        e, r = self.e, self.e.rng
        nom_phase, duree, cout, _, _ = PHASES[m.phase]
        p = self.proba(m.phase) if m.statut != "licencie" else min(0.95, PHASES[m.phase][3] * 1.1)
        m.avancement = 0.0
        m.accelere = False
        if r.random() < p:
            if m.statut == "licencie":
                e.vendre(m.jalon, t)
                txt = f"✅ {m.nom} ({m.indication}) réussit sa {nom_phase} chez {m.partenaire} : jalon de {fmt(m.jalon)}."
            else:
                sub = 0.10 * duree * cout if m.phase >= 1 else 0.0
                if sub:
                    e.produit("subventions", sub, "subventions")
                txt = (f"✅ Succès ! {m.nom} ({m.indication}) réussit sa {nom_phase}."
                       + (f" Bpifrance vous accorde {fmt(sub)} de subvention." if sub else ""))
            m.phase += 1
            e.notoriete = min(100.0, e.notoriete + (4 if m.phase <= 2 else 10))
            if m.phase >= 5:
                if m.statut != "licencie":
                    m.statut = "commercialise"
                txt += " Le médicament est autorisé : lancement commercial !"
            else:
                txt += f" Passage en {PHASES[m.phase][0]}."
                if m.statut == "actif" and m.phase in (2, 3) and r.random() < 0.6:
                    self.offres.append(m)
            return [txt]
        m.statut = "echec"
        e.notoriete = max(0.0, e.notoriete - 12)
        txt = f"❌ Échec : {m.nom} ({m.indication}) ne passe pas sa {nom_phase}. Le programme s'arrête."
        return [txt]

    # ------------------------------------------------------------ actions du joueur
    def accelerer(self, m: Molecule) -> str:
        if m.statut != "actif" or m.phase >= 5:
            return "Seul un essai en cours peut être accéléré."
        m.accelere = not m.accelere
        return (f"{m.nom} : essai accéléré (plus de centres cliniques) — 50 % plus rapide, 60 % plus cher."
                if m.accelere else f"{m.nom} : l'essai revient à son rythme normal.")

    def pause(self, m: Molecule) -> str:
        if m.statut == "actif" and m.phase < 5:
            m.statut = "pause"
            return f"{m.nom} mis en pause : plus aucune dépense, mais le programme n'avance plus."
        if m.statut == "pause":
            m.statut = "actif"
            return f"{m.nom} reprend."
        return "Impossible pour ce programme."

    def abandonner(self, m: Molecule) -> str:
        if m.statut not in ("actif", "pause"):
            return "Impossible pour ce programme."
        m.statut = "abandonne"
        return f"{m.nom} abandonné : ses dépenses s'arrêtent."

    def chercher_partenaire(self, m: Molecule) -> str:
        if m.statut != "actif" or m.phase < 1 or m.phase >= 5:
            return "Seule une molécule en clinique, que vous développez vous-même, peut être licenciée."
        m.recherche_partenaire = True
        return f"Vos équipes démarchent les grands laboratoires pour {m.nom} : réponse le mois prochain."

    def offre_licence(self, m: Molecule) -> dict:
        e, r = self.e, self.e.rng
        upfront = round(self.rnpv(m) * r.uniform(0.3, 0.45) * (0.8 + e.notoriete / 250) / 100_000) * 100_000
        upfront = max(500_000, upfront)
        return {"partenaire": r.choice(LABORATOIRES), "upfront": upfront, "royalties": 0.12,
                "jalon": round(upfront * 0.4 / 100_000) * 100_000}

    def evenement(self, marche):
        if not self.offres:
            return None
        m = self.offres.pop(0)
        if m.statut != "actif":
            return None
        o = self.offre_licence(m)
        return {"cle": "act_licence", "titre": f"{o['partenaire']} veut licencier {m.nom}",
                "texte": f"Le laboratoire {o['partenaire']} propose de reprendre le développement de {m.nom} "
                         f"({m.indication}, en {m.libelle_phase}) : {fmt(o['upfront'])} tout de suite, "
                         f"{fmt(o['jalon'])} à chaque étape réussie et {o['royalties']:.0%} de royalties sur les "
                         "ventes. Il paie tous les essais restants, mais vous renoncez à l'essentiel de la valeur "
                         "si le médicament réussit.".replace("%", " %"),
                "choix": ("Signer la licence", "Garder la molécule"), "molecule": m, "offre": o}

    def resoudre(self, ev, oui, marche):
        m, o = ev["molecule"], ev["offre"]
        if not oui or m.statut != "actif":
            return f"Vous gardez {m.nom} : à vous les risques… et la valeur."
        self.signer_licence(m, o, len(self.e.historique))
        return f"Licence signée avec {o['partenaire']} : {fmt(o['upfront'])} encaissés, les essais de {m.nom} sont à sa charge."

    def signer_licence(self, m: Molecule, o: dict, t: int) -> None:
        m.statut, m.partenaire, m.royalties, m.jalon = "licencie", o["partenaire"], o["royalties"], o["jalon"]
        m.accelere = False
        self.e.vendre(o["upfront"], t)

    def fusion_niche(self, f):
        m = self.nouvelle_molecule(phase=1)
        return f"sa molécule {m.nom} ({m.indication}, en Phase 1)"

    # ------------------------------------------------------------ concurrents
    def decider_ia(self, marche, force):
        e, st, r = self.e, self.e.strategie, self.e.rng
        if self.offres:
            m = self.offres.pop(0)
            envie = {"lowcost": 0.8, "equilibre": 0.5, "premium": 0.3, "startup": 0.2}[st.cle]
            if m.statut == "actif" and r.random() < envie:
                self.signer_licence(m, self.offre_licence(m), len(e.historique))
        cap = self.capacite()
        if self.besoin_personnel() > cap and e.tresorerie > 12 * e.s.salaire:
            e.recruter()
        brule = max(1.0, self.cout_mois + e.charges_fixes() + e.mkt + e.qinv)
        for m in self.molecules:
            if m.statut == "actif" and m.phase < 5:
                m.accelere = st.cle == "startup" and e.tresorerie > 20 * brule

    def budgets_ia(self, force):
        st = self.e.strategie
        q = {"lowcost": 40_000, "equilibre": 100_000, "premium": 180_000, "startup": 150_000}[st.cle] * force
        mk = {"lowcost": 10_000, "equilibre": 20_000, "premium": 25_000, "startup": 40_000}[st.cle] * force
        if self.e.tresorerie < 4 * max(1.0, self.cout_mois + self.e.charges_fixes()):
            q, mk = q * 0.3, mk * 0.3
        return mk, q

    def metriques(self):
        m = self.phare()
        return {"pipeline": self.pipeline(), "phase": (m.phase + m.avancement) if m else 0.0}

    def kpis(self):
        e = self.e
        m = self.phare()
        reels = e.mois_reels()
        brule = self.cout_mois + e.charges_fixes() + e.mkt + e.qinv
        autonomie = (e.tresorerie + e.placements) / brule if brule > 0 else 99
        k1 = {"titre": "Molécule phare", "valeur": f"{m.nom} · {m.libelle_phase}" if m else "Aucune",
              "detail": (f"{m.avancement:.0%} · succès ≈ {self.proba(m.phase):.0%}".replace("%", " %")
                         if m and m.phase < 5 else "sur le marché" if m else ""),
              "serie": [h.get("kpi", {}).get("phase", 0.0) for h in reels], "couleur": None}
        k2 = {"titre": "Autonomie de trésorerie", "valeur": f"{max(0.0, autonomie):.0f} mois",
              "detail": f"pipeline ≈ {fmt_c(self.pipeline())}",
              "serie": [h.get("kpi", {}).get("pipeline", 0.0) for h in reels],
              "couleur": ROUGE_K if autonomie < 6 else VERT_K if autonomie > 12 else None}
        return [k1, k2]

    def jauge(self):
        m = self.phare()
        v = m.avancement * 100 if m and m.phase < 5 else 100.0
        return "Essai en cours", v, f"{v:.0f} %", False

    def resume(self):
        m = self.phare()
        return f"{m.nom} en {m.libelle_phase}" if m else "Pipeline vide"

    def conseils(self):
        e = self.e
        c = []
        brule = self.cout_mois + e.charges_fixes() + e.mkt + e.qinv
        autonomie = (e.tresorerie + e.placements) / brule if brule > 0 else 99
        if autonomie < 9:
            c.append(f"Plus que {autonomie:.0f} mois de trésorerie : levez des fonds maintenant (page Banque), "
                     "avant d'être à court.")
        cliniques = [m for m in self.molecules if m.en_clinique]
        if len(cliniques) == 1 and cliniques[0].statut == "actif":
            c.append("Une seule molécule en clinique : si son essai échoue, c'est la faillite. Diversifiez "
                     "(recherche, rachat d'une biotech).")
        if self.besoin_personnel() > self.capacite():
            c.append("Pas assez de chercheurs pour mener tous vos essais : ils prennent du retard. Recrutez.")
        return c


# ---------------------------------------------------------------- jeu vidéo
ENVERGURES = {"inde": ("Indé", 70, 20, 1.0), "aa": ("AA", 260, 40, 2.8), "aaa": ("AAA", 900, 70, 7.0)}
TITRES_JEUX = ["Les Brumes d'Aldaïr", "Néon Samouraï", "Station Kepler", "Le Dernier Phare", "Cendres & Couronnes",
               "Rift Runner", "Petit Jardin", "Mécha Cantine", "Arcadia 2099", "Les Voleurs d'Étoiles", "Marée Creuse",
               "Tempête sur Ys", "Chroniques de Vellum", "Hyperloop Heist", "La Forêt qui chante", "Orbite Zéro"]
EDITEURS = ["Nébula Publishing", "Hexagone Games", "Pangée Interactive", "Studio Voltaire Édition"]


@dataclass
class Jeu:
    nom: str
    envergure: str
    charge: float                   # travail total, en personnes-mois
    avancement: float = 0.0
    qualite: float = 50.0
    wishlists: float = 0.0
    statut: str = "dev"             # dev, sorti
    note: float = 0.0
    lancement: float = 0.0          # copies vendues le mois de la sortie
    ventes_total: float = 0.0
    ventes_mois: float = 0.0
    mois_depuis: int = 0
    prix: float = 0.0
    lancer: bool = False
    editeur: dict | None = None     # {nom, avance, restant}
    date_sortie: str = ""

    @property
    def libelle(self) -> str:
        return ENVERGURES[self.envergure][0]


def note_attendue(qualite: float, avancement: float) -> float:
    return max(15.0, min(97.0, qualite * (0.55 + 0.45 * min(1.0, avancement)) - max(0.0, 1 - avancement) * 60))


def conversion(note: float) -> float:
    return 0.04 if note < 50 else 0.06 + 0.40 * ((note - 50) / 45) ** 1.5


class ActiviteJeu(Activite):
    partage = False
    unite_capacite = "personnes-mois par mois (développement)"

    def __init__(self, e):
        super().__init__(e)
        self.projet: Jeu | None = None
        self.catalogue: list[Jeu] = []
        self.titres = list(TITRES_JEUX)
        e.rng.shuffle(self.titres)
        self.nouveau_projet("inde")

    def nouveau_projet(self, envergure: str) -> str:
        if self.projet:
            return "Un projet est déjà en cours."
        e = self.e
        nom = self.titres.pop(0) if self.titres else f"Projet {len(self.catalogue) + 1}"
        lib, charge, prix, portee = ENVERGURES[envergure]
        fans = sum(j.ventes_total for j in self.catalogue) * 0.12 + e.notoriete * 80
        self.projet = Jeu(nom, envergure, float(charge), qualite=45 + e.qualite * 0.15, wishlists=fans)
        duree = charge / max(1.0, self.capacite())
        return (f"Nouveau projet : « {nom} » ({lib}), environ {fmt_n(charge)} personnes-mois de travail, soit "
                f"≈ {duree:.0f} mois avec votre équipe actuelle. Prix conseillé : {prix} €.")

    def capacite(self) -> float:
        e = self.e
        penurie = 0.6 if e.penurie > 0 else 1.0
        return (1 + sum(x.capa() for x in e.equipe)) * e.capa_mult * (0.75 + e.moral / 400) * penurie

    def preparer(self):
        e, p = self.e, self.projet
        if not p:
            return
        p.avancement += self.capacite() / p.charge
        trop_gros = p.charge / max(1.0, self.capacite()) > 30
        p.qualite += (1.4 * math.log1p(e.qinv / (1_500 * e.s.echelle)) + 0.6 * e.effet("qualite") + e.bonus("polish")
                      + (e.moral - 60) / 60 - 0.4 - (0.6 if trop_gros else 0.0))
        p.qualite = max(0.0, min(100.0, p.qualite))
        portee = ENVERGURES[p.envergure][3]
        gain = (1_400 * math.log1p(e.mkt * e.mkt_mult * (1 + e.effet("mkt")) / 5_000) * (0.4 + e.notoriete / 60)
                * portee * (1.0 if p.avancement > 0.25 else 0.4) * (1.3 if p.editeur else 1.0))
        p.wishlists = p.wishlists * 0.99 + gain

    def demander_lancement(self) -> str:
        p = self.projet
        if not p:
            return "Aucun jeu en développement."
        if p.avancement < 0.8:
            return f"« {p.nom} » n'est avancé qu'à {p.avancement:.0%} : il faut au moins 80 % pour sortir.".replace("%", " %")
        p.lancer = True
        return (f"« {p.nom} » sortira à la fin du mois, au prix de {fmt(self.e.prix)}."
                + (" Attention : sorti avant la fin du développement, il sera buggé et la critique le sanctionnera."
                   if p.avancement < 1 else ""))

    def annuler_lancement(self) -> str:
        if self.projet:
            self.projet.lancer = False
        return "Sortie repoussée : l'équipe continue de peaufiner le jeu."

    def signer_editeur(self) -> str:
        e, p = self.e, self.projet
        if not p or p.editeur or p.avancement < 0.15:
            return "Un éditeur ne s'engage que sur un projet avancé d'au moins 15 %, sans éditeur."
        reste = p.charge * max(0.0, 1 - p.avancement) * e.s.salaire
        avance = max(50_000, round(0.6 * reste / 10_000) * 10_000)
        nom = e.rng.choice(EDITEURS)
        e.encaisser_avance(avance)
        p.editeur = {"nom": nom, "avance": avance, "restant": avance}
        return (f"Contrat signé avec {nom} : {fmt(avance)} d'avance tout de suite, et son marketing gonfle vos "
                "wishlists (+30 %). En échange, il prend 50 % des revenus du jeu jusqu'à rembourser son avance, "
                "puis 30 %.")

    def lancements_prevus(self) -> float:
        p = self.projet
        return ENVERGURES[p.envergure][3] if p and p.lancer else 0.0

    def exploiter(self, demande, mois_cal, t, marche):
        e, r, p = self.e, self.e.rng, self.projet
        msgs = []
        if p and p.lancer:
            lib, _, prix_ref, portee = ENVERGURES[p.envergure]
            note = max(15.0, min(97.0, note_attendue(p.qualite, p.avancement) + r.gauss(0, 6)))
            f_prix = max(0.3, min(2.0, (prix_ref / max(1.0, e.prix)) ** 1.3))
            organique = e.notoriete * 35 * portee * (note / 70) ** 2
            autres = marche.poids_lancements - portee
            f_conc = 1 / (1 + 0.2 * max(0.0, autres) / portee)
            f_conf = 1.3 if marche.confinement else 1.0
            ventes = ((p.wishlists * conversion(note) + organique) * f_prix * f_conc * marche.conjoncture
                      * e.portee * f_conf * r.uniform(0.85, 1.15))
            p.note, p.lancement, p.prix, p.statut, p.mois_depuis = note, ventes, e.prix, "sorti", 0
            p.date_sortie = marche.date()
            p.lancer = False
            self.catalogue.append(p)
            self.projet = None
            e.notoriete = max(0.0, min(100.0, e.notoriete + note / 6 - 6))
            verdict = ("un triomphe" if note >= 85 else "un succès" if note >= 72 else "un accueil mitigé"
                       if note >= 55 else "un flop")
            msgs.append(f"🎮 Sortie de « {p.nom} » : note de la critique {note:.0f}/100, {verdict}. "
                        f"{fmt_n(ventes)} copies vendues le premier mois.")
            if f_conc < 0.9:
                msgs.append("⚠ D'autres jeux sont sortis le même mois : les joueurs se sont dispersés.")
        copies, ca = 0.0, 0.0
        for j in self.catalogue:
            if j.mois_depuis == 0:
                v = j.lancement
            else:
                d = 0.35 + j.note / 200
                v = max(j.lancement * 0.02, j.lancement * d ** j.mois_depuis)
                if mois_cal in (5, 10, 11):
                    v *= 1.3                    # soldes d'été et de fin d'année
            j.mois_depuis += 1
            j.ventes_total += v
            j.ventes_mois = v
            montant = v * j.prix
            copies += v
            ca += montant
            if montant <= 0:
                continue
            e.vendre(montant, t)
            e.charge("operations", montant * 0.30, "charges")          # commission des plateformes
            if j.editeur:
                # l'éditeur récupère d'abord son avance (50 % des revenus nets), puis touche 30 % de redevances
                part = montant * 0.70 * (0.5 if j.editeur["restant"] > 0 else 0.3)
                rembourse = min(part, j.editeur["restant"])
                if rembourse:
                    j.editeur["restant"] -= rembourse
                    e.avances -= rembourse
                    e.mouvement(-rembourse, "fournisseurs")
                if part - rembourse > 0:
                    e.charge("achats", part - rembourse, "fournisseurs")
        return {"ventes": copies, "capacite": self.capacite(),
                "utilisation": (p.charge / 18) / max(1.0, self.capacite()) if p else 0.5, "manques": 0.0,
                "messages": msgs}

    def valeur_projet(self) -> float:
        p, e = self.projet, self.e
        if not p:
            return 0.0
        lib, _, prix_ref, portee = ENVERGURES[p.envergure]
        note = note_attendue(p.qualite, 1.0)
        lancement = p.wishlists * conversion(note) + e.notoriete * 35 * portee * (note / 70) ** 2
        vie = lancement * prix_ref * 3 * 0.7
        return vie * 0.35 * (0.3 + 0.7 * min(1.0, p.avancement))

    def ajuster_valeur(self, ev):
        return ev + self.valeur_projet()

    def levee_possible(self):
        return len(self.e.mois_reels()) >= 3 and (self.catalogue or (self.projet and self.projet.avancement >= 0.2))

    def decider_ia(self, marche, force):
        e, st = self.e, self.e.strategie
        if not self.projet:
            dernier = self.catalogue[-1] if self.catalogue else None
            env = "inde"
            if dernier and dernier.note >= 72 and st.cle != "lowcost":
                if dernier.envergure == "inde" and e.tresorerie > 1_200_000:
                    env = "aa"
                elif dernier.envergure in ("aa", "aaa") and e.tresorerie > 5_000_000:
                    env = "aaa"
                elif dernier.envergure == "aa":
                    env = "aa"
            self.nouveau_projet(env)
        p = self.projet
        cible = {"inde": 8, "aa": 20, "aaa": 45}[p.envergure]
        if len(e.equipe) + 1 < cible and e.tresorerie > 10 * e.s.salaire:
            e.recruter()
        seuil = {"lowcost": 0.9, "equilibre": 1.0, "premium": 1.12, "startup": 1.0}[st.cle]
        if p.avancement >= seuil:
            p.lancer = True
            e.prix = ENVERGURES[p.envergure][2] * st.prix
        if not p.editeur and p.avancement > 0.3 and e.tresorerie < 6 * e.charges_fixes() and st.cle != "premium":
            self.signer_editeur()

    def budgets_ia(self, force):
        e, st = self.e, self.e.strategie
        p = self.projet
        portee = ENVERGURES[p.envergure][3] if p else 1.0
        mk = {"lowcost": 6_000, "equilibre": 10_000, "premium": 12_000, "startup": 20_000}[st.cle] * portee * force
        q = {"lowcost": 3_000, "equilibre": 8_000, "premium": 15_000, "startup": 8_000}[st.cle] * portee ** 0.7 * force
        if p and p.avancement < 0.25:
            mk *= 0.3
        if e.tresorerie < 3 * e.charges_fixes():
            mk, q = mk * 0.4, q * 0.4
        return mk, q

    def metriques(self):
        p = self.projet
        return {"wishlists": p.wishlists if p else 0.0, "avancement": p.avancement if p else 0.0}

    def kpis(self):
        e, p = self.e, self.projet
        reels = e.mois_reels()
        if p:
            note = note_attendue(p.qualite, p.avancement)
            return [{"titre": "Wishlists", "valeur": fmt_n(p.wishlists),
                     "detail": f"conversion attendue ≈ {conversion(note):.0%}".replace("%", " %"),
                     "serie": [h.get("kpi", {}).get("wishlists", 0.0) for h in reels], "couleur": None},
                    {"titre": f"« {p.nom} »", "valeur": f"{min(p.avancement, 9.99):.0%}".replace("%", " %"),
                     "detail": f"{p.libelle} · note attendue ≈ {note:.0f}/100",
                     "serie": [h.get("kpi", {}).get("avancement", 0.0) for h in reels],
                     "couleur": VERT_K if p.avancement >= 1 else None}]
        dernier = self.catalogue[-1] if self.catalogue else None
        return [{"titre": "Ventes du mois", "valeur": fmt_n(sum(j.ventes_mois for j in self.catalogue)),
                 "detail": "copies, tous jeux confondus", "serie": [h["ventes"] for h in reels], "couleur": None},
                {"titre": "Dernier jeu", "valeur": f"{dernier.note:.0f}/100" if dernier else "—",
                 "detail": f"« {dernier.nom} » · {fmt_n(dernier.ventes_total)} copies" if dernier else "",
                 "serie": [], "couleur": None}]

    def jauge(self):
        p = self.projet
        if p:
            return "Qualité du jeu", p.qualite, f"{p.qualite:.0f}", False
        return "Qualité du jeu", 0.0, "—", False

    def resume(self):
        p = self.projet
        if p:
            return f"« {p.nom} » ({p.libelle}) à {min(p.avancement, 9.99):.0%}".replace("%", " %")
        return f"{len(self.catalogue)} jeu(x) sorti(s)"

    def conseils(self):
        p = self.projet
        c = []
        if not p:
            c.append("Aucun jeu en développement : lancez un nouveau projet (page Projets de jeux).")
            return c
        if p.avancement >= 1 and not p.lancer:
            c.append(f"« {p.nom} » est prêt : sortez-le (page Projets de jeux) quand vos wishlists sont au plus haut.")
        if p.avancement > 0.4 and p.wishlists < 20_000 * ENVERGURES[p.envergure][3]:
            c.append("Peu de wishlists : sans marketing, le lancement risque de faire un flop.")
        if note_attendue(p.qualite, 1.0) < 60:
            c.append("Note attendue faible : investissez dans le polish et les tests avant de sortir.")
        return c

    def fusion_niche(self, f):
        self.e.notoriete = min(100.0, self.e.notoriete + 5)
        if self.projet:
            self.projet.wishlists += f.ca * 2
        return "sa communauté de joueurs"


# ---------------------------------------------------------------- luxe
class ActiviteLuxe(Activite):
    unite_capacite = "pièces par mois"
    k_mkt, k_qual = 2.5, 1.0

    def __init__(self, e):
        super().__init__(e)
        self.exclusivite = 55.0
        self.quota = 0                # pièces mises en vente par mois (0 : toute la capacité)
        self.dernier_prix = e.prix
        self.attente = 0.0
        self.baisse = 0.0

    def pma(self) -> float:
        """Prix maximal acceptable par la clientèle : il monte avec la réputation et l'exclusivité."""
        e = self.e
        return (e.s.prix_ref * (0.75 + e.notoriete / 80) * (0.75 + self.exclusivite / 200)
                * (1 + e.bonus("pma")))

    def preparer(self):
        e = self.e
        self.baisse = 0.0
        if e.prix < self.dernier_prix * 0.99:
            self.baisse = 1 - e.prix / self.dernier_prix
            self.exclusivite = max(0.0, self.exclusivite - 250 * self.baisse)
            e.notoriete = max(0.0, e.notoriete - 120 * self.baisse)
        self.dernier_prix = e.prix

    def attrait(self):
        e, s = self.e, self.e.s
        pma = self.pma()
        f_prix = (e.prix / s.prix_ref) ** 0.15
        if e.prix > pma:
            f_prix *= math.exp(-5 * (e.prix / pma - 1))
        return ((0.3 + e.notoriete / 150) * (0.6 + self.exclusivite / 125) * (0.4 + e.qualite / 100) * f_prix
                * e.portee * (1 + min(0.4, e.effet("attrait"))))

    def exploiter(self, demande, mois_cal, t, marche):
        e = self.e
        capa = self.capacite()
        offre = min(capa, self.quota) if self.quota else capa
        ventes = min(demande, offre)
        self.attente = max(0.0, demande - ventes)
        if ventes > 0 and demande > ventes * 1.15:
            self.exclusivite += min(4.0, 3 * (demande / ventes - 1))     # liste d'attente : la rareté fait rêver
        elif demande <= offre:
            self.exclusivite -= 0.8                                       # tout le monde peut en avoir un
        part = e.historique[-1]["part"] if e.historique else 0.0
        if part > 0.35:
            self.exclusivite -= (part - 0.35) * 20                        # surexposition
        self.exclusivite -= 0.01 * (self.exclusivite - 50)
        self.exclusivite = max(0.0, min(100.0, self.exclusivite))
        e.vendre(ventes * e.prix, t)
        e.acheter(ventes * e.cout_unitaire, t)
        msgs = []
        if self.baisse and e.joueur:
            msgs.append(f"💔 Baisse de prix de {self.baisse:.0%} : la marque se banalise (exclusivité et réputation "
                        "en chute).".replace("%", " %"))
        return {"ventes": ventes, "capacite": capa, "utilisation": demande / capa if capa else 0.0,
                "manques": max(0.0, demande - offre) * 0.2, "messages": msgs}

    def ajuster_valeur(self, ev):
        e = self.e
        return ev * (0.4 + e.notoriete / 125) * (0.6 + self.exclusivite / 125)

    def decider_ia(self, marche, force):
        e, st = self.e, self.e.strategie
        pma = self.pma()
        h = e.historique[-1] if e.historique else None
        if st.cle == "lowcost":                   # « maison accessible » : baisse ses prix pour vendre plus
            if h and len(e.historique) % 4 == 0 and h["part"] < 1 / max(1, len(marche.actives)):
                e.prix = round(e.prix * 0.93, -1)
        elif h and self.attente > 0.2 * max(1.0, h["ventes"]) and e.prix < 0.92 * pma:
            e.prix = round(min(0.95 * pma, e.prix * 1.06), -1)
        elif e.prix > pma * 1.05:
            e.prix = round(pma * 0.98, -1)             # hors de prix : il faut redescendre, quitte à abîmer la marque
        if st.cle == "premium":
            self.quota = int(self.capacite() * 0.85)
        if h and h["utilisation"] > 1.1 and e.tresorerie > 8 * e.s.salaire and (st.cle != "premium"
                                                                                 or h["utilisation"] > 1.6):
            e.recruter()

    def metriques(self):
        return {"exclusivite": self.exclusivite, "pma": self.pma()}

    def kpis(self):
        e = self.e
        reels = e.mois_reels()
        pma = self.pma()
        return [{"titre": "Indice d'exclusivité", "valeur": f"{self.exclusivite:.0f}/100",
                 "detail": f"liste d'attente : {fmt_n(self.attente)} pièce(s)",
                 "serie": [h.get("kpi", {}).get("exclusivite", 0.0) for h in reels],
                 "couleur": VERT_K if self.exclusivite >= 60 else ROUGE_K if self.exclusivite < 35 else None},
                {"titre": "Prix maximal accepté", "valeur": fmt(pma),
                 "detail": f"votre prix : {e.prix / pma:.0%} du plafond".replace("%", " %"),
                 "serie": [h.get("kpi", {}).get("pma", 0.0) for h in reels],
                 "couleur": ROUGE_K if e.prix > pma else None}]

    def jauge(self):
        return "Exclusivité", self.exclusivite, f"{self.exclusivite:.0f}", False

    def resume(self):
        return f"Exclusivité {self.exclusivite:.0f} · plafond {fmt_c(self.pma())}"

    def conseils(self):
        e = self.e
        c = []
        pma = self.pma()
        if e.prix > pma:
            c.append(f"Votre prix dépasse ce que la clientèle accepte ({fmt(pma)}) : les ventes s'effondrent.")
        elif self.attente >= 3 and e.prix < pma * 0.9:
            c.append(f"Liste d'attente de {fmt_n(self.attente)} pièces : vous pouvez monter vos prix jusqu'à "
                     f"≈ {fmt(pma)}.")
        if self.exclusivite < 40:
            c.append("Exclusivité en berne : limitez les volumes (quota, page La maison) et ne baissez jamais vos prix.")
        return c

    def evenement(self, marche):
        e, r = self.e, self.e.rng
        if len(e.historique) < 4 or r.random() > 0.06:
            return None
        if r.random() < 0.5:
            gain = r.choice([8, 12, 18])
            e.notoriete = min(100.0, e.notoriete + gain)
            return {"cle": "act_star", "titre": "Une star porte votre création",
                    "texte": f"Une actrice célèbre apparaît sur un tapis rouge avec une de vos pièces. "
                             f"Réputation +{gain}.", "choix": None}
        montant = round(e.capacite() * e.prix * 1.5 / 10_000) * 10_000
        return {"cle": "act_destockage", "titre": "Proposition de ventes privées",
                "texte": f"Un site de ventes privées propose de racheter vos invendus et collections passées à −60 % : "
                         f"{fmt(montant)} de trésorerie tout de suite. Mais votre maison apparaîtrait à prix cassés.",
                "choix": ("Accepter", "Refuser"), "montant": montant}

    def resoudre(self, ev, oui, marche):
        e = self.e
        if ev["cle"] != "act_destockage":
            return ""
        if not oui:
            return "Vous refusez : la marque reste intacte."
        e.vendre(ev["montant"], len(e.historique))
        e.acheter(ev["montant"] * 0.4, len(e.historique))
        self.exclusivite = max(0.0, self.exclusivite - 25)
        e.notoriete = max(0.0, e.notoriete - 10)
        return f"Ventes privées : {fmt(ev['montant'])} encaissés, mais exclusivité −25 et réputation −10."


# ---------------------------------------------------------------- aéronautique et spatial
CLIENTS_AERO = ["Consortium Aérien Européen", "Agence spatiale Europa", "Constellation Orion", "Hélios Défense",
                "Lanceurs Atlantique", "Avionneur Dassel", "Opérateur SatCom Nova", "Agence de l'armement"]
PRODUCTIVITE_AERO = 40_000      # chiffre d'affaires produit par personne-mois de travail
OBJETS_AERO = [("Structure de lanceur", 1.0), ("Satellite d'observation", 1.4), ("Système de propulsion", 1.2),
               ("Radôme et antennes", 0.6), ("Harnais électriques", 0.4), ("Tuyères composites", 0.8),
               ("Module de service orbital", 1.3), ("Équipements de cabine", 0.5)]


@dataclass
class Contrat:
    client: str
    objet: str
    montant: float
    charge: float                   # personnes-mois de travail
    debut: int
    echeance: int                   # mois (numéro) de livraison prévu
    avancement: float = 0.0
    a_facturer: float = 0.0         # travail fait, pas encore facturé
    avance: float = 0.0             # acompte restant à imputer
    jalons: int = 0
    penalites: float = 0.0
    livre: bool = False


@dataclass
class AppelOffres:
    ident: int
    client: str
    objet: str
    montant: float
    charge: float
    duree: int
    decision: int                   # mois où le client choisit
    exigence: float                 # crédibilité technique minimale
    offres: dict = field(default_factory=dict)   # nom d'entreprise → prix proposé
    gagnant: str = ""


class ActiviteAero(Activite):
    partage = False
    unite_capacite = "personnes-mois par mois"

    def __init__(self, e):
        super().__init__(e)
        self.contrats: list[Contrat] = []
        self.penalites = 0.0
        self.charge_mois = 0.0
        # un premier contrat d'étude, signé à la création
        c = Contrat("Agence spatiale Europa", "Étude de faisabilité", 5_000_000, 5_000_000 / PRODUCTIVITE_AERO, 0, 16)
        self.signer(c)

    def signer(self, c: Contrat) -> None:
        acompte = round(c.montant * 0.2)
        c.avance = acompte
        self.e.encaisser_avance(acompte)
        self.contrats.append(c)

    def capacite(self) -> float:
        e = self.e
        penurie = 0.6 if e.penurie > 0 else 1.0
        return (1 + sum(x.capa() for x in e.equipe)) * e.capa_mult * (0.75 + e.moral / 400) * penurie

    def actifs(self) -> list[Contrat]:
        return [c for c in self.contrats if not c.livre]

    def carnet(self) -> float:
        return sum(c.montant * (1 - c.avancement) for c in self.actifs())

    def besoins(self, t: int) -> dict:
        return {id(c): c.charge * (1 - c.avancement) / max(1, c.echeance - t) for c in self.actifs()}

    def charge_prevue(self, t: int) -> float:
        return sum(self.besoins(t).values())

    def fixes(self) -> float:
        return self.e.s.cout_fixe_ops * self.e.ops_mult

    def exploiter(self, demande, mois_cal, t, marche):
        e = self.e
        msgs = []
        capa = self.capacite()
        besoins = self.besoins(t)
        total = sum(besoins.values())
        ratio = min(1.25, capa / total) if total else 0.0
        materiaux = 0.30 * e.cout_unitaire
        for c in self.actifs():
            delta = min(1 - c.avancement, besoins[id(c)] * ratio / c.charge)
            if delta <= 0:
                continue
            rev = delta * c.montant
            e.produit("ca", rev)
            impute = min(c.avance, rev * 0.2)
            c.avance -= impute
            e.avances -= impute
            e.encours += rev - impute
            c.a_facturer += rev - impute
            e.acheter(rev * materiaux, t)
            c.avancement += delta
            jalons = int(c.avancement * 4 + 1e-9)
            fini = c.avancement >= 1 - 1e-6
            if jalons > c.jalons or fini:
                if fini and c.avance > 0:             # reliquat d'acompte : imputé sur la dernière facture
                    e.avances -= c.avance
                    e.encours -= c.avance
                    c.a_facturer -= c.avance
                    c.avance = 0.0
                if c.a_facturer > 0:
                    e.encours -= c.a_facturer
                    e.creances.append([t + e.delai_clients // 30, c.a_facturer, 0.0])
                    if e.joueur and not fini:
                        msgs.append(f"🧾 Jalon {jalons}/4 atteint sur « {c.objet} » : {fmt(c.a_facturer)} facturés à "
                                    f"{c.client}.")
                c.a_facturer = 0.0
                c.jalons = jalons
            if fini:
                c.livre = True
                c.avancement = 1.0
                a_temps = t <= c.echeance
                e.notoriete = min(100.0, e.notoriete + (5 if a_temps else 1))
                msgs.append(f"📦 « {c.objet} » livré à {c.client}" + (" dans les temps." if a_temps else
                                                                       f", avec {t - c.echeance} mois de retard."))
        for c in self.actifs():                        # pénalités de retard
            if t > c.echeance and c.penalites < 0.15 * c.montant:
                pen = min(0.015 * c.montant, 0.15 * c.montant - c.penalites)
                c.penalites += pen
                self.penalites += pen
                e.charge("operations", pen, "charges")
                e.notoriete = max(0.0, e.notoriete - 0.5)
                if e.joueur:
                    msgs.append(f"⚠ Retard sur « {c.objet} » : {fmt(pen)} de pénalités ce mois-ci.")
        e.charge("operations", self.fixes(), "charges")
        self.charge_mois = total / capa if capa else 0.0
        return {"ventes": sum(1 for c in self.contrats if c.livre), "capacite": capa,
                "utilisation": self.charge_mois, "manques": 0.0, "messages": msgs}

    def ajuster_valeur(self, ev):
        return ev + 0.12 * self.carnet()

    def levee_possible(self):
        return len(self.e.mois_reels()) >= 3

    def score_offre(self, ao: AppelOffres, prix: float, t: int, rng: random.Random) -> float:
        e = self.e
        charge = self.charge_prevue(t) + ao.charge / ao.duree
        f_charge = 1.0 if charge <= 1.2 * self.capacite() else 0.75
        return ((ao.montant / prix) ** 3 * (0.5 + e.qualite / 100) * (0.6 + e.notoriete / 150) * f_charge
                * (1 + min(0.3, e.effet("attrait"))) * rng.uniform(0.9, 1.1))

    def decider_ia(self, marche, force):
        e = self.e
        if self.charge_mois > 1.05 and e.tresorerie > 8 * e.s.salaire:
            e.recruter()

    def budgets_ia(self, force):
        st = self.e.strategie
        mk = {"lowcost": 25_000, "equilibre": 40_000, "premium": 50_000, "startup": 70_000}[st.cle] * force
        q = {"lowcost": 30_000, "equilibre": 50_000, "premium": 90_000, "startup": 60_000}[st.cle] * force
        if self.e.tresorerie < 3 * self.e.charges_fixes():
            mk, q = mk * 0.4, q * 0.4
        return mk, q

    def metriques(self):
        return {"carnet": self.carnet(), "charge": self.charge_mois}

    def kpis(self):
        e = self.e
        reels = e.mois_reels()
        carnet = self.carnet()
        cout_mois = max(1.0, e.charges_fixes())
        mois = carnet * 0.45 / cout_mois
        return [{"titre": "Carnet de commandes", "valeur": fmt_c(carnet),
                 "detail": f"{len(self.actifs())} contrat(s) en cours",
                 "serie": [h.get("kpi", {}).get("carnet", 0.0) for h in reels],
                 "couleur": ROUGE_K if mois < 6 else None},
                {"titre": "Charge / capacité", "valeur": f"{self.charge_mois:.0%}".replace("%", " %"),
                 "detail": f"pénalités : {fmt_c(self.penalites)}",
                 "serie": [h.get("kpi", {}).get("charge", 0.0) for h in reels],
                 "couleur": ROUGE_K if self.charge_mois > 1.05 else None}]

    def jauge(self):
        v = self.charge_mois * 100
        return "Charge / capacité", v, f"{v:.0f} %", True

    def resume(self):
        return f"Carnet {fmt_c(self.carnet())} · charge {self.charge_mois:.0%}".replace("%", " %")

    def conseils(self):
        e = self.e
        c = []
        if self.charge_mois > 1.05:
            c.append(f"Charge à {self.charge_mois:.0%} de la capacité : vos contrats vont prendre du retard "
                     "(pénalités). Recrutez.".replace("%", " %"))
        if self.carnet() < 6 * e.charges_fixes() / 0.45:
            c.append("Carnet de commandes mince : répondez aux appels d'offres (page Contrats).")
        return c

    def fusion_niche(self, f):
        self.e.notoriete = min(100.0, self.e.notoriete + 8)
        return "sa crédibilité technique (+8)"


# ---------------------------------------------------------------- grande distribution
class ActiviteDistribution(Activite):
    unite_capacite = "commandes par mois"
    k_mkt, k_qual = 0.4, 0.3

    def __init__(self, e):
        super().__init__(e)
        self.jours_cible = 20
        self.demande_prec = 0.0
        self.rupture = 0.0
        self.defaut = 0                 # mois pendant lesquels les fournisseurs exigent d'être payés comptant
        self.impayes = 0

    def cout_commande(self) -> float:
        e = self.e
        delai = 0 if self.defaut else e.delai_fournisseurs
        return e.cout_unitaire * DELAIS_FOURN[delai]

    def exploiter(self, demande, mois_cal, t, marche):
        e, s, r = self.e, self.e.s, self.e.rng
        msgs = []
        cmv = self.cout_commande()
        capa = self.capacite()
        base = self.demande_prec or min(capa, demande) * r.uniform(0.9, 1.1)
        prevision = base * s.saison[mois_cal] / s.saison[(mois_cal - 1) % 12]
        prevision *= 1 + r.gauss(0, 0.10 * (1 - e.bonus("prevision")))
        cible = max(0.0, prevision) * cmv * (1 + self.jours_cible / 30)
        achat = max(0.0, cible - e.stocks)
        if self.defaut:
            achat *= 0.7                                  # fournisseurs méfiants : livraisons rationnées
        e.acheter_stock(achat, t, comptant=bool(self.defaut))
        dispo = e.stocks / cmv if cmv else 0.0
        ventes = min(demande, capa, dispo)
        self.rupture = max(0.0, min(demande, capa) - ventes) / demande if demande else 0.0
        e.consommer_stock(min(e.stocks, ventes * cmv))
        e.vendre(ventes * e.prix, t)
        e.charge("operations", ventes * 6 * e.ops_mult + e.stocks * 0.012 + s.cout_fixe_ops * e.ops_mult,
                 "charges")
        self.demande_prec = demande
        if self.rupture > 0.03 and e.joueur:
            msgs.append(f"⚠ Ruptures de stock : {self.rupture:.0%} des commandes n'ont pas pu être servies."
                        .replace("%", " %"))
        if self.defaut:
            self.defaut -= 1
        return {"ventes": ventes, "capacite": capa, "utilisation": demande / capa if capa else 0.0,
                "manques": max(0.0, demande - ventes), "messages": msgs}

    def payer_fournisseurs(self, t):
        """Si la trésorerie ne suit pas, la facture n'est payée qu'en partie : pénalité de retard et fournisseurs
        qui exigent ensuite d'être payés comptant."""
        e = self.e
        a_payer = []
        for d in e.dettes_fourn:
            if d[0] > t:
                a_payer.append(d)
                continue
            dispo = e.tresorerie + e.decouvert_autorise()
            if d[1] <= dispo:
                e.mouvement(-d[1], "fournisseurs")
                continue
            paye = max(0.0, dispo)
            if paye:
                e.mouvement(-paye, "fournisseurs")
            reste = d[1] - paye
            penalite = reste * 0.03
            e.comptabiliser("charges_fin", penalite)
            a_payer.append([t + 1, reste + penalite])
            if not self.defaut:
                self.impayes += 1
                e.incidents += 1
                e.periode["details"].append(("Impayé fournisseur", 0.0))
            self.defaut = 3
        e.dettes_fourn = a_payer
        return True

    def jours_stock(self) -> float:
        h = self.e.historique[-1] if self.e.historique else None
        cmv = h["pl"]["achats"] if h and "pl" in h else 0.0
        return self.e.stocks / cmv * 30 if cmv else 0.0

    def metriques(self):
        return {"rotation": self.jours_stock(), "rupture": self.rupture}

    def kpis(self):
        e = self.e
        reels = e.mois_reels()
        return [{"titre": "Rotation des stocks", "valeur": f"{self.jours_stock():.0f} jours",
                 "detail": f"stock {fmt_c(e.stocks)} · cible {self.jours_cible} j",
                 "serie": [h.get("kpi", {}).get("rotation", 0.0) for h in reels], "couleur": None},
                {"titre": "Ruptures de stock", "valeur": f"{self.rupture * 100:.1f} %".replace(".", ","),
                 "detail": (f"fournisseurs à {0 if self.defaut else e.delai_fournisseurs} j"
                            + (" · sous surveillance" if self.defaut else "")),
                 "serie": [h.get("kpi", {}).get("rupture", 0.0) for h in reels],
                 "couleur": ROUGE_K if self.rupture > 0.03 or self.defaut else VERT_K}]

    def jauge(self):
        v = (1 - self.rupture) * 100
        return "Taux de service", v, f"{v:.0f} %", False

    def resume(self):
        return f"Stock {self.jours_stock():.0f} j · ruptures {self.rupture:.0%}".replace("%", " %")

    def decider_ia(self, marche, force):
        super().decider_ia(marche, force)
        self.jours_cible = {"lowcost": 12, "equilibre": 20, "premium": 28, "startup": 18}[self.e.strategie.cle]

    def conseils(self):
        c = []
        if self.rupture > 0.03:
            c.append("Ruptures de stock : augmentez votre stock cible (page Stocks et logistique).")
        if self.jours_stock() > 40:
            c.append(f"{self.jours_stock():.0f} jours de stock : trop d'argent immobilisé et de frais de stockage.")
        if self.defaut:
            c.append("Impayé fournisseur : ils exigent d'être payés comptant, votre trésorerie va souffrir.")
        return c


# ---------------------------------------------------------------- énergie
SAISON_SOLAIRE = [0.45, 0.6, 0.9, 1.15, 1.35, 1.45, 1.5, 1.35, 1.05, 0.75, 0.5, 0.4]
SAISON_EOLIEN = [1.3, 1.25, 1.15, 1.0, 0.85, 0.75, 0.7, 0.75, 0.9, 1.1, 1.2, 1.3]
# type : (libellé, MW, investissement, mois de travaux, facteur de charge, saison, exploitation par mois)
TYPES_CENTRALE = {
    "solaire": ("Parc solaire", 40.0, 28_000_000, 6, 0.14, SAISON_SOLAIRE, 40_000),
    "eolien": ("Parc éolien", 30.0, 39_000_000, 10, 0.26, SAISON_EOLIEN, 90_000),
    "stockage": ("Stockage par batteries", 20.0, 14_000_000, 5, 0.0, [1.0] * 12, 25_000),
}
LIEUX = ["de la Beauce", "des Causses", "du Cotentin", "de Camargue", "des Landes", "du Vexin", "de la Crau",
         "du Lauragais", "des Monts d'Arrée", "de Champagne", "du Quercy", "de Sologne"]


@dataclass
class Centrale:
    nom: str
    type: str
    mw: float
    capex: float
    etat: str = "travaux"           # travaux, service
    travaux: int = 6
    ppa_prix: float | None = None   # prix garanti (€/MWh) ; None : vente au prix du marché
    ppa_fin: int = 0
    production: float = 0.0
    revenu: float = 0.0


@dataclass
class ProjetEnergie:
    nom: str
    type: str


class ActiviteEnergie(Activite):
    partage = False
    unite_capacite = "—"

    def __init__(self, e):
        super().__init__(e)
        self.lieux = list(LIEUX)
        e.rng.shuffle(self.lieux)
        lib, mw, capex, travaux, *_ = TYPES_CENTRALE["solaire"]
        self.centrales = [Centrale(f"{lib} {self.lieux.pop(0)}", "solaire", mw, e.s.installation, "travaux", travaux)]
        e.immos[-1]["libelle"] = self.centrales[0].nom
        self.projets: list[ProjetEnergie] = []
        self.developpement = 0.0

    def dispo(self) -> float:
        e = self.e
        return min(0.995, 0.90 + e.qualite / 1000 + e.bonus("dispo"))

    def en_service(self) -> list[Centrale]:
        return [c for c in self.centrales if c.etat == "service"]

    def exploiter(self, demande, mois_cal, t, marche):
        e, r = self.e, self.e.rng
        msgs = []
        dispo = self.dispo()
        ca, production = 0.0, 0.0
        for c in self.centrales:
            if c.etat == "travaux":
                c.travaux -= 1
                if c.travaux <= 0:
                    c.etat = "service"
                    msgs.append(f"⚡ {c.nom} ({c.mw:.0f} MW) est raccordé et produit ses premiers MWh.")
                continue
            lib, mw, capex, travaux, fc, saison, om = TYPES_CENTRALE[c.type]
            sous_contrat = c.ppa_prix is not None and t < c.ppa_fin
            if c.type == "stockage":
                prod = 0.0
                rev = c.mw * 7_500 * (marche.spot / 70) ** 0.6 * r.uniform(0.8, 1.2) * (1 + e.bonus("trading"))
            else:
                prod = c.mw * 730 * fc * saison[mois_cal] * dispo * r.uniform(0.85, 1.15)
                prix = c.ppa_prix if sous_contrat else marche.spot * (1 + e.bonus("trading"))
                rev = prod * prix
                if not sous_contrat and marche.taxe_rente and marche.spot > 180:
                    taxe = prod * (marche.spot - 180) * 0.9
                    e.exceptionnel(-taxe, "Contribution sur la rente inframarginale")
            c.production, c.revenu = prod, rev
            ca += rev
            production += prod
            e.charge("operations", om * e.ops_mult, "charges")
        e.vendre(ca, t)
        if len(self.projets) < 3:
            self.developpement += (5 * math.log1p(e.mkt / 10_000) * (0.5 + e.notoriete / 100)
                                   * (1 + e.bonus("developpement")) * r.uniform(0.6, 1.4))
            if self.developpement >= 100:
                self.developpement = 0.0
                typ = r.choices(["solaire", "eolien", "stockage"], [0.5, 0.3, 0.2])[0]
                lieu = self.lieux.pop(0) if self.lieux else f"n°{len(self.centrales) + len(self.projets) + 1}"
                p = ProjetEnergie(f"{TYPES_CENTRALE[typ][0]} {lieu}", typ)
                self.projets.append(p)
                msgs.append(f"📜 Permis obtenu : « {p.nom} » ({TYPES_CENTRALE[typ][1]:.0f} MW) est prêt à construire.")
        return {"ventes": production, "capacite": sum(c.mw for c in self.en_service()),
                "utilisation": dispo, "manques": 0.0, "messages": msgs}

    # ------------------------------------------------------------ construction et contrats
    def cout_projet(self, p: ProjetEnergie) -> float:
        return round(TYPES_CENTRALE[p.type][2] * (1 + self.e.bonus("capex")) / 100_000) * 100_000

    def financement(self, p: ProjetEnergie) -> dict:
        e = self.e
        capex = self.cout_projet(p)
        part_dette = 0.8 if e.note in "ABC" else 0.6 if e.note == "D" else 0.0
        subvention = round(capex * 0.10 / 100_000) * 100_000
        dette = round(capex * part_dette / 100_000) * 100_000
        return {"capex": capex, "dette": dette, "subvention": subvention,
                "fonds_propres": capex - dette - subvention}

    def construire(self, p: ProjetEnergie) -> str:
        e = self.e
        if p not in self.projets:
            return "Ce projet n'est plus disponible."
        f = self.financement(p)
        if e.tresorerie < f["fonds_propres"]:
            return (f"Il faut {fmt(f['fonds_propres'])} de fonds propres pour financer « {p.nom} » (la banque prête "
                    f"{fmt(f['dette'])}, l'ADEME subventionne {fmt(f['subvention'])}). Levez des fonds d'abord.")
        lib, mw, capex, travaux, *_ = TYPES_CENTRALE[p.type]
        self.projets.remove(p)
        e.investir(p.nom, f["capex"], 240)
        if f["dette"]:
            e.prets.append(nouveau_pret(f["dette"], e.taux_ref + 0.018, 180, f"Dette de projet — {p.nom}",
                                        differe=travaux + 2, variable=True, marge=0.018))
            e.mouvement(f["dette"], "emprunts")
        e.exceptionnel(f["subvention"], "Subvention d'investissement")
        self.centrales.append(Centrale(p.nom, p.type, mw, f["capex"], "travaux", travaux))
        return (f"Construction de « {p.nom} » lancée : {fmt(f['capex'])}, dont {fmt(f['dette'])} de dette de projet "
                f"à taux variable et {fmt(f['subvention'])} de subvention. Mise en service dans {travaux} mois.")

    def prix_ppa_industriel(self, marche: "Marche") -> float:
        return round(0.92 * marche.spot_moyen(), 1)

    def signer_ppa(self, c: Centrale, prix: float, annees: int, t: int) -> str:
        if c.type == "stockage":
            return "Une batterie ne vend pas d'énergie sous contrat."
        c.ppa_prix, c.ppa_fin = prix, t + annees * 12
        return (f"Contrat signé pour « {c.nom} » : {prix:.1f} €/MWh garantis pendant {annees} ans.".replace(".", ",", 1))

    def lcoe(self, typ: str) -> float:
        """Coût complet de production (€/MWh) : le prix minimal pour rentabiliser une centrale."""
        lib, mw, capex, travaux, fc, saison, om = TYPES_CENTRALE[typ]
        if not fc:
            return 0.0
        mwh = mw * 8760 * fc * 0.96
        return (capex * (0.055 + self.e.taux_ref + 0.018) + om * 12) / mwh

    def valeur_parc(self, marche: "Marche | None" = None) -> float:
        e = self.e
        spot = marche.spot_moyen() if marche else 72.0
        ebitda = 0.0
        for c in self.en_service():
            lib, mw, capex, travaux, fc, saison, om = TYPES_CENTRALE[c.type]
            if c.type == "stockage":
                rev = c.mw * 7_500 * 12
            else:
                prix = c.ppa_prix if c.ppa_prix else spot
                rev = c.mw * 8760 * fc * self.dispo() * prix
            ebitda += rev - om * 12
        ebitda -= (e.s.loyer + e.s.salaire_dirigeant + e.masse_salariale() + e.s.frais_generaux) * 12
        travaux = sum(c.capex for c in self.centrales if c.etat == "travaux")
        return max(0.0, ebitda * 13) + travaux + 1_500_000 * len(self.projets)

    def ajuster_valeur(self, ev):
        return self.valeur_parc(getattr(self.e, "marche_ref", None))

    def levee_possible(self):
        return len(self.e.mois_reels()) >= 3

    def roic(self) -> float:
        e = self.e
        der = e.mois_reels()[-3:]
        if not der:
            return 0.0
        rex = sum(h.get("rex", 0.0) for h in der) / len(der) * 12
        capital = e.immo_nette + e.total_creances - e.total_fournisseurs
        return rex * 0.75 / capital if capital > 0 else 0.0

    def decider_ia(self, marche, force):
        e = self.e
        for p in list(self.projets):
            f = self.financement(p)
            if f["dette"] and e.tresorerie > f["fonds_propres"] + 6 * e.charges_fixes():
                self.construire(p)
                marche.nouvelles.append(f"⚡ {e.nom} lance la construction de « {p.nom} ».")
                break
        if e.strategie.cle == "premium":
            for c in self.centrales:
                if c.ppa_prix is None and c.type != "stockage" and marche.spot_moyen() > 70:
                    self.signer_ppa(c, self.prix_ppa_industriel(marche), 10, len(e.historique))

    def budgets_ia(self, force):
        st = self.e.strategie
        mk = {"lowcost": 30_000, "equilibre": 40_000, "premium": 30_000, "startup": 80_000}[st.cle] * force
        q = {"lowcost": 10_000, "equilibre": 20_000, "premium": 35_000, "startup": 15_000}[st.cle] * force
        if self.e.tresorerie < 3 * self.e.charges_fixes():
            mk, q = mk * 0.4, q * 0.4
        return mk, q

    def metriques(self):
        return {"mw": sum(c.mw for c in self.en_service()), "roic": self.roic()}

    def kpis(self):
        e = self.e
        reels = e.mois_reels()
        mw = sum(c.mw for c in self.en_service())
        mw_t = sum(c.mw for c in self.centrales if c.etat == "travaux")
        m = getattr(e, "marche_ref", None)
        return [{"titre": "Parc en service", "valeur": f"{mw:.0f} MW",
                 "detail": (f"+{mw_t:.0f} MW en construction" if mw_t else f"{len(self.projets)} projet(s) prêt(s)"),
                 "serie": [h.get("kpi", {}).get("mw", 0.0) for h in reels], "couleur": None},
                {"titre": "Rendement du capital (ROIC)", "valeur": f"{self.roic() * 100:.1f} %".replace(".", ","),
                 "detail": (f"marché {m.spot:.0f} €/MWh · taux {fmt_taux(m.taux_ref)}" if m else ""),
                 "serie": [h.get("kpi", {}).get("roic", 0.0) for h in reels], "couleur": None}]

    def jauge(self):
        v = self.dispo() * 100
        return "Disponibilité", v, f"{v:.1f} %".replace(".", ","), False

    def resume(self):
        return f"{sum(c.mw for c in self.en_service()):.0f} MW en service"

    def conseils(self):
        e = self.e
        c = []
        if self.projets:
            c.append(f"« {self.projets[0].nom} » a son permis : lancez la construction (page Parc de centrales).")
        m = getattr(e, "marche_ref", None)
        libres = [x for x in self.centrales if x.ppa_prix is None and x.type != "stockage"]
        if libres and m:
            c.append(f"{len(libres)} centrale(s) vendent au prix du marché ({m.spot:.0f} €/MWh) : un contrat long "
                     "(PPA) sécuriserait vos revenus.")
        if m and m.taux_ref > 0.04:
            c.append(f"Taux de référence à {fmt_taux(m.taux_ref)} : votre dette variable coûte de plus en plus cher.")
        return c

    def fusion_niche(self, f):
        lieu = self.lieux.pop(0) if self.lieux else "du Val"
        c = Centrale(f"Petit parc solaire {lieu}", "solaire", 8.0, 0.0, "service", 0)
        self.centrales.append(c)
        return f"sa centrale ({c.nom}, 8 MW)"

    def evenement(self, marche):
        e, r = self.e, self.e.rng
        if len(e.historique) < 4 or r.random() > 0.05:
            return None
        chantiers = [c for c in self.centrales if c.etat == "travaux" and c.type == "eolien"]
        if chantiers and r.random() < 0.5:
            c = chantiers[0]
            c.travaux += 6
            return {"cle": "act_recours", "titre": "Recours contre votre parc éolien",
                    "texte": f"Une association de riverains attaque le permis de « {c.nom} ». Le chantier prend "
                             "6 mois de retard, et la dette court toujours.", "choix": None}
        if not marche.taxe_rente and marche.spot > 120:
            marche.taxe_rente = True
            return {"cle": "act_taxe", "titre": "Taxe sur la rente des producteurs",
                    "texte": "Face à l'envolée des prix, l'État taxe à 90 % les revenus au-delà de 180 €/MWh pour "
                             "les centrales qui vendent au prix du marché.", "choix": None}
        return None


MODELES = {"industrie": ActiviteIndustrie, "saas": ActiviteSaaS, "biotech": ActiviteBiotech, "jeu": ActiviteJeu,
           "luxe": ActiviteLuxe, "aero": ActiviteAero, "distribution": ActiviteDistribution,
           "energie": ActiviteEnergie}
VERT_K, ROUGE_K = "vert", "rouge"   # couleurs symboliques des indicateurs (traduites par l'interface)


# =============================================================================
class Entreprise:
    def __init__(self, nom: str, secteur: Secteur, couleur: str, apport: float, pret_initial: float = 0.0,
                 strategie: Strategie | None = None, rng: random.Random | None = None):
        s = secteur
        self.rng = rng or random.Random()
        self.nom = nom
        self.s = s
        self.couleur = couleur
        self.strategie = strategie                 # None : c'est le joueur
        self.joueur = strategie is None
        self.marche_ref = None                     # le marché (prix de l'électricité, taux…), fixé par le Marche
        # --- comptabilité : chaque euro qui entre ou sort passe par mouvement(), chaque charge ou produit
        # par comptabiliser() ; le bilan (actif = passif) est ainsi toujours équilibré
        self.tresorerie = 0.0
        self.prets: list[Pret] = []
        self.capital = 0.0                          # apports du fondateur et des investisseurs
        self.reserves = 0.0                         # résultats des exercices clos (report à nouveau)
        self.immos: list[dict] = []                 # {libelle, brut, amorti, duree}
        self.goodwill = 0.0                         # écarts d'acquisition (rachats)
        self.stocks = 0.0                           # marchandises en stock (au prix d'achat)
        self.encours = 0.0                          # travaux réalisés, pas encore facturés (contrats longs)
        self.creances: list[list] = []              # [mois d'échéance, montant, taux d'impayés]
        self.dettes_fourn: list[list] = []          # [mois d'échéance, montant]
        self.avances = 0.0                          # acomptes reçus des clients (ou d'un éditeur)
        self.dette_fiscale = 0.0                    # impôt sur les sociétés à payer
        self.credit_impot = 0.0                     # crédit d'impôt à recevoir de l'État
        self.deficit_reportable = 0.0
        self.cii_annee = 0.0                        # crédit d'impôt acquis sur l'exercice
        self.placements = 0.0
        self.credits_bail: list[dict] = []          # {libelle, loyer, restant, total}
        self.delai_clients = s.delai_clients if s.b2b else 0
        self.delai_fournisseurs = s.delai_fournisseurs
        self.dividendes_verses = 0.0
        self.patrimoine = 0.0                       # dividendes nets touchés par le fondateur
        self.incidents = 0                          # incidents bancaires (prêt d'urgence, impayés…)
        self.note = "B"
        self.taux_ref = TAUX_REF_INITIAL
        self.exercice = pl_vide()                   # compte de résultat de l'exercice en cours
        self.exercices: list[dict] = []             # exercices clos
        self.nouvelle_periode()
        # --- tour de table de départ
        self.capital = apport + s.investisseurs * (strategie.capital if strategie else 1.0)
        self.mouvement(self.capital, "levees")
        self.part_fondateur = 1.0 - s.part_investisseurs
        if pret_initial:
            taux = s.taux_pret_initial if not s.pret_variable else TAUX_REF_INITIAL + 0.018
            self.prets.append(nouveau_pret(pret_initial, taux, s.duree_pret_initial, s.libelle_pret,
                                           differe=s.differe_initial, variable=s.pret_variable,
                                           marge=0.018 if s.pret_variable else 0.0))
            self.mouvement(pret_initial, "emprunts")
        if s.subvention_initiale:
            self.produit("subventions", s.subvention_initiale, "subventions")
            self.periode["details"].append((s.libelle_subvention, s.subvention_initiale))
        self.investir(s.libelle_installation, s.installation, s.duree_installation)
        self.equipe: list[Employe] = []
        self.filiales: list[Filiale] = []
        self.amont = False                          # fournisseur intégré : à l'abri des pénuries
        self.ca_filiales = 0.0                      # chiffre d'affaires des filiales ce mois-ci
        self.vivier: list[Employe] = []             # candidats du mois (joueur)
        self.prix = s.prix_ref * (strategie.prix if strategie else 1.0)
        self.notoriete = s.notoriete_initiale
        self.qualite = s.qualite_initiale + (12 if strategie and strategie.cle == "premium" else 0)
        self.moral = 75.0
        self.satisfaction = 70.0
        self.abonnes = 0.0
        self.cout_unitaire = s.cout_unitaire
        self.impots_payes = 0.0
        self.historique: list[dict] = []
        self.actif = True
        self.fin_raison = ""                        # « faillite », « rachetée »…
        self.aide_urgence_utilisee = False
        self.levees = 0
        self.mkt = self.qinv = 0.0
        self.mkt_prevu = self.q_prevu = 0.0
        self.guerre_prix = 0                        # mois restants de riposte tarifaire (IA)
        self.mult_prix = strategie.prix if strategie else 1.0
        self.ameliorations: dict[str, int] = {}
        self.capa_mult = self.portee = self.loyer_mult = self.churn_mult = self.mkt_mult = self.ops_mult = 1.0
        self.bonus_effets: dict[str, float] = {}
        self.bonus_satisfaction = 0.0
        self.salaire_mult = 1.0                     # niveau des salaires (inflation, augmentations)
        self.penurie = 0                            # mois de pénurie d'approvisionnement (capacité −40 %)
        self.stock_secours = False
        self.distance = False                       # vente à distance prête en cas de confinement
        self.riposte_mkt = 0                        # mois de contre-offensive marketing (IA)
        self.refus_rachat = 0                       # mois pendant lesquels elle refuse de discuter d'un rachat
        self.exigence = self.rng.uniform(0.9, 1.1)  # caractère plus ou moins gourmand en négociation
        for _ in range(s.equipe_initiale):
            self.equipe.append(self.equipier())
        self.act = MODELES[s.modele](self)
        if isinstance(self.act, ActiviteLuxe) and strategie:
            self.prix = min(self.prix, round(self.act.pma() * 0.97, -1))
            self.act.dernier_prix = self.prix
        if self.joueur:
            self.renouveler_vivier()

    # ------------------------------------------------------------ comptabilité
    def nouvelle_periode(self) -> None:
        """Ouvre la période comptable du mois (compte de résultat et flux de trésorerie)."""
        self.periode = {"pl": pl_vide(), "flux": flux_vide(), "tresorerie_debut": self.tresorerie, "details": []}

    def mouvement(self, montant: float, flux: str) -> None:
        """Seule façon de faire entrer ou sortir de l'argent du compte en banque."""
        self.tresorerie += montant
        self.periode["flux"][flux] += montant

    def comptabiliser(self, poste: str, montant: float) -> None:
        self.periode["pl"][poste] += montant
        self.exercice[poste] += montant

    def charge(self, poste: str, montant: float, flux: str | None = None) -> None:
        """Une charge ; payée tout de suite si un flux de trésorerie est indiqué."""
        self.comptabiliser(poste, montant)
        if flux:
            self.mouvement(-montant, flux)

    def produit(self, poste: str, montant: float, flux: str | None = None) -> None:
        self.comptabiliser(poste, montant)
        if flux:
            self.mouvement(montant, flux)

    def exceptionnel(self, montant: float, libelle: str) -> None:
        """Produit (montant > 0) ou charge (montant < 0) exceptionnel, réglé comptant."""
        self.comptabiliser("exceptionnel", montant)
        self.mouvement(montant, "exceptionnel")
        self.periode["details"].append((libelle, montant))

    def investir(self, libelle: str, montant: float, duree: int = DUREE_AMORT) -> None:
        """Achat comptant d'une immobilisation, amortie ensuite sur sa durée (5 ans par défaut)."""
        self.immos.append({"libelle": libelle, "brut": montant, "amorti": 0.0, "duree": duree})
        self.mouvement(-montant, "investissements")

    def vendre(self, montant: float, t: int) -> None:
        """Chiffre d'affaires : les particuliers paient comptant, les professionnels selon le délai accordé."""
        if montant <= 0:
            return
        a_credit = montant * self.s.b2b if self.delai_clients else 0.0
        self.produit("ca", montant)
        self.mouvement(montant - a_credit, "clients")
        if a_credit:
            self.creances.append([t + self.delai_clients // 30, a_credit, DELAIS_CLIENTS[self.delai_clients][1]])

    def acheter(self, montant: float, t: int, poste: str = "achats") -> None:
        """Achats consommés : payés comptant (avec escompte) ou à 30 / 60 jours."""
        if montant <= 0:
            return
        montant *= DELAIS_FOURN[self.delai_fournisseurs]
        self.charge(poste, montant)
        if self.delai_fournisseurs:
            self.dettes_fourn.append([t + self.delai_fournisseurs // 30, montant])
        else:
            self.mouvement(-montant, "fournisseurs")

    def acheter_stock(self, montant: float, t: int, comptant: bool = False) -> None:
        """Achat de marchandises pour le stock : pas une charge tant qu'elles ne sont pas vendues."""
        if montant <= 0:
            return
        self.stocks += montant
        if self.delai_fournisseurs and not comptant:
            self.dettes_fourn.append([t + self.delai_fournisseurs // 30, montant])
        else:
            self.mouvement(-montant, "fournisseurs")

    def consommer_stock(self, montant: float) -> None:
        montant = min(montant, self.stocks)
        self.stocks -= montant
        self.comptabiliser("achats", montant)

    def encaisser_avance(self, montant: float) -> None:
        """Acompte reçu : de l'argent en caisse, mais une dette envers le client tant que le travail n'est pas fait."""
        self.avances += montant
        self.mouvement(montant, "clients")

    def encaisser_creances(self, t: int) -> None:
        restantes = []
        for c in self.creances:                    # factures arrivées à échéance
            if c[0] <= t:
                perte = c[1] * c[2] * (0.4 if self.membres("daf") else 1.0)
                self.mouvement(c[1] - perte, "clients")
                if perte:
                    self.comptabiliser("impayes", perte)
            else:
                restantes.append(c)
        self.creances = restantes

    def payer_fournisseurs(self, t: int) -> None:
        if self.act.payer_fournisseurs(t):
            return
        a_payer = []
        for d in self.dettes_fourn:
            if d[0] <= t:
                self.mouvement(-d[1], "fournisseurs")
            else:
                a_payer.append(d)
        self.dettes_fourn = a_payer

    @property
    def dette(self) -> float:
        return sum(p.capital_restant for p in self.prets)

    @property
    def immo_nette(self) -> float:
        return sum(i["brut"] - i["amorti"] for i in self.immos)

    @property
    def total_creances(self) -> float:
        return sum(c[1] for c in self.creances)

    @property
    def total_fournisseurs(self) -> float:
        return sum(d[1] for d in self.dettes_fourn)

    @property
    def resultat_en_cours(self) -> float:
        return soldes(self.exercice)["net"]

    @property
    def capitaux_propres(self) -> float:
        return self.capital + self.reserves + self.resultat_en_cours

    @property
    def engagements_credit_bail(self) -> float:
        return sum(c["loyer"] * c["restant"] for c in self.credits_bail)

    @property
    def dette_nette(self) -> float:
        """Dettes financières (y compris crédit-bail) moins trésorerie et placements."""
        return self.dette + self.engagements_credit_bail * 0.9 - self.tresorerie - self.placements

    def bilan_comptable(self) -> dict:
        actif = {"immos": self.immo_nette, "goodwill": self.goodwill, "stocks": self.stocks,
                 "encours": self.encours, "creances": self.total_creances, "etat": self.credit_impot,
                 "placements": self.placements, "disponibilites": max(0.0, self.tresorerie)}
        passif = {"capital": self.capital, "reserves": self.reserves, "resultat": self.resultat_en_cours,
                  "emprunts": self.dette, "decouvert": max(0.0, -self.tresorerie), "avances": self.avances,
                  "fournisseurs": self.total_fournisseurs, "fiscal": self.dette_fiscale}
        return {"actif": actif, "passif": passif, "total_actif": sum(actif.values()),
                "total_passif": sum(passif.values()), "hors_bilan": self.engagements_credit_bail}

    def ecart_bilan(self) -> float:
        b = self.bilan_comptable()
        return b["total_actif"] - b["total_passif"]

    def mois_reels(self) -> list[dict]:
        """Les mois d'activité réelle (avec leurs comptes)."""
        return [h for h in self.historique if "pl" in h]

    def charges_fixes(self) -> float:
        s = self.s
        return (s.loyer * self.loyer_mult + s.salaire_dirigeant + self.masse_salariale() + s.frais_generaux
                + sum(c["loyer"] for c in self.credits_bail) + self.act.fixes())

    def bonus(self, nom: str) -> float:
        return self.bonus_effets.get(nom, 0.0)

    # ------------------------------------------------------------ banque
    def analyse_credit(self) -> tuple[float, list[tuple[str, str, bool]]]:
        """Ce que regarde la banque : un score (0 = parfait) et le détail des critères (libellé, valeur, ok)."""
        reels = self.mois_reels()
        der = reels[-3:]
        det = []
        score = 0.0
        if len(der) < 3:
            det.append(("Historique", "moins de 3 mois : note de départ", True))
            score = 0.5 + 1.25 * self.incidents
        else:
            ebe_m = sum(h["ebe"] for h in der) / 3
            frais_fin = sum(h["pl"]["charges_fin"] for h in der) / 3
            dn = self.dette_nette
            if ebe_m <= 0:
                # l'entreprise brûle de l'argent : la banque regarde combien de mois elle peut tenir
                autonomie = (self.tresorerie + self.placements) / max(1.0, frais_fin - ebe_m)
                score += 0.5 if autonomie >= 12 else 1.0 if autonomie >= 6 else 1.5
                det.append(("EBE (3 derniers mois)", "négatif", False))
                det.append(("Autonomie de trésorerie", f"{max(0.0, autonomie):.0f} mois", autonomie >= 6))
            else:
                levier = dn / (ebe_m * 12)          # dette nette / EBE annuel
                limite = 2.5 * max(1.0, self.s.bancabilite * 2.5)   # les infrastructures supportent plus de dette
                score += (0.0 if levier <= limite * 0.4 else 0.5 if levier <= limite else 1.0 if levier <= limite * 1.6
                          else 1.5)
                det.append(("Dette nette / EBE annuel", "trésorerie nette positive" if dn < 0 else
                            f"{levier:.1f} an(s)".replace(".", ","), levier <= limite))
                if frais_fin > 0:
                    couv = ebe_m / frais_fin
                    if couv < 2:
                        score += 0.5
                    det.append(("Couverture des intérêts par l'EBE", f"× {couv:.1f}".replace(".", ","), couv >= 2))
                if dn < 0:
                    score -= 0.5                    # plus de trésorerie que de dettes
                perte = sum(h["resultat"] for h in der) < 0
                if perte:
                    score += 0.5
                det.append(("Résultat net (3 derniers mois)", "déficitaire" if perte else "bénéficiaire", not perte))
            if len(reels) < 12:
                score -= 0.5                        # la banque accompagne le démarrage
                det.append(("Jeune entreprise", "la banque accompagne le démarrage", True))
        if self.membres("daf"):
            score -= 0.5
            det.append(("Directeur financier", "rassure la banque", True))
        if self.tresorerie < 0:
            score += 1.0
        det.append(("Compte en banque", "à découvert" if self.tresorerie < 0 else "créditeur", self.tresorerie >= 0))
        if self.capitaux_propres < 0:
            score += 0.5
        det.append(("Capitaux propres", "négatifs" if self.capitaux_propres < 0 else "positifs",
                    self.capitaux_propres >= 0))
        if len(der) >= 3:
            score += self.incidents
        det.append(("Incidents bancaires", str(self.incidents) if self.incidents else "aucun", not self.incidents))
        return score, det

    def notation(self) -> str:
        """Note de crédit attribuée par la banque, de A (excellente) à E (plus de crédit)."""
        score, _ = self.analyse_credit()
        for seuil, n in ((0.25, "A"), (1.0, "B"), (2.0, "C"), (3.0, "D")):
            if score <= seuil:
                return n
        return "E"

    def taux_emprunt(self, duree_ans: int = 5) -> float | None:
        base = NOTES[self.note][0]
        remise = 0.005 if self.membres("daf") else 0.0
        if base is None:
            return None
        return max(0.005, base + (self.taux_ref - TAUX_REF_INITIAL) + DUREES_PRET.get(duree_ans, 0.0) - remise)

    def decouvert_autorise(self) -> float:
        return round(NOTES[self.note][2] * self.charges_fixes() / 500) * 500

    def ca_annualise(self) -> float:
        derniers = [h["ca"] for h in self.historique[-3:]]
        return sum(derniers) / len(derniers) * 12 if derniers else 0.0

    def capacite_emprunt(self) -> float:
        ca_an = self.ca_annualise()
        # la banque prête selon l'activité et les actifs qui servent de garantie ; le secteur et la note
        # modulent ce plafond
        garantie = self.immo_nette * 0.7
        plancher = 20_000 * self.s.echelle
        plafond = max(plancher, ca_an * 0.35, garantie) if len(self.historique) >= 3 else max(plancher * 3, garantie)
        plafond *= NOTES[self.note][1] * self.s.bancabilite
        return max(0.0, round((plafond - self.dette) / 1000) * 1000)

    def emprunter(self, montant: float, duree_ans: int = 5) -> str:
        taux = self.taux_emprunt(duree_ans)
        if taux is None:
            return "La banque refuse tout nouveau crédit : votre note est E (situation critique)."
        montant = min(montant, self.capacite_emprunt())
        if montant < 1000:
            return "La banque refuse : vous êtes déjà trop endetté pour votre niveau d'activité."
        self.prets.append(nouveau_pret(montant, taux, duree_ans * 12))
        self.mouvement(montant, "emprunts")
        return (f"Prêt de {fmt(montant)} accordé sur {duree_ans} ans à {fmt_taux(taux)} (note {self.note}) : "
                f"mensualité de {fmt(self.prets[-1].mensualite)}.")

    def rembourser(self, pret: Pret) -> str:
        """Remboursement anticipé d'un prêt, avec indemnité."""
        if pret not in self.prets:
            return "Ce prêt n'existe plus."
        pen = pret.penalite()
        total = pret.capital_restant + pen
        if total > self.tresorerie:
            return f"Trésorerie insuffisante : il faut {fmt(total)} pour solder ce prêt."
        self.mouvement(-pret.capital_restant, "remboursements")
        if pen:
            self.charge("charges_fin", pen, "financier")
        self.prets.remove(pret)
        return (f"{pret.libelle} soldé : {fmt(pret.capital_restant)} remboursés"
                + (f" + {fmt(pen)} d'indemnité." if pen else ", sans indemnité."))

    def placer(self, montant: float) -> str:
        montant = min(montant, self.tresorerie)
        if montant < 100:
            return "Rien à placer."
        self.placements += montant
        self.mouvement(-montant, "placements")
        return f"{fmt(montant)} placés sur un compte à terme à {TAUX_LIVRET:.0%} par an.".replace("%", " %")

    def retirer(self, montant: float) -> str:
        montant = min(montant, self.placements)
        if montant < 1:
            return "Aucun placement à récupérer."
        self.placements -= montant
        self.mouvement(montant, "placements")
        return f"{fmt(montant)} récupérés de vos placements."

    def ceder_creances(self) -> str:
        """Affacturage : la banque rachète toutes les factures clients en attente, moins sa commission."""
        total = self.total_creances
        if total < 100:
            return "Aucune facture client en attente."
        frais = total * FRAIS_AFFACTURAGE
        self.creances = []
        self.mouvement(total, "clients")
        self.charge("charges_fin", frais, "financier")
        return (f"Affacturage : {fmt(total)} de factures cédées, {fmt(total - frais)} encaissés tout de suite "
                f"({fmt(frais)} de commission). Les éventuels impayés sont désormais pour l'affactureur.")

    def regler_delais(self, clients: int | None = None, fournisseurs: int | None = None) -> None:
        if clients in DELAIS_CLIENTS:
            self.delai_clients = clients
        if fournisseurs in DELAIS_FOURN:
            self.delai_fournisseurs = fournisseurs

    # ------------------------------------------------------------ actionnaires
    def valorisation(self) -> float:
        if not self.actif:
            return 0.0
        ca = self.ca_annualise()
        res = sum(h.get("rcai", h["resultat"]) for h in self.historique[-6:]) * 2
        marge = res / ca if ca else 0
        ajust = max(0.3, min(1.8, 1 + marge * 2))
        croissance = 1.0
        if len(self.historique) >= 7 and self.historique[-7]["ca"] > 0:
            g = self.historique[-1]["ca"] / self.historique[-7]["ca"] - 1
            croissance = max(0.7, min(1 + 1.2 * self.s.bonus_croissance, 1 + g * self.s.bonus_croissance))
        ca_fil = sum(h.get("ca_filiales", 0.0) for h in self.historique[-3:]) / max(1, len(self.historique[-3:])) * 12
        ev = max(0.0, ca - ca_fil) * self.s.multiple * ajust * croissance
        ev = self.act.ajuster_valeur(ev)
        filiales = sum(f.valeur_entreprise(self.s.multiple) for f in self.filiales)
        return max(0.0, ev + filiales + self.tresorerie + self.placements - self.dette - self.dette_fiscale
                   + self.credit_impot)

    def conditions_levee(self) -> dict | None:
        """Levée de fonds possible ? {valorisation, mini, maxi} ou None."""
        if self.levees >= self.s.levees_max or not self.act.levee_possible():
            return None
        v = self.valorisation()
        if v < 20_000 * self.s.echelle:
            return None
        pas = 10 ** max(3, int(math.log10(v)) - 2) * 5
        return {"valorisation": v, "mini": max(pas, round(v * 0.1 / pas) * pas),
                "maxi": max(pas, round(v * 0.6 / pas) * pas), "pas": pas}

    def offre_levee(self) -> tuple[float, float] | None:
        c = self.conditions_levee()
        if not c:
            return None
        montant = round(c["valorisation"] * 0.4 / c["pas"]) * c["pas"]
        return montant, montant / (c["valorisation"] + montant)

    def lever(self, montant: float | None = None) -> str:
        c = self.conditions_levee()
        if not c:
            return ("Aucun investisseur intéressé pour l'instant : il faut quelques mois d'activité, des résultats "
                    f"tangibles à montrer (clients, essais, projet avancé…), et pas plus de {self.s.levees_max} levées.")
        v = c["valorisation"]
        montant = max(c["mini"], min(c["maxi"], montant if montant is not None else v * 0.4))
        part = montant / (v + montant)
        self.capital += montant
        self.mouvement(montant, "levees")
        self.part_fondateur *= (1 - part)
        self.levees += 1
        return (f"Levée de fonds de {fmt(montant)} sur une valorisation de {fmt(v)} avant l'opération : "
                f"les investisseurs prennent {part * 100:.0f} % du capital. Vous détenez désormais "
                f"{self.part_fondateur * 100:.1f} % de l'entreprise.".replace(".", ",", 1))

    def dividende_max(self) -> float:
        """Distribuable : les bénéfices mis en réserve, dans la limite de la trésorerie."""
        return max(0.0, min(self.reserves, self.tresorerie))

    def verser_dividende(self, montant: float) -> str:
        montant = min(montant, self.dividende_max())
        if montant < 100:
            return ("Rien à distribuer : il faut des bénéfices d'exercices clos (réserves positives) "
                    "et de la trésorerie.")
        self.reserves -= montant
        self.mouvement(-montant, "dividendes")
        brut = montant * self.part_fondateur
        net = brut * (1 - FLAT_TAX)
        self.dividendes_verses += montant
        self.patrimoine += net
        return (f"Dividende de {fmt(montant)} versé. Votre part : {fmt(brut)}, soit {fmt(net)} nets après "
                f"la flat tax de 30 %. Cet argent est à vous, quoi qu'il arrive à l'entreprise.")

    # ------------------------------------------------------------ équipe
    @property
    def salaries(self) -> int:
        return len(self.equipe)

    @salaries.setter
    def salaries(self, n: int) -> None:
        """Compatibilité : ajuster l'effectif ajoute des équipiers anonymes ou retire les derniers arrivés."""
        n = max(0, int(n))
        while len(self.equipe) < n:
            self.equipe.append(self.equipier())
        while len(self.equipe) > n:
            generiques = [e for e in self.equipe if e.profil == "equipier"]
            self.equipe.remove(generiques[-1] if generiques else self.equipe[-1])

    def equipier(self) -> Employe:
        return Employe("Équipier", "equipier", self.s.salaire, self.s.salaire)

    def titre(self, e: Employe) -> str:
        if e.profil == "star":
            return self.s.titre_star
        return e.p.titre

    def titre_min(self, e: Employe) -> str:
        t = self.titre(e)
        return t if t[:2].isupper() else t[0].lower() + t[1:]

    def membres(self, profil: str) -> list[Employe]:
        return [e for e in self.equipe if e.profil == profil]

    def effet(self, nom: str) -> float:
        """Somme des apports de l'équipe (chaque effet est modulé par le talent de la personne)."""
        table = {"qualite": {"star": 2.5, "perfectionniste": 1.5}, "satisfaction": {"commercial": -1.5,
                 "perfectionniste": 1.5}, "moral": {"rh": 2.5}, "notoriete": {"growth": 1.5}, "mkt": {"growth": 0.3},
                 "attrait": {"commercial": 0.10}}[nom]
        return sum(table.get(e.profil, 0.0) * e.talent for e in self.equipe)

    def masse_salariale(self) -> float:
        """Salaires fixes chargés de l'équipe (hors dirigeant et commissions)."""
        return sum(e.salaire for e in self.equipe) * self.salaire_mult

    def taux_commission(self) -> float:
        return 0.03 * len(self.membres("commercial"))

    def seuil_exigence(self, profil: str) -> float:
        return {"formation": 300, "budget_mkt": 1_500}.get(PROFILS[profil].exigence, 0) * self.s.echelle

    def exigence_texte(self, e: Employe) -> str:
        return e.p.exigence_txt.replace("{montant}", fmt(self.seuil_exigence(e.profil)))

    def nouveau_candidat(self) -> Employe:
        r = self.rng
        cles = [c for c in PROFILS]
        poids = []
        for c in cles:
            w = PROFILS[c].frequence
            if c in ("star", "rh", "daf", "growth") and self.membres(c):
                w *= 0.3                             # on en a déjà un : moins de candidats de ce type
            poids.append(w)
        cle = r.choices(cles, poids)[0]
        talent = round(r.uniform(0.85, 1.25), 2)
        base = PROFILS[cle].salaire * self.s.salaire / SALAIRE_CHARGE
        pretention = round(base * talent * r.uniform(0.95, 1.08) / 50) * 50
        nom = f"{r.choice(PRENOMS)} {r.choice('ABCDEFGHJKLMNPRSTV')}."
        return Employe(nom, cle, pretention, pretention, talent, 70.0, progression=0.6 if cle == "junior" else 1.0)

    def renouveler_vivier(self) -> None:
        self.vivier = [self.nouveau_candidat() for _ in range(3)]

    def frais_recrutement(self, c: Employe) -> float:
        # un chasseur de têtes pour les profils rares
        return round(c.pretention * (1.2 if c.profil in ("star", "daf", "mercenaire") else 0.6) / 100) * 100

    def embaucher(self, c: Employe, salaire: float) -> tuple[bool, str]:
        """Offre d'embauche à un candidat du vivier, au salaire proposé."""
        if c not in self.vivier:
            return False, "Ce candidat n'est plus disponible."
        ratio = salaire / c.pretention
        self.vivier.remove(c)
        if self.rng.random() > chance_acceptation(ratio):
            return False, (f"{c.nom} décline votre offre de {fmt(salaire)} par mois (il en demandait "
                           f"{fmt(c.pretention)}) et part chez un concurrent.")
        c.salaire = salaire
        c.moral = max(30.0, min(100.0, 68 + (ratio - 1) * 100))
        frais = self.frais_recrutement(c)
        self.charge("divers", frais, "charges")
        extra = ""
        if c.profil == "star":
            c.parts = 0.02
            self.part_fondateur *= 1 - c.parts
            extra = f" Il reçoit 2 % du capital : vous détenez désormais {self.part_fondateur:.1%}.".replace(".", ",", 1)
        self.equipe.append(c)
        self.moral = min(100, self.moral + 3)
        return True, (f"{c.nom} rejoint l'équipe comme {self.titre_min(c)} pour {fmt(salaire)} par mois "
                      f"({fmt(frais)} de frais de recrutement).{extra}")

    def recruter(self, n: int = 1) -> str:
        """Recrutement d'équipiers polyvalents (concurrents, tests)."""
        frais = round(self.s.salaire * 0.6 / 100) * 100 * n
        for _ in range(n):
            self.equipe.append(self.equipier())
        self.charge("divers", frais, "charges")
        self.moral = min(100, self.moral + 3)
        return f"{n} recrutement(s) : {fmt(frais)} de frais. Équipe : {self.salaries} salarié(s) + vous."

    def indemnite(self, e: Employe) -> float:
        return e.salaire * self.salaire_mult * (1 + e.anciennete / 24)

    def licencier(self, e: Employe | None = None) -> str:
        if not self.equipe:
            return "Vous n'avez aucun salarié."
        if e is None:
            generiques = self.membres("equipier")
            e = generiques[-1] if generiques else self.equipe[-1]
        if e not in self.equipe:
            return "Cette personne ne fait plus partie de l'équipe."
        cout = self.indemnite(e)
        self.equipe.remove(e)
        self.charge("salaires", cout, "salaires")
        self.moral = max(0, self.moral - 12)
        msg = f"{e.nom} ({self.titre_min(e)}) quitte l'entreprise : {fmt(cout)} d'indemnités. Le moral baisse."
        for rh in self.membres("rh"):
            self.equipe.remove(rh)
            self.moral = max(0, self.moral - 8)
            msg += f" {rh.nom}, votre RH, refuse de cautionner ce licenciement et démissionne."
        return msg

    def augmenter(self, e: Employe, taux: float = 0.10) -> str:
        if e not in self.equipe:
            return "Cette personne ne fait plus partie de l'équipe."
        avant = e.salaire
        e.salaire = round(e.salaire * (1 + taux) / 50) * 50
        e.moral = min(100.0, e.moral + 15)
        return f"{e.nom} est augmenté : {fmt(avant)} → {fmt(e.salaire)} par mois. Il est ravi."

    def exigence_ok(self, e: Employe, ratio_prix: float) -> bool:
        x = e.p.exigence
        if x == "formation":
            return self.qinv >= self.seuil_exigence(e.profil)
        if x == "budget_mkt":
            return self.mkt >= self.seuil_exigence(e.profil)
        if x == "decouvert":
            return self.tresorerie >= 0
        if x == "premium":
            return ratio_prix >= 0.9
        return True

    def vie_equipe(self, ratio_prix: float) -> list[str]:
        """Fin de mois : ancienneté, progression, moral de chacun, exigences, démissions."""
        msgs = []
        for e in list(self.equipe):
            e.anciennete += 1
            if e.profil == "junior":
                e.progression = min(1.1, e.progression + 0.04)
            if not self.joueur:
                continue
            ok = self.exigence_ok(e, ratio_prix)
            e.alerte = 0 if ok else e.alerte + 1
            cible = (self.moral + (e.salaire / e.pretention - 1) * 100 + (4 if ok else -25)
                     + 6 * len(self.membres("rh")) * (e.profil != "rh"))
            e.moral = max(0.0, min(100.0, e.moral + (cible - e.moral) * 0.35))
            limite = 2 if e.p.exigence == "decouvert" else 3
            if e.alerte >= limite or (e.moral < 20 and self.rng.random() < 0.5):
                self.equipe.remove(e)
                self.moral = max(0.0, self.moral - 5)
                raison = self.exigence_texte(e).split(":")[0].lower() if e.alerte >= limite else "trop malheureux"
                msgs.append(f"🚪 {e.nom} ({self.titre_min(e)}) démissionne : {raison}.")
            elif not ok and e.alerte == 1:
                txt = self.exigence_texte(e)
                msgs.append(f"⚠ {e.nom} ({self.titre_min(e)}) est mécontent : {txt[0].lower()}{txt[1:]}")
            elif e.moral < 35 and e.anciennete % 3 == 0:
                msgs.append(f"⚠ {e.nom} ({self.titre_min(e)}) a le moral à zéro : augmentez-le ou il partira.")
        return msgs

    def cout_salarie(self) -> float:
        return self.s.salaire * self.salaire_mult

    def capacite(self) -> float:
        return self.act.capacite()

    # ------------------------------------------------------------ investissements stratégiques
    def ameliorations_secteur(self) -> dict:
        return AMELIORATIONS[self.s.cle]

    def cout_amelioration(self, cle: str) -> float:
        a = self.ameliorations_secteur()[cle]
        niveau = self.ameliorations.get(cle, 0)
        return round(a.cout * (1 + 0.5 * niveau) / 1000) * 1000

    def peut_ameliorer(self, cle: str) -> bool:
        return self.ameliorations.get(cle, 0) < self.ameliorations_secteur()[cle].niveaux

    def loyer_credit_bail(self, cle: str) -> float:
        return self.cout_amelioration(cle) * (1 + MAJ_CREDIT_BAIL) / DUREE_CREDIT_BAIL

    def ameliorer(self, cle: str, mode: str = "comptant") -> str:
        """Investissement payé comptant (immobilisation amortie sur 5 ans) ou financé en crédit-bail
        (36 loyers, rien au bilan : un engagement hors bilan)."""
        a = self.ameliorations_secteur()[cle]
        if not self.peut_ameliorer(cle):
            return f"{a.nom} : déjà au niveau maximum."
        cout = self.cout_amelioration(cle)
        niveau = self.ameliorations.get(cle, 0) + 1
        libelle = a.nom + (f" (niveau {niveau})" if a.niveaux > 1 else "")
        if mode == "credit_bail":
            if self.note == "E":
                return "Le loueur refuse : votre note de crédit est E."
            loyer = self.loyer_credit_bail(cle)
            self.credits_bail.append({"libelle": libelle, "loyer": loyer, "restant": DUREE_CREDIT_BAIL,
                                      "total": DUREE_CREDIT_BAIL})
            self.appliquer_amelioration(cle)
            return f"{a.nom} : financé en crédit-bail, {DUREE_CREDIT_BAIL} loyers de {fmt(loyer)}. {a.effet}."
        self.investir(libelle, cout)
        self.appliquer_amelioration(cle)
        return f"{a.nom} : investissement de {fmt(cout)} réalisé (amorti sur 5 ans). {a.effet}."

    def appliquer_amelioration(self, cle: str) -> None:
        self.ameliorations[cle] = self.ameliorations.get(cle, 0) + 1
        self.appliquer_effets(self.ameliorations_secteur()[cle].effets)

    def appliquer_effets(self, effets: dict, sens: int = 1) -> None:
        """Effets durables d'un investissement ou d'une filiale (sens = −1 pour les retirer)."""
        k = 1 if sens > 0 else -1
        mult = {"capa": "capa_mult", "portee": "portee", "loyer": "loyer_mult", "cout": "cout_unitaire",
                "churn": "churn_mult", "mkt": "mkt_mult", "ops": "ops_mult"}
        for n, x in effets.items():
            if n in mult:
                setattr(self, mult[n], getattr(self, mult[n]) * (1 + x) ** k)
            elif n == "qualite" and sens > 0:
                self.qualite = min(100.0, self.qualite + x)
            elif n == "notoriete" and sens > 0:
                self.notoriete = min(100.0, self.notoriete + x)
            elif n == "satisfaction":
                self.bonus_satisfaction += x * k
            elif n == "maturite" and sens > 0 and hasattr(self.act, "maturite"):
                self.act.maturite = min(100.0, self.act.maturite + x)
            elif n == "exclusivite" and sens > 0 and hasattr(self.act, "exclusivite"):
                self.act.exclusivite = min(100.0, self.act.exclusivite + x)
            elif n == "amont":
                self.amont = sens > 0 or any(f.effets.get("amont") for f in self.filiales)
            elif n not in ("qualite", "notoriete", "maturite", "exclusivite"):
                self.bonus_effets[n] = self.bonus_effets.get(n, 0.0) + x * k

    # ------------------------------------------------------------ un mois
    def preparer(self, marketing: float, qualite_inv: float) -> None:
        """Effet des décisions du mois sur la notoriété et la qualité."""
        s = self.s
        self.mkt, self.qinv = marketing, qualite_inv
        self.notoriete += (s.noto_gain * math.log1p(marketing * self.mkt_mult * (1 + self.effet("mkt")) / s.noto_echelle)
                           - self.notoriete * s.noto_declin + self.effet("notoriete"))
        self.notoriete = max(0.0, min(100.0, self.notoriete))
        charge_prev = self.historique[-1]["utilisation"] if self.historique else 0.5
        self.qualite += (2.5 * math.log1p(qualite_inv / s.qual_echelle) + 1 + (self.moral - 60) / 40
                         - self.qualite * 0.05 + self.effet("qualite"))
        self.moral = max(0.0, min(100.0, self.moral + self.effet("moral")))
        if charge_prev > 1.05 and s.modele not in ("industrie", "energie"):
            self.qualite -= 3                      # équipe débordée : le travail se dégrade
        self.qualite = max(0.0, min(100.0, self.qualite))
        self.act.preparer()

    def attrait(self) -> float:
        return self.act.attrait()

    def base_credit_impot(self) -> float:
        b = self.s.base_credit
        if b == "recherche":
            return self.qinv + self.periode["pl"]["operations"]
        if b == "developpement":
            return self.qinv + self.masse_salariale()
        return self.qinv

    def cloturer(self, demande: float, mois_cal: int, date_txt: str, marche: "Marche") -> list[str]:
        """Activité, compte de résultat et trésorerie du mois."""
        s = self.s
        rapport = []
        infos = []
        t = len(self.historique)                   # numéro du mois, pour les échéances
        self.encaisser_creances(t)
        self.payer_fournisseurs(t)
        op = self.act.exploiter(demande, mois_cal, t, marche)
        ventes, capa, utilisation, manques = op["ventes"], op["capacite"], op["utilisation"], op["manques"]
        ratio_prix = self.prix / s.prix_ref if s.prix_ref else 1.0
        cible = (40 + self.bonus_satisfaction + self.qualite * 0.5 - max(0, ratio_prix - 1) * 30 * (s.modele != "luxe")
                 - min(30, manques / max(1.0, demande or 1.0) * 80) + 3 * self.effet("satisfaction"))
        self.satisfaction += (cible - self.satisfaction) * 0.3
        if utilisation > 1.05:
            self.moral -= 6
        elif utilisation < 0.5 and s.modele in ("industrie", "luxe", "distribution", "saas"):
            self.moral -= 1
        else:
            self.moral += 2
        self.moral = max(0.0, min(100.0, self.moral))

        # charges communes
        ca_mois = self.periode["pl"]["ca"]
        self.charge("salaires", self.masse_salariale() + s.salaire_dirigeant + ca_mois * self.taux_commission(),
                    "salaires")
        self.charge("loyer", s.loyer * self.loyer_mult, "charges")
        self.charge("marketing", self.mkt, "charges")
        self.charge("qualite", self.qinv, "charges")
        self.cii_annee += self.base_credit_impot() * s.credit_impot
        self.charge("divers", s.frais_generaux, "charges")
        for cb in self.credits_bail:
            self.charge("credit_bail", cb["loyer"], "charges")
            cb["restant"] -= 1
            if cb["restant"] <= 0:
                infos.append(f"🔑 Crédit-bail terminé : « {cb['libelle']} » vous appartient désormais.")
        self.credits_bail = [cb for cb in self.credits_bail if cb["restant"] > 0]
        for im in self.immos:                      # amortissements (charge sans sortie d'argent)
            d = min(im["brut"] / im["duree"], im["brut"] - im["amorti"])
            if d > 0:
                im["amorti"] += d
                self.comptabiliser("dotations", d)
        # résultat financier
        for p in self.prets:
            if p.variable:
                p.taux = max(0.0, self.taux_ref + p.marge)
                if p.differe <= 0:
                    p.mensualite = annuite(p.capital_restant, p.taux, p.restant)
            self.charge("charges_fin", p.interets_mois(), "financier")
        agios = -self.periode["tresorerie_debut"] * TAUX_DECOUVERT / 12 if self.periode["tresorerie_debut"] < 0 else 0.0
        if agios:
            self.charge("charges_fin", agios, "financier")
        if self.placements:
            self.produit("produits_fin", self.placements * TAUX_LIVRET / 12, "financier")
        # remboursement du capital des emprunts
        for p in self.prets:
            if p.differe > 0:
                p.differe -= 1
                if p.differe == 0:
                    p.mensualite = annuite(p.capital_restant, p.taux, p.restant)
                continue
            amort = p.amortissement_mois()
            p.restant = max(0, p.restant - 1)
            if p.capital_restant - amort <= 1 or p.restant == 0:
                amort = p.capital_restant            # on solde le reliquat
            p.capital_restant -= amort
            self.mouvement(-amort, "remboursements")
        self.prets = [p for p in self.prets if p.capital_restant > 0]

        # impôt : solde de l'exercice précédent payé en mai, crédit d'impôt remboursé
        if mois_cal == MOIS_SOLDE_IS:
            if self.dette_fiscale:
                infos.append(f"🧾 Solde de l'impôt sur les sociétés payé : {fmt(self.dette_fiscale)}.")
                self.mouvement(-self.dette_fiscale, "impots")
                self.dette_fiscale = 0.0
            if self.credit_impot:
                infos.append(f"🧾 L'État vous rembourse votre crédit d'impôt : {fmt(self.credit_impot)}.")
                self.mouvement(self.credit_impot, "impots")
                self.credit_impot = 0.0
        cloture = None
        if mois_cal == 11:                         # clôture de l'exercice
            cloture = self.cloturer_exercice(date_txt.split()[-1])

        pl = self.periode["pl"]
        sd = soldes(pl)
        rapport.append(f"— {date_txt.capitalize()} —")
        vol = f"{fmt_n(ventes)} {s.unite} · " if ventes and s.modele not in ("aero", "biotech") else ""
        rapport.append(f"{vol}CA {fmt(pl['ca'])} · EBE {fmt(sd['ebe'], signe=True)} · "
                       f"résultat net {fmt(sd['net'], signe=True)}")
        if manques > 1 and s.modele in ("industrie", "saas", "luxe", "distribution"):
            rapport.append(f"⚠ Demande non servie : {fmt_n(manques)} {s.unite} (capacité insuffisante, clients "
                           "déçus).")
        rapport += op.get("messages", [])
        if agios:
            rapport.append(f"🏦 Compte à découvert : {fmt(agios)} d'agios ce mois-ci (12 % par an).")
        rapport += infos
        if cloture:
            rapport.append(cloture)
        rapport += self.vie_equipe(ratio_prix)
        if self.joueur:
            self.renouveler_vivier()
        if self.penurie:
            self.penurie -= 1
        if self.refus_rachat:
            self.refus_rachat -= 1
        self.historique.append({
            "ca": pl["ca"], "resultat": sd["net"], "rcai": sd["rcai"], "ebe": sd["ebe"], "rex": sd["rex"],
            "tresorerie": self.tresorerie, "tresorerie_debut": self.periode["tresorerie_debut"],
            "ventes": ventes, "utilisation": utilisation, "prix": self.prix, "part": 0.0, "valorisation": 0.0,
            "pl": dict(pl), "flux": dict(self.periode["flux"]), "details": list(self.periode["details"]),
            "bilan": self.bilan_comptable(), "date": date_txt, "kpi": self.act.metriques()})
        ancienne = self.note
        self.note = self.notation()
        self.historique[-1]["note"] = self.note
        if self.joueur and ancienne != self.note:
            mieux = "ABCDE".index(self.note) < "ABCDE".index(ancienne)
            rapport.append(f"🏦 Votre banque {'relève' if mieux else 'abaisse'} votre note de crédit : "
                           f"{ancienne} → {self.note} ({NOTES_TXT[self.note].lower()}).")
        self.nouvelle_periode()
        return rapport

    def cloturer_exercice(self, annee: str) -> str:
        """Fin d'exercice : impôt sur les sociétés (après report des déficits et crédit d'impôt),
        puis affectation du résultat en réserves."""
        rai = soldes(self.exercice)["rai"]
        base = rai
        if base < 0:
            self.deficit_reportable += -base
            base = 0.0
        else:
            imput = min(self.deficit_reportable, base)
            self.deficit_reportable -= imput
            base -= imput
        impot = min(base, SEUIL_IS) * 0.15 + max(0.0, base - SEUIL_IS) * 0.25
        cii = self.cii_annee
        net_is = impot - cii
        self.comptabiliser("impot", net_is)
        if net_is >= 0:
            self.dette_fiscale += net_is
        else:
            self.credit_impot += -net_is
        self.impots_payes += impot
        net = soldes(self.exercice)["net"]
        self.exercices.append({"annee": annee, "pl": dict(self.exercice), "impot_brut": impot, "cii": cii,
                               "base": base, "deficit": self.deficit_reportable})
        self.reserves += net
        self.exercice = pl_vide()
        self.cii_annee = 0.0
        return (f"🧾 Clôture de l'exercice {annee} : résultat avant impôt {fmt(rai, signe=True)}, "
                f"impôt sur les sociétés {fmt(impot)}, crédit d'impôt {fmt(cii)} → "
                + (f"{fmt(net_is)} à payer en mai" if net_is >= 0 else f"{fmt(-net_is)} remboursés par l'État en mai")
                + f". Résultat net {fmt(net, signe=True)}, mis en réserve."
                + (f" Déficit reportable : {fmt(self.deficit_reportable)}." if self.deficit_reportable else ""))

    def verifier_solvabilite(self) -> str | None:
        """Trésorerie sous le découvert autorisé : placements débloqués d'abord, puis un prêt d'urgence
        une seule fois, puis la faillite."""
        msg = None
        if self.tresorerie < 0 and self.placements > 0:
            x = min(self.placements, -self.tresorerie)
            self.placements -= x
            self.mouvement(x, "placements")
            msg = "retrait:" + fmt(x)
        if self.tresorerie >= -self.decouvert_autorise():
            return msg
        if not self.aide_urgence_utilisee and self.ca_annualise() > 20_000 * self.s.echelle:
            besoin = math.ceil((-self.tresorerie + self.charges_fixes()) / 1000) * 1000
            self.aide_urgence_utilisee = True
            self.incidents += 1
            self.prets.append(nouveau_pret(besoin, NOTES["D"][0], libelle="Prêt d'urgence"))
            self.mouvement(besoin, "emprunts")
            self.note = self.notation()
            return "urgence:" + fmt(besoin)
        self.actif = False
        self.fin_raison = "faillite"
        return "faillite"

    # ------------------------------------------------------------ filiales
    def activite_filiales(self, saison: float, conjoncture: float) -> None:
        """Chiffre d'affaires et charges du mois des filiales (comptabilité consolidée)."""
        self.ca_filiales = 0.0
        for f in self.filiales:
            ca = f.ca * saison * conjoncture * self.rng.uniform(0.9, 1.1)
            couts = ca * (1 - f.marge)
            self.produit("ca", ca, "clients")
            self.charge("achats", couts * 0.6, "fournisseurs")
            self.charge("salaires", couts * 0.4, "salaires")
            self.ca_filiales += ca
            if f.type == "complementaire":
                f.ca *= 1.01                       # les ventes croisées font grandir l'activité

    def reprendre_bilan(self, f: Filiale, prix: float, date_txt: str) -> float:
        """Écritures du rachat : prix payé, trésorerie, matériel et dettes repris, écart d'acquisition."""
        self.mouvement(-prix, "acquisitions")
        self.mouvement(f.tresorerie, "acquisitions")
        f.immo_ref = {"libelle": f"Matériel de {f.nom}", "brut": f.immos, "amorti": 0.0, "duree": DUREE_AMORT}
        self.immos.append(f.immo_ref)
        if f.dette > 0:
            f.pret_ref = nouveau_pret(f.dette, 0.05, 60, f"Dette reprise de {f.nom}")
            self.prets.append(f.pret_ref)
        ecart = prix - (f.tresorerie + f.immos - f.dette)
        if ecart >= 0:
            f.goodwill = ecart
            self.goodwill += ecart
        else:
            self.comptabiliser("exceptionnel", -ecart)
            self.periode["details"].append((f"Rachat de {f.nom} sous sa valeur comptable", -ecart))
        f.acquise_le = date_txt
        return ecart

    def financer(self, montant: float) -> str:
        """Mobilise placements puis emprunt pour pouvoir payer un montant."""
        emprunt = ""
        coussin = self.charges_fixes()
        if montant > self.tresorerie - coussin and self.placements:
            self.retirer(montant - self.tresorerie + coussin)
        if montant > self.tresorerie - coussin:
            besoin = min(self.capacite_emprunt(), math.ceil((montant - self.tresorerie + coussin) / 1000) * 1000)
            if besoin >= 1000:
                self.emprunter(besoin)
                emprunt = f" (dont {fmt(besoin)} empruntés)"
        return emprunt

    def racheter_cible(self, f: Filiale, prix: float, date_txt: str) -> str:
        """Rachat d'une cible : filiale (revenus et effet durable) ou fusion pour un concurrent de niche."""
        emprunt = self.financer(prix)
        ecart = self.reprendre_bilan(f, prix, date_txt)
        gw = (f"écart d'acquisition de {fmt(ecart)} inscrit au bilan" if ecart >= 0
              else f"achetée sous sa valeur comptable : {fmt(-ecart)} de produit exceptionnel")
        if f.type == "niche":                       # fusion : clients et équipe intégrés
            for _ in range(f.salaries):
                e = self.equipier()
                e.origine = f.nom
                self.equipe.append(e)
            apport = self.act.fusion_niche(f)
            self.notoriete = min(100.0, self.notoriete + 5)
            self.moral = max(0.0, self.moral - 4)
            return (f"Rachat de {f.nom} pour {fmt(prix)}{emprunt} : fusion réussie. Vous récupérez {apport} et "
                    f"{f.salaries} salarié(s) ; {gw}.")
        self.filiales.append(f)
        self.appliquer_effets(f.effets)
        return (f"{f.nom} devient votre filiale pour {fmt(prix)}{emprunt} : {f.effet[0].lower()}{f.effet[1:]} "
                f"Elle apporte environ {fmt(f.ca)} de chiffre d'affaires par mois ; {gw}.")

    def offre_cession(self, f: Filiale) -> float:
        """Prix proposé par un acheteur : valeur d'entreprise, moins la dette qu'il reprend (la trésorerie de la
        filiale est déjà fondue dans la vôtre)."""
        dette = f.pret_ref.capital_restant if f.pret_ref in self.prets else 0.0
        return max(0.0, round((f.valeur_entreprise(self.s.multiple) - dette) * 0.95 / 1000) * 1000)

    def cout_developpement(self, f: Filiale) -> float:
        return round(max(8_000 * self.s.echelle, f.ca * 4) * (1 + 0.5 * f.niveau) / 1000) * 1000

    def developper_filiale(self, f: Filiale) -> str:
        """Investir dans une filiale : nouveaux moyens (matériel, recrutements, marketing) → +25 % d'activité et
        une marge un peu meilleure. L'investissement est immobilisé et amorti sur 5 ans."""
        if f not in self.filiales:
            return "Cette filiale n'est plus à vous."
        if f.niveau >= 3:
            return f"{f.nom} est déjà développée au maximum."
        cout = self.cout_developpement(f)
        if cout > self.tresorerie:
            return f"Trésorerie insuffisante : il faut {fmt(cout)} pour développer {f.nom}."
        self.investir(f"Développement de {f.nom} ({f.niveau + 1})", cout)
        f.dev_refs.append(self.immos[-1])
        f.niveau += 1
        f.investi += cout
        f.ca *= 1.25
        f.marge = min(0.35, f.marge + 0.03)
        return (f"{f.nom} se développe ({f.niveau}/3) : {fmt(cout)} investis, activité +25 % (≈ {fmt(f.ca)} de "
                f"chiffre d'affaires par mois) et marge améliorée.")

    def vendre_filiale(self, f: Filiale) -> str:
        """Cession : l'acheteur paie et reprend le matériel et la dette ; plus- ou moins-value exceptionnelle."""
        if f not in self.filiales:
            return "Cette filiale n'est plus à vous."
        prix = self.offre_cession(f)
        immo = 0.0
        for ref in [f.immo_ref] + list(f.dev_refs):
            if ref in self.immos:
                immo += ref["brut"] - ref["amorti"]
                self.immos.remove(ref)
        dette = 0.0
        if f.pret_ref in self.prets:
            dette = f.pret_ref.capital_restant
            self.prets.remove(f.pret_ref)
        self.goodwill -= f.goodwill
        pv = prix - (immo + f.goodwill - dette)
        self.mouvement(prix, "acquisitions")
        self.comptabiliser("exceptionnel", pv)
        self.periode["details"].append((f"Cession de {f.nom}", pv))
        self.filiales.remove(f)
        self.appliquer_effets(f.effets, -1)
        return (f"{f.nom} est vendue {fmt(prix)}"
                + (f" (l'acheteur reprend {fmt(dette)} de dettes)" if dette else "")
                + f" : {'plus' if pv >= 0 else 'moins'}-value de {fmt(abs(pv))}.")

    def vider(self) -> None:
        """Après un rachat : tout le patrimoine est passé à l'acquéreur."""
        self.tresorerie = self.capital = self.reserves = self.goodwill = 0.0
        self.placements = self.dette_fiscale = self.credit_impot = self.deficit_reportable = 0.0
        self.stocks = self.encours = self.avances = 0.0
        self.prets, self.immos, self.creances, self.dettes_fourn, self.credits_bail = [], [], [], [], []
        self.exercice = pl_vide()
        self.equipe, self.abonnes = [], 0.0

    # ------------------------------------------------------------ pilotage automatique (concurrents)
    def burn(self) -> float:
        """Ce que l'entreprise brûle chaque mois (hors financement), en moyenne sur 3 mois ; 0 si elle gagne de
        l'argent."""
        der = self.mois_reels()[-3:]
        if not der:
            return self.charges_fixes()
        flux = sum(sum(h["flux"][k] for k in FLUX_EXPLOITATION + ("investissements",)) for h in der) / len(der)
        return max(0.0, -flux)

    def decider(self, marche: "Marche", force: float) -> None:
        st, s = self.strategie, self.s
        h = self.historique[-1] if self.historique else None
        self.act.decider_ia(marche, force)
        # financement : emprunt si la trésorerie devient juste, levée de fonds si l'autonomie est courte
        fixes = self.charges_fixes()
        if self.tresorerie < 2 * fixes and self.capacite_emprunt() >= fixes:
            self.emprunter(min(self.capacite_emprunt(), 6 * fixes))
        brule = self.burn()
        horizon = 12 if st.cle == "startup" else 8
        if brule > 0 and (self.tresorerie + self.placements) < horizon * brule:
            c = self.conditions_levee()
            if c:
                self.lever(min(c["maxi"], max(c["mini"], 18 * brule)))
                marche.nouvelles.append(f"💼 {self.nom} lève des fonds.")
        # copie les investissements du joueur qui semblent lui réussir
        j = marche.joueur
        if h and j.actif:
            for c, niv in j.ameliorations.items():
                if (self.ameliorations.get(c, 0) < niv and self.peut_ameliorer(c)
                        and self.tresorerie > 2 * self.cout_amelioration(c) and self.rng.random() < 0.12):
                    self.ameliorer(c)
                    marche.nouvelles.append(f"🏗 {self.nom} copie votre stratégie : "
                                            f"{self.ameliorations_secteur()[c].nom.lower()}.")
                    break
        # investissements stratégiques quand la trésorerie le permet
        if h and self.rng.random() < 0.08:
            choix = [c for c in self.ameliorations_secteur() if self.peut_ameliorer(c)
                     and self.tresorerie > 3 * self.cout_amelioration(c) + 6 * fixes]
            if choix:
                c = self.rng.choice(choix)
                self.ameliorer(c)
                marche.nouvelles.append(f"🏗 {self.nom} investit : {self.ameliorations_secteur()[c].nom.lower()}.")
        # budgets
        mk, q = self.act.budgets_ia(force)
        if self.riposte_mkt:
            mk *= 1.6
            self.riposte_mkt -= 1
        if self.tresorerie < 2 * fixes and s.modele in ("industrie", "saas", "luxe", "distribution"):
            mk, q = mk * 0.4, q * 0.4
        self.mkt_prevu, self.q_prevu = mk, q


# =============================================================================
class Marche:
    def __init__(self, nom_joueur: str, secteur: str, pret_initial: float = 0.0, nb_concurrents: int = 3,
                 difficulte: str = "Normal", graine: int | None = None, duree: int = DUREE):
        self.rng = random.Random(graine)
        self.s = SECTEURS[secteur]
        self.force = DIFFICULTES.get(difficulte, 1.0)
        self.difficulte = difficulte
        self.duree = duree
        self.mois = 0
        self.conjoncture, self.duree_conjoncture = 1.0, 0
        self.nouvelles: list[str] = []
        self.journal: list[str] = []
        self.fin: str | None = None
        self.prix_rachat: float | None = None
        self.acquereur: str | None = None
        self.chaines: list[dict] = []          # événements en plusieurs étapes en cours
        self.opportunites: list[Filiale] = []  # entreprises à vendre (fournisseurs, sous-traitants…)
        self.cibles_vendues: set[str] = set()
        self.chaines_faites: set[str] = set()
        self.confinement = 0                   # mois de confinement restants
        # --- environnement économique
        self.taux_ref = TAUX_REF_INITIAL       # taux interbancaire : il se répercute sur tous les crédits
        self.spot = 72.0                       # prix de gros de l'électricité (€/MWh)
        self.spot_hist: list[float] = [72.0]
        self.spot_cible, self.duree_crise_energie = 72.0, 0
        self.taxe_rente = False
        self.appels: list[AppelOffres] = []    # appels d'offres en cours (aéronautique)
        self.appels_clos: list[AppelOffres] = []
        self.prochain_ao = 1
        self.enchere: dict | None = None       # appel d'offres de l'État pour les contrats d'électricité
        self.poids_lancements = 0.0            # jeux vidéo qui sortent ce mois-ci
        self.joueur = Entreprise(nom_joueur or "Ma Boîte", self.s, COULEURS[0], APPORT, pret_initial, rng=self.rng)
        self.joueur.marche_ref = self
        self.entreprises = [self.joueur]
        noms = list(self.s.noms)
        self.rng.shuffle(noms)
        ordre = ["equilibre", "lowcost", "premium", "startup", "lowcost"]
        for i in range(nb_concurrents):
            self.ajouter_concurrent(noms[i], STRATEGIES[ordre[i]])
        self.noms_libres = noms[nb_concurrents:]

    def ajouter_concurrent(self, nom: str, st: Strategie) -> Entreprise:
        s = self.s
        e = Entreprise(nom, s, COULEURS[len(self.entreprises) % len(COULEURS)], APPORT, s.pret_conseille, st,
                       self.rng)
        if self.force > 1.0:                          # difficulté : des concurrents mieux financés
            bonus = (s.investisseurs + APPORT) * (self.force - 1)
            e.capital += bonus
            e.mouvement(bonus, "levees")
        e.marche_ref = self
        e.taux_ref = self.taux_ref
        if self.mois:                                 # arrivée en cours de partie : un peu de notoriété d'emblée
            e.notoriete = max(e.notoriete, 15)
        e.historique = [dict(ca=0, resultat=0, tresorerie=e.tresorerie, ventes=0, utilisation=0.5,
                             prix=e.prix, part=0.0, valorisation=0.0, absent=True) for _ in range(self.mois)]
        if isinstance(e.act, ActiviteAero):
            for c in e.act.contrats:
                c.debut += self.mois
                c.echeance += self.mois
        self.entreprises.append(e)
        return e

    @property
    def actives(self) -> list[Entreprise]:
        return [e for e in self.entreprises if e.actif]

    @property
    def concurrents(self) -> list[Entreprise]:
        return [e for e in self.entreprises if not e.joueur]

    def date(self, decalage: int = 0) -> str:
        m = self.mois + decalage
        return f"{MOIS_NOMS[m % 12]} {2027 + m // 12}"

    def spot_moyen(self) -> float:
        h = self.spot_hist[-6:]
        return sum(h) / len(h)

    # ------------------------------------------------------------ rachats de concurrents
    def prix_demande(self, cible: Entreprise) -> float:
        """Prix en dessous duquel les dirigeants de la cible refusent de vendre (le joueur ne le voit pas)."""
        v = max(10_000.0 * self.s.echelle, cible.valorisation())
        if cible.tresorerie < cible.charges_fixes():
            f = 0.8                                    # en difficulté : prête à vendre
        elif self.classement()[0] is cible:
            f = 1.6                                    # le leader se sait en position de force
        else:
            f = 1.3
        return v * f * cible.exigence

    def attitude(self, cible: Entreprise) -> str:
        if cible.refus_rachat:
            return f"Vient de refuser une offre : ne veut plus en entendre parler avant {cible.refus_rachat} mois."
        if cible.tresorerie < cible.charges_fixes():
            return "En difficulté : ses dirigeants sont prêts à vendre, même sous sa valeur."
        if self.classement()[0] is cible:
            return "Leader du marché : il exigera une très forte prime."
        return "En bonne santé : il faudra proposer une prime pour la convaincre."

    def offrir_rachat(self, acheteur: Entreprise, cible: Entreprise, offre: float) -> tuple[bool, str]:
        """Offre de rachat : la cible accepte si l'offre atteint son prix. L'acheteur récupère ses salariés,
        ses clients, sa notoriété, ses investissements et sa trésorerie, et reprend ses dettes."""
        if not cible.actif:
            return False, f"{cible.nom} n'existe plus."
        if cible.refus_rachat:
            return False, f"{cible.nom} refuse de discuter : revenez dans {cible.refus_rachat} mois."
        moyens = acheteur.tresorerie + acheteur.placements + acheteur.capacite_emprunt()
        if offre > moyens:
            return False, f"Financement impossible : vous ne pouvez pas mobiliser plus de {fmt(max(0, moyens))}."
        demande = self.prix_demande(cible)
        if offre < demande:
            cible.refus_rachat = 3
            pas = 10 ** max(3, int(math.log10(max(demande, 1))) - 2) * 5
            indice = math.ceil(demande * self.rng.uniform(1.0, 1.1) / pas) * pas
            return False, (f"{cible.nom} refuse votre offre de {fmt(offre)}. D'après son entourage, il faudrait "
                           f"approcher {fmt(indice)} pour la convaincre. Elle ne rediscutera pas avant 3 mois.")
        emprunt = acheteur.financer(offre)
        det = (f"{cible.salaries} salarié(s), sa trésorerie ({fmt(cible.tresorerie)}) et ses dettes "
               f"({fmt(cible.dette)})")
        ecart = self.fusionner(acheteur, cible, offre)
        for e in cible.equipe:
            e.origine = e.origine or cible.nom
            e.moral = min(e.moral, 60.0)
        acheteur.equipe += cible.equipe
        acheteur.abonnes += cible.abonnes
        acheteur.notoriete = min(100.0, max(acheteur.notoriete, cible.notoriete) + 0.25 * min(acheteur.notoriete,
                                                                                               cible.notoriete))
        extra = self.fusionner_activites(acheteur, cible)
        recup = []
        for c, niv in cible.ameliorations.items():
            while acheteur.ameliorations.get(c, 0) < min(niv, acheteur.ameliorations_secteur()[c].niveaux):
                acheteur.appliquer_amelioration(c)
                recup.append(acheteur.ameliorations_secteur()[c].nom.lower())
        acheteur.portee *= 1.10                        # la clientèle et les implantations de la cible
        acheteur.moral = max(0.0, acheteur.moral - 5)  # l'intégration des équipes bouscule tout le monde
        cible.actif = False
        cible.fin_raison = "rachetée par vous" if acheteur.joueur else f"rachetée par {acheteur.nom}"
        cible.vider()
        det += f", ses investissements ({', '.join(recup)})" if recup else ""
        det += extra
        if acheteur.joueur:
            msg = (f"Rachat de {cible.nom} pour {fmt(offre)}{emprunt} ! Vous récupérez {det}. "
                   + (f"Écart d'acquisition (goodwill) inscrit au bilan : {fmt(ecart)}." if ecart >= 0 else
                      f"Vous l'achetez sous sa valeur comptable : {fmt(-ecart)} de produit exceptionnel."))
        else:
            msg = f"🤝 {acheteur.nom} rachète {cible.nom}."
        return True, msg

    @staticmethod
    def fusionner_activites(acheteur: Entreprise, cible: Entreprise) -> str:
        """Reprend ce qui fait l'activité de la cible : usines, molécules, projets, contrats, centrales…"""
        a, c = acheteur.act, cible.act
        if isinstance(a, ActiviteIndustrie):
            for u in c.usines:
                a.usines.append(dict(u, nom=f"{u['nom']} ({cible.nom})"))
            return ", ses usines"
        if isinstance(a, ActiviteBiotech):
            vivantes = [m for m in c.molecules if m.statut not in ("echec", "abandonne")]
            a.molecules += vivantes
            return f", ses {len(vivantes)} molécule(s)" if vivantes else ""
        if isinstance(a, ActiviteJeu):
            a.catalogue += c.catalogue
            if c.projet and not a.projet:
                a.projet = c.projet
            elif c.projet and c.projet.editeur and c.projet.editeur["restant"] > 0:
                reste = c.projet.editeur["restant"]           # projet abandonné : on rembourse son éditeur
                acheteur.avances -= reste
                acheteur.mouvement(-reste, "fournisseurs")
            return ", ses jeux"
        if isinstance(a, ActiviteAero):
            a.contrats += c.actifs()
            return f", ses contrats ({fmt_c(c.carnet())} de carnet)"
        if isinstance(a, ActiviteEnergie):
            a.centrales += c.centrales
            a.projets += c.projets
            return f", ses centrales ({sum(x.mw for x in c.centrales):.0f} MW)"
        if isinstance(a, ActiviteLuxe):
            a.exclusivite = (a.exclusivite + c.exclusivite) / 2
        if isinstance(a, ActiviteSaaS):
            a.maturite = max(a.maturite, c.maturite)
        return ""

    @staticmethod
    def fusionner(acheteur: Entreprise, cible: Entreprise, prix: float) -> float:
        """Reprise de tout l'actif et de tout le passif de la cible. L'écart entre le prix payé et ses capitaux
        propres devient un goodwill (ou, s'il est négatif, un produit exceptionnel). Renvoie cet écart."""
        acheteur.mouvement(-prix, "acquisitions")
        acheteur.mouvement(cible.tresorerie, "acquisitions")           # trésorerie récupérée
        acheteur.placements += cible.placements
        acheteur.stocks += cible.stocks
        acheteur.encours += cible.encours
        acheteur.avances += cible.avances
        acheteur.creances += cible.creances
        acheteur.dettes_fourn += cible.dettes_fourn
        acheteur.prets += cible.prets
        acheteur.dette_fiscale += cible.dette_fiscale
        acheteur.credit_impot += cible.credit_impot
        acheteur.credits_bail += [dict(c, libelle=f"{c['libelle']} ({cible.nom})") for c in cible.credits_bail]
        acheteur.immos += [dict(i, libelle=f"{i['libelle']} ({cible.nom})") for i in cible.immos if i["brut"] > i["amorti"]]
        acheteur.goodwill += cible.goodwill
        # capitaux propres de la cible = actif net repris (les immobilisations amorties n'ont plus de valeur)
        ecart = prix - cible.capitaux_propres
        if ecart >= 0:
            acheteur.goodwill += ecart
        else:
            acheteur.comptabiliser("exceptionnel", -ecart)
            acheteur.periode["details"].append((f"Rachat de {cible.nom} sous sa valeur comptable", -ecart))
        return ecart

    # ------------------------------------------------------------ croissance externe
    def nouvelle_opportunite(self) -> Filiale | None:
        r, s = self.rng, self.s
        cat = CIBLES.get(s.cle)
        if not cat:
            return None
        deja = {f.type for f in self.opportunites}
        types = [t for t in TYPES_CIBLE if t not in deja]
        if not types:
            return None
        t = r.choice(types)
        metier, noms = cat[t]
        libres = [n for n in noms if n not in self.cibles_vendues and all(f.nom != n for f in self.opportunites)]
        if not libres:
            return None
        nom = r.choice(libres)
        _, taille, marge, _ = TYPES_CIBLE[t]
        ca = round(s.ca_cible * taille * r.uniform(0.7, 1.4) / 1000) * 1000
        marge = marge + r.uniform(-0.05, 0.05)
        salaries = max(1, round(ca / (4 * s.salaire) * r.uniform(0.6, 1.0)))
        immos = round(ca * 4 * r.uniform(0.5, 1.2) / 1000) * 1000
        treso = round(ca * r.uniform(0.2, 1.0) / 1000) * 1000
        dette = round(immos * r.uniform(0.0, 0.8) / 1000) * 1000
        texte, effets = effet_cible(s.modele, t)
        f = Filiale(nom, t, metier, ca, round(marge, 3), salaries, treso, dette, immos, 0.0,
                    dispo=r.randint(3, 5), effet=texte, effets=dict(effets))
        pas = 10 ** max(3, int(math.log10(max(f.valeur(s.multiple), 1))) - 1)
        f.prix = max(15_000, round(f.valeur(s.multiple) * r.uniform(1.1, 1.35) / pas) * pas)
        return f

    def flux_opportunites(self) -> None:
        """Chaque mois, des entreprises se mettent en vente ; celles que personne n'achète peuvent partir
        chez un concurrent."""
        r = self.rng
        restantes = []
        for f in self.opportunites:
            f.dispo -= 1
            if f.dispo > 0:
                restantes.append(f)
                continue
            riches = [e for e in self.concurrents if e.actif and e.tresorerie > f.prix + 6 * e.charges_fixes()]
            if riches and r.random() < 0.45:
                e = r.choice(riches)
                texte, effets = effet_cible(self.s.modele, f.type)
                f.effet, f.effets = texte, dict(effets)
                e.racheter_cible(f, f.prix, self.date(-1))
                self.cibles_vendues.add(f.nom)
                self.nouvelles.append(f"🏢 {e.nom} rachète {f.nom} ({f.metier.lower()}) : {f.effet[0].lower()}"
                                      f"{f.effet[1:]}")
            else:
                self.nouvelles.append(f"ℹ {f.nom} n'est plus à vendre.")
        self.opportunites = restantes
        if self.mois >= 2 and len(self.opportunites) < 3 and r.random() < (0.6 if not self.opportunites else 0.3):
            f = self.nouvelle_opportunite()
            if f:
                self.opportunites.append(f)
                self.nouvelles.append(f"🏷 À vendre : {f.nom}, {f.metier.lower()} ({f.libelle_type.lower()}), "
                                      f"pour {fmt(f.prix)}. Voir la page Rachats.")

    def offrir_cible(self, f: Filiale, offre: float) -> tuple[bool, str]:
        """Offre du joueur sur une entreprise à vendre."""
        j = self.joueur
        if f not in self.opportunites:
            return False, f"{f.nom} n'est plus à vendre."
        moyens = j.tresorerie + j.placements + j.capacite_emprunt()
        if offre > moyens:
            return False, f"Financement impossible : vous ne pouvez pas mobiliser plus de {fmt(max(0, moyens))}."
        if self.rng.random() > chance_acceptation(offre / f.prix):
            f.refus += 1
            if f.refus >= 2:
                self.opportunites.remove(f)
                return False, f"{f.nom} refuse encore votre offre et se retire des négociations."
            f.prix = round(f.prix * 1.05 / 1000) * 1000
            return False, (f"Les vendeurs de {f.nom} refusent {fmt(offre)} et se braquent : ils demandent maintenant "
                           f"{fmt(f.prix)}. Une seconde offre refusée, et ils se retirent.")
        self.opportunites.remove(f)
        self.cibles_vendues.add(f.nom)
        return True, j.racheter_cible(f, offre, self.date())

    def prix_moyen_concurrents(self) -> float | None:
        p = [e.prix for e in self.concurrents if e.actif]
        return sum(p) / len(p) if p else None

    # ------------------------------------------------------------ environnement économique
    def evoluer_macro(self) -> None:
        r = self.rng
        # taux de référence : il dérive lentement ; la banque centrale agit parfois par à-coups (événements)
        self.taux_ref = max(0.0, min(0.08, self.taux_ref + r.gauss(0, 0.0008) + 0.02 * (0.03 - self.taux_ref)))
        # prix de gros de l'électricité : il revient vers sa cible, avec des à-coups
        if self.duree_crise_energie:
            self.duree_crise_energie -= 1
            if not self.duree_crise_energie:
                self.spot_cible = 72.0
                if self.s.modele == "energie":
                    self.nouvelles.append("ℹ Les prix de l'électricité se détendent.")
        cible = self.spot_cible * (0.85 + 0.15 * self.conjoncture)
        self.spot = max(15.0, min(400.0, self.spot + 0.25 * (cible - self.spot) + r.gauss(0, 6)))
        self.spot_hist.append(self.spot)
        self.spot_hist = self.spot_hist[-24:]

    def processus_secteur(self) -> None:
        """Ce qui se joue à l'échelle du secteur avant la clôture du mois."""
        m = self.s.modele
        if m == "aero":
            self.appels_d_offres()
        elif m == "energie":
            self.encheres_electricite()
        elif m == "jeu":
            self.poids_lancements = sum(e.act.lancements_prevus() for e in self.actives)

    def appels_d_offres(self) -> None:
        r, t = self.rng, self.mois
        for ao in [a for a in self.appels if a.decision <= t]:
            self.appels.remove(ao)
            self.attribuer(ao)
        if r.random() < 0.40 * self.conjoncture + 0.05 * len(self.actives):
            objet, k = r.choice(OBJETS_AERO)
            montant = round(math.exp(r.uniform(math.log(2_500_000), math.log(24_000_000))) * k / 100_000) * 100_000
            duree = int(min(30, 12 + montant / 1_500_000))
            ao = AppelOffres(self.prochain_ao, r.choice(CLIENTS_AERO), objet, montant, montant / PRODUCTIVITE_AERO, duree,
                             t + r.randint(3, 5), min(85.0, 10 + montant / 450_000))
            self.prochain_ao += 1
            self.appels.append(ao)
            for e in self.concurrents:
                if e.actif and isinstance(e.act, ActiviteAero) and e.notoriete >= ao.exigence:
                    charge = e.act.charge_prevue(t) + ao.charge / ao.duree
                    if charge < 1.6 * e.act.capacite() and r.random() < 0.8:
                        marge = {"lowcost": 0.88, "equilibre": 0.98, "premium": 1.07, "startup": 0.93}[e.strategie.cle]
                        ao.offres[e.nom] = round(ao.montant * marge * r.uniform(0.96, 1.04) / 10_000) * 10_000
            if self.joueur.actif and self.joueur.notoriete >= ao.exigence:
                self.nouvelles.append(f"📣 Appel d'offres : {ao.client} cherche « {ao.objet} » ({fmt_c(ao.montant)}, "
                                      f"{ao.duree} mois). Réponse avant {self.date(ao.decision - t)}.")

    def deposer_offre(self, ao: AppelOffres, prix: float) -> str:
        j = self.joueur
        if ao not in self.appels:
            return "Cet appel d'offres est clos."
        if j.notoriete < ao.exigence:
            return (f"Votre crédibilité technique ({j.notoriete:.0f}) est trop faible : {ao.client} exige "
                    f"{ao.exigence:.0f}.")
        ao.offres[j.nom] = prix
        return f"Offre déposée auprès de {ao.client} pour « {ao.objet} » : {fmt(prix)}. Décision en {self.date(ao.decision - self.mois)}."

    def attribuer(self, ao: AppelOffres) -> None:
        r, t = self.rng, self.mois
        candidats = []
        for e in self.actives:
            if e.nom in ao.offres and isinstance(e.act, ActiviteAero):
                candidats.append((e.act.score_offre(ao, ao.offres[e.nom], t, r), e, ao.offres[e.nom]))
        prix_ext = ao.montant * r.uniform(0.93, 1.08)
        score_ext = (ao.montant / prix_ext) ** 3 * 1.15 * 1.0 * r.uniform(0.9, 1.1)
        candidats.append((score_ext, None, prix_ext))
        candidats.sort(key=lambda x: -x[0])
        _, gagnant, prix = candidats[0]
        joueur_a_candidate = self.joueur.nom in ao.offres
        if gagnant is None:
            ao.gagnant = "un groupe étranger"
            if joueur_a_candidate:
                self.nouvelles.append(f"✖ {ao.client} attribue « {ao.objet} » à un groupe étranger.")
        else:
            ao.gagnant = gagnant.nom
            c = Contrat(ao.client, ao.objet, prix, ao.charge, t, t + ao.duree)
            gagnant.act.signer(c)
            gagnant.notoriete = min(100.0, gagnant.notoriete + 4)
            if gagnant.joueur:
                self.nouvelles.append(f"🏆 Contrat gagné ! {ao.client} vous confie « {ao.objet} » pour {fmt(prix)} "
                                      f"({ao.duree} mois). Acompte de {fmt(prix * 0.2)} encaissé.")
            elif joueur_a_candidate:
                self.nouvelles.append(f"✖ {ao.client} attribue « {ao.objet} » à {gagnant.nom} ({fmt_c(prix)}).")
            else:
                self.nouvelles.append(f"📉 {gagnant.nom} remporte « {ao.objet} » ({fmt_c(prix)}).")
        self.appels_clos.append(ao)
        self.appels_clos = self.appels_clos[-8:]

    def encheres_electricite(self) -> None:
        """Tous les 4 mois, l'État lance un appel d'offres : 20 ans de prix garanti pour les offres les moins
        chères, dans la limite d'un volume."""
        r, t = self.rng, self.mois
        e_ = self.enchere
        if e_ and e_["decision"] <= t:
            offres = sorted(e_["offres"].items(), key=lambda x: x[1][1])
            volume = e_["volume"]
            gagnants = []
            for nom, (centrale, prix) in offres:
                if volume <= 0:
                    break
                ent = next((x for x in self.actives if x.nom == nom), None)
                if not ent or centrale not in ent.act.centrales or centrale.ppa_prix is not None:
                    continue
                prix_ext = e_["prix_externe"]
                if prix > prix_ext:
                    continue
                centrale.ppa_prix, centrale.ppa_fin = prix, t + 240
                volume -= centrale.mw
                gagnants.append((ent, centrale, prix))
            for ent, centrale, prix in gagnants:
                if ent.joueur:
                    self.nouvelles.append(f"🏆 Appel d'offres remporté : « {centrale.nom} » vendra son électricité "
                                          f"{prix:.1f} €/MWh pendant 20 ans.".replace(".", ",", 1))
            if self.joueur.nom in e_["offres"] and not any(g[0].joueur for g in gagnants):
                self.nouvelles.append("✖ Votre offre à l'appel d'offres de l'État n'a pas été retenue : trop chère.")
            self.enchere = None
        if not self.enchere and t % 4 == 2:
            self.enchere = {"decision": t + 1, "volume": 80.0, "offres": {},
                            "prix_externe": round(r.uniform(58, 72), 1)}
            for e in self.concurrents:
                if e.actif and isinstance(e.act, ActiviteEnergie):
                    libres = [c for c in e.act.centrales if c.ppa_prix is None and c.type != "stockage"]
                    if libres:
                        c = libres[0]
                        marge = {"lowcost": 1.02, "equilibre": 1.08, "premium": 1.12, "startup": 1.05}[e.strategie.cle]
                        e_prix = round(e.act.lcoe(c.type) * marge * r.uniform(0.97, 1.03), 1)
                        self.enchere["offres"][e.nom] = (c, e_prix)
            if self.joueur.actif and isinstance(self.joueur.act, ActiviteEnergie):
                self.nouvelles.append("📣 L'État lance un appel d'offres : 80 MW de contrats à 20 ans. Déposez une "
                                      "offre (page Parc de centrales) avant la fin du mois.")

    def offre_enchere(self, centrale: "Centrale", prix: float) -> str:
        if not self.enchere:
            return "Aucun appel d'offres en cours."
        if centrale.ppa_prix is not None or centrale.type == "stockage":
            return "Cette centrale ne peut pas concourir."
        self.enchere["offres"][self.joueur.nom] = (centrale, prix)
        return (f"Offre déposée : « {centrale.nom} » à {prix:.1f} €/MWh. Résultat le mois prochain.".replace(".", ",", 1))

    # ------------------------------------------------------------ un mois
    def partager_demande(self, act: list[Entreprise], mois_cal: int) -> dict:
        """Plus il y a d'acteurs attractifs, plus le marché total grandit ; chacun en capte une part selon son
        attrait relatif (prix, notoriété, qualité, satisfaction)."""
        s, r = self.s, self.rng
        attraits = [e.attrait() for e in act]
        n = len(act)
        part_totale = (s.part_max * (1 + s.extension * (n - 1))
                       * (1 - math.exp(-s.saturation * sum(attraits) / max(1, n))))
        volume = (s.marche * part_totale * s.saison[mois_cal] * self.conjoncture
                  * (sum(e.portee for e in act) / max(1, n)) ** 0.5)
        poids = [a ** 1.3 for a in attraits]
        total = sum(poids) or 1
        f_conf = s.confinement if self.confinement else 1.0
        demandes = {}
        for e, p in zip(act, poids):
            dem = volume * p / total * r.uniform(0.9, 1.1)
            if f_conf != 1.0:
                f_e = f_conf + (1 - f_conf) * 0.5 if (f_conf < 1 and e.distance) else f_conf
                dem *= f_e
                if s.recurrent and f_conf < 1 and not e.distance:
                    e.abonnes *= 1 - 0.05 * (1 - f_conf)
            demandes[e] = dem
        return demandes

    def jouer_mois(self, prix: float, marketing: float, qualite_inv: float) -> list[str]:
        s, r = self.s, self.rng
        self.nouvelles = []
        mois_cal = self.mois % 12
        date_txt = self.date()
        j = self.joueur
        if s.prix_ref:
            j.prix = prix
        self.evoluer_macro()
        for e in self.actives:
            e.taux_ref = self.taux_ref
            e.marche_ref = self
            if e.joueur:
                e.preparer(marketing, qualite_inv)
            else:
                e.decider(self, self.force)
                e.preparer(e.mkt_prevu, e.q_prevu)
        self.processus_secteur()
        act = self.actives
        if s.modele in ("industrie", "saas", "luxe", "distribution"):
            demandes = self.partager_demande(act, mois_cal)
        else:
            demandes = {e: 0.0 for e in act}
        rapport = []
        for e in act:
            e.activite_filiales(s.saison[mois_cal], self.conjoncture)
            lignes = e.cloturer(demandes[e], mois_cal, date_txt, self)
            e.historique[-1]["ca_filiales"] = e.ca_filiales
            if e.joueur:
                rapport += lignes
        cle_part = "ventes" if s.modele in ("industrie", "saas", "luxe", "distribution") else "ca"
        total_part = sum(e.historique[-1][cle_part] for e in act) or 1
        for e in self.entreprises:
            if e.actif:
                e.historique[-1]["part"] = e.historique[-1][cle_part] / total_part
            else:
                e.historique.append(dict(ca=0, resultat=0, tresorerie=0, ventes=0, utilisation=0, prix=e.prix,
                                         part=0.0, valorisation=0.0))
        if self.confinement:
            self.confinement -= 1
        for ch in self.chaines:
            ch["dans"] -= 1
        if self.duree_conjoncture:
            self.duree_conjoncture -= 1
            if not self.duree_conjoncture:
                self.conjoncture = 1.0
                self.nouvelles.append("ℹ La conjoncture redevient normale.")
        self.mois += 1
        for e in self.entreprises:
            e.historique[-1]["valorisation"] = e.valorisation()
        # biotech : un échec clinique sans autre molécule en clinique, et les investisseurs se retirent
        for e in act:
            if getattr(e.act, "faillite", False) and e.actif:
                e.actif, e.fin_raison = False, "faillite (échec clinique)"
                if e.joueur:
                    rapport.append("💀 Votre dernière molécule en clinique a échoué : les investisseurs se retirent "
                                   "et l'entreprise est liquidée.")
                    self.fin = "faillite"
                else:
                    self.nouvelles.append(f"💀 {e.nom} perd sa dernière molécule en clinique et ferme ses portes.")
        # solvabilité
        for e in [x for x in act if x.actif]:
            v = e.verifier_solvabilite()
            if e.joueur and e.tresorerie < 0 and v is None or (v or "").startswith("retrait:"):
                if e.joueur:
                    if v:
                        rapport.append(f"🏦 Découvert : vos placements ont été débloqués pour renflouer le compte "
                                       f"({v.split(':')[1]}).")
                    if e.tresorerie < 0:
                        rapport.append(f"⚠ Compte à découvert : {fmt(-e.tresorerie)} sur {fmt(e.decouvert_autorise())} "
                                       "autorisés. Agios de 12 % par an ; au-delà, c'est l'incident.")
                continue
            if not v:
                continue
            if e.joueur:
                if v == "faillite":
                    rapport.append("💀 Trésorerie épuisée et plus de crédit : votre entreprise est placée "
                                   "en liquidation.")
                    self.fin = "faillite"
                else:
                    rapport.append(f"🚨 Trésorerie négative ! La banque vous accorde un prêt d'urgence de "
                                   f"{v.split(':')[1]}. C'est la seule fois : la prochaine, c'est la liquidation.")
            elif v == "faillite":
                self.nouvelles.append(f"💀 {e.nom} fait faillite !")
        # les concurrents vivent aussi leurs coups de chance et leurs coups durs
        for e in self.concurrents:
            if not e.actif:
                continue
            x = r.random()
            if x < 0.06:
                e.notoriete = min(100, e.notoriete + r.choice([6, 10, 15]))
                self.nouvelles.append(f"📰 {e.nom} fait parler d'elle : sa notoriété grimpe.")
            elif x < 0.09:
                e.exceptionnel(-r.choice([3_000, 5_000, 8_000]) * s.echelle, "Incident d'exploitation")
            elif x < 0.11 and e.historique[-1]["ca"] > 0 and "commande" not in s.exclus:
                e.exceptionnel(e.historique[-1]["ca"] * 0.25 * s.marge_commande / 0.35, "Commande exceptionnelle")
                self.nouvelles.append(f"🤝 {e.nom} décroche une grosse commande.")
        # fusions entre concurrents : un concurrent riche rachète un concurrent en difficulté
        fragiles = [e for e in self.concurrents if e.actif and e.tresorerie < e.charges_fixes()
                    and len(e.historique) > 6]
        for cible in fragiles:
            if r.random() < 0.08:
                prix = self.prix_demande(cible)
                riches = [e for e in self.concurrents if e.actif and e is not cible
                          and e.tresorerie > 2 * prix + 6 * e.charges_fixes()]
                if riches:
                    ok, msg = self.offrir_rachat(r.choice(riches), cible, prix)
                    if ok:
                        self.nouvelles.append(msg + " Le secteur se concentre.")
                    break
        self.flux_opportunites()
        # nouvel entrant de temps en temps
        if (self.noms_libres and 4 <= self.mois <= self.duree * 0.7 and len(self.actives) < 5 and r.random() < 0.04):
            st = r.choice(list(STRATEGIES.values()))
            e = self.ajouter_concurrent(self.noms_libres.pop(0), st)
            self.nouvelles.append(f"🆕 Nouveau concurrent : {e.nom} ({st.nom.lower()} : {st.description}).")
        if not self.fin and self.mois >= self.duree:
            self.fin = "terme"
        if not self.fin and not [e for e in self.concurrents if e.actif] and self.concurrents:
            self.nouvelles.append("🏆 Tous vos concurrents ont disparu : vous êtes seul dans votre secteur !")
        rapport += self.nouvelles
        self.journal += rapport
        return rapport

    # ------------------------------------------------------------ événements
    def tirer_evenement(self) -> dict | None:
        """Événement aléatoire : {'cle', 'titre', 'texte', 'choix': None | (oui, non)} ; si choix, appeler resoudre()."""
        j, r, s = self.joueur, self.rng, self.s
        if self.fin:
            return None
        ev = j.act.evenement(self)                     # événements propres au secteur (licence, recours…)
        if ev:
            self.journal.append(f"★ {ev['titre']} : {ev['texte']}")
            return ev
        due = next((c for c in self.chaines if c["dans"] <= 0), None)
        if due:                                        # une étape d'un événement en cours passe en priorité
            ev = self.etape_chaine(due)
            if ev:
                self.journal.append(f"★ {ev['titre']} : {ev['texte']}")
                return ev
        if r.random() > 0.36:
            return None
        en_difficulte = [e for e in self.concurrents if e.actif and e.tresorerie < 1.5 * e.charges_fixes()
                         and len(e.historique) > 6]
        possibles = [
            ("presse", 3), ("buzz", 2), ("fournisseur", 2 if s.cout_unitaire else 0), ("panne", 2), ("commande", 3),
            ("subvention", 2 if self.mois <= 18 else 0), ("demission", 4 if j.moral < 45 and j.salaries else 0),
            ("crise", 1), ("salon", 2), ("avis", 2 if j.satisfaction < 50 else 0), ("controle", 1),
            ("taux_hausse", 1), ("taux_baisse", 1), ("energie", 1 if s.modele in ("industrie", "energie") else 0),
            ("rachat", 3 if self.mois >= 18 and j.valorisation() > 3 * j.capital else 0),
            ("reprise", 4 if en_difficulte else 0), ("debauchage", 2 if j.salaries >= 2 else 0),
            ("hostile", 3 if self.joueur_fragile() and self.rival_riche() else 0),
        ]
        possibles = [(c, p) for c, p in possibles if c not in s.exclus]
        if not self.chaines:                           # au plus un événement en plusieurs étapes à la fois
            possibles += [(c, p) for c, p in (("ch_greve", 2), ("ch_inflation", 2),
                                              ("ch_confinement", 1 if self.mois >= 5 else 0),
                                              ("ch_geant", 1 if self.mois <= self.duree * 0.6
                                               and len(self.actives) < 6 else 0),
                                              ("ch_influenceur", 2)) if c not in self.chaines_faites
                          and c not in s.exclus]
        tirage = [c for c, p in possibles for _ in range(p)]
        if not tirage:
            return None
        cle = r.choice(tirage)
        if cle.startswith("ch_"):
            ch = {"cle": cle, "etape": 1, "dans": 0}
            self.chaines.append(ch)
            self.chaines_faites.add(cle)
            ev = self.etape_chaine(ch)
            if ev:
                self.journal.append(f"★ {ev['titre']} : {ev['texte']}")
            return ev
        k = s.echelle
        ev = {"cle": cle, "choix": None}
        if cle == "presse":
            j.notoriete = min(100, j.notoriete + 8)
            ev.update(titre="Article dans la presse", texte=f"Un grand quotidien économique consacre un portrait à "
                      f"votre entreprise. {s.libelle_notoriete} +8.")
        elif cle == "buzz":
            j.notoriete = min(100, j.notoriete + 15)
            ev.update(titre="Buzz sur les réseaux !", texte=f"Une vidéo sur votre entreprise devient virale. "
                      f"{s.libelle_notoriete} +15.")
        elif cle == "fournisseur":
            for e in self.actives:
                e.cout_unitaire *= 1.08
            ev.update(titre="Hausse des prix fournisseurs", texte="Les fournisseurs du secteur augmentent leurs "
                      "prix de 8 % pour tout le monde. Vos concurrents vont sans doute augmenter leurs prix.")
        elif cle == "panne":
            cout = r.choice([3_000, 5_000, 8_000]) * k
            j.exceptionnel(-cout, "Panne d'un équipement")
            ev.update(titre="Panne", texte=f"Un équipement essentiel lâche. Réparation : {fmt(cout)}.")
        elif cle == "commande":
            montant = round(max(3_000 * k, j.ca_annualise() / 12 * r.uniform(0.3, 0.6)) / 1000) * 1000
            ev.update(titre="Grosse commande", texte=f"Un grand client vous propose une commande de "
                      f"{fmt(montant)}, à livrer en urgence : l'équipe va faire des heures supplémentaires "
                      f"(moral −15). Marge espérée : {fmt(montant * s.marge_commande)}.", choix=("Accepter", "Refuser"),
                      montant=montant)
        elif cle == "subvention":
            montant = 15_000 * k
            ev.update(titre="Prêt d'innovation", texte=f"Bpifrance vous propose un prêt d'innovation de "
                      f"{fmt(montant)} à taux zéro, remboursable en 5 ans.", choix=("Accepter", "Refuser"),
                      montant=montant)
        elif cle == "demission":
            e = min(j.equipe, key=lambda x: x.moral)
            j.equipe.remove(e)
            perte = 8 if e.profil in ("star", "perfectionniste") else 4
            j.qualite = max(0, j.qualite - perte)
            ev.update(titre="Démission", texte=f"Épuisé et démotivé, {e.nom} ({j.titre_min(e)}) démissionne. "
                      f"{s.libelle_qualite} −{perte}. Surveillez la charge de travail et le moral de l'équipe.")
        elif cle == "crise":
            self.conjoncture, self.duree_conjoncture = 0.85, 4
            ev.update(titre="Ralentissement économique", texte="L'économie ralentit : −15 % d'activité pour tout le "
                      "secteur pendant 4 mois. Les plus fragiles risquent de ne pas passer l'hiver.")
        elif cle == "salon":
            cout = 4_000 * k
            ev.update(titre="Salon professionnel", texte=f"On vous propose un stand dans le grand salon du secteur "
                      f"pour {fmt(cout)}. {s.libelle_notoriete} +15 espérée.", choix=("Réserver un stand", "Passer"),
                      cout=cout)
        elif cle == "avis":
            j.notoriete = max(0, j.notoriete - 10)
            ev.update(titre="Avis négatifs", texte=f"Des clients mécontents publient des avis assassins. "
                      f"{s.libelle_notoriete} −10. Améliorez la qualité ou revoyez vos prix.")
        elif cle == "controle":
            amende = r.choice([0, 0, 1_500, 4_000]) * k
            if amende:
                j.exceptionnel(-amende, "Redressement URSSAF")
            ev.update(titre="Contrôle URSSAF", texte="Un contrôle passe au crible vos déclarations. "
                      + (f"Quelques erreurs : redressement de {fmt(amende)}." if amende
                         else "Tout est en ordre, félicitations !"))
        elif cle == "taux_hausse":
            hausse = r.choice([0.005, 0.0075, 0.01])
            self.taux_ref = min(0.08, self.taux_ref + hausse)
            ev.update(titre="La banque centrale relève ses taux", texte=f"Pour freiner l'inflation, la banque "
                      f"centrale relève ses taux de {fmt_taux(hausse)}. Taux de référence : {fmt_taux(self.taux_ref)}. "
                      "Vos nouveaux crédits, et vos prêts à taux variable, coûtent plus cher.")
        elif cle == "taux_baisse":
            baisse = r.choice([0.0025, 0.005])
            self.taux_ref = max(0.0, self.taux_ref - baisse)
            ev.update(titre="La banque centrale baisse ses taux", texte=f"Pour soutenir l'activité, la banque "
                      f"centrale baisse ses taux de {fmt_taux(baisse)}. Taux de référence : {fmt_taux(self.taux_ref)}.")
        elif cle == "energie":
            if s.modele == "energie":
                self.spot_cible, self.duree_crise_energie = r.choice([150.0, 190.0, 240.0]), 6
                ev.update(titre="Crise énergétique", texte="Tensions géopolitiques et centrales à l'arrêt : les prix "
                          "de gros de l'électricité s'envolent pour plusieurs mois. Une aubaine pour les centrales qui "
                          "vendent au prix du marché… et un risque de taxe exceptionnelle.")
            else:
                for e in self.actives:
                    e.ops_mult *= 1.12
                ev.update(titre="Flambée du prix de l'énergie", texte="L'électricité et le gaz flambent : les coûts "
                          "fixes des usines augmentent de 12 % pour tout le secteur.")
        elif cle == "rachat":
            v = j.valorisation()
            pas = 10 ** max(3, int(math.log10(max(v, 1))) - 1)
            prix = round(v * r.uniform(1.1, 1.5) / pas) * pas
            ev.update(titre="Offre de rachat !", texte=f"Un grand groupe veut racheter votre entreprise pour "
                      f"{fmt(prix)}. Votre part ({j.part_fondateur:.0%}) vous rapporterait "
                      f"{fmt(prix * j.part_fondateur)}. Vendre met fin à la partie.".replace("%", " %"),
                      choix=("Vendre", "Refuser et continuer"), prix=prix)
        elif cle == "reprise":
            cible = r.choice(en_difficulte)
            prix = math.ceil(self.prix_demande(cible) / 1000) * 1000
            ev.update(titre=f"{cible.nom} est à vendre", texte=f"{cible.nom}, en grande difficulté, cherche un "
                      f"repreneur pour {fmt(prix)}. Vous récupéreriez ses {cible.salaries} salarié(s), son activité "
                      f"et ses investissements, mais aussi ses dettes ({fmt(cible.dette)}). "
                      "Le concurrent disparaît.", choix=("Racheter", "Laisser couler"), prix=prix, cible=cible)
        elif cle == "hostile":
            rival = self.rival_riche()
            prix = math.ceil(max(10_000 * k, j.valorisation() * r.uniform(0.9, 1.15)) / 1000) * 1000
            ev.update(titre=f"{rival.nom} veut vous racheter", texte=f"Votre concurrent {rival.nom} a remarqué "
                      f"vos difficultés et propose de racheter votre entreprise pour {fmt(prix)}. Votre part "
                      f"({j.part_fondateur:.0%}) vous rapporterait {fmt(prix * j.part_fondateur)}. Vendre met fin "
                      "à la partie ; refuser, c'est parier que vous allez vous redresser.".replace("%", " %"),
                      choix=("Vendre", "Refuser"), prix=prix, rival=rival)
        elif cle == "debauchage":
            rival = r.choice([e for e in self.concurrents if e.actif] or [None])
            if rival is None:
                return None
            poids = [3 if e.profil == "mercenaire" else 2 if e.profil in ("star", "daf", "growth") else 1
                     for e in j.equipe]
            e = r.choices(j.equipe, poids)[0]
            prime = max(3_000, round(e.salaire * j.salaire_mult * (1.5 if e.profil == "mercenaire" else 1) / 500) * 500)
            ev.update(titre="Débauchage", texte=f"{rival.nom} tente de débaucher {e.nom}, votre "
                      f"{j.titre_min(e)}. Pour le garder, il faut lui accorder une prime de {fmt(prime)}.",
                      choix=("Payer la prime", "Le laisser partir"), rival=rival, employe=e, prime=prime)
        self.journal.append(f"★ {ev['titre']} : {ev['texte']}")
        return ev

    def resoudre(self, ev: dict, oui: bool) -> str:
        j, cle = self.joueur, ev["cle"]
        t = len(j.historique)
        msg = ""
        if cle.startswith("act_"):
            msg = j.act.resoudre(ev, oui, self)
        elif cle == "commande":
            if oui:
                j.vendre(ev["montant"], t)
                j.acheter(ev["montant"] * (1 - self.s.marge_commande), t)
                j.moral = max(0, j.moral - 15)
                msg = f"Commande honorée : {fmt(ev['montant'] * self.s.marge_commande)} de marge."
            else:
                msg = "Commande refusée."
        elif cle == "subvention":
            if oui:
                j.prets.append(nouveau_pret(ev["montant"], 0.0, libelle="Prêt d'innovation"))
                j.mouvement(ev["montant"], "emprunts")
                msg = f"Prêt d'innovation de {fmt(ev['montant'])} encaissé."
            else:
                msg = "Prêt d'innovation refusé."
        elif cle == "salon":
            if oui:
                j.charge("marketing", ev["cout"], "charges")
                gain = self.rng.choice([8, 15, 22])
                j.notoriete = min(100, j.notoriete + gain)
                msg = f"Salon réussi : {self.s.libelle_notoriete.lower()} +{gain}."
            else:
                msg = "Vous passez votre tour."
        elif cle in ("rachat", "hostile"):
            if oui:
                self.prix_rachat = ev["prix"]
                self.acquereur = ev["rival"].nom if cle == "hostile" else "un grand groupe"
                if cle == "hostile":
                    j.actif, j.fin_raison = False, f"rachetée par {ev['rival'].nom}"
                self.fin = "rachat"
                msg = f"Vendu ! Vous encaissez {fmt(ev['prix'] * j.part_fondateur)}."
            else:
                msg = "Vous refusez l'offre : l'aventure continue."
        elif cle == "reprise":
            c = ev["cible"]
            if oui and c.actif:
                c.refus_rachat = 0
                _, msg = self.offrir_rachat(j, c, ev["prix"])
            else:
                msg = f"Vous laissez {c.nom} à son sort."
        elif cle.startswith("ch_"):
            msg = self.resoudre_chaine(ev, oui)
        elif cle == "debauchage":
            e = ev["employe"]
            if e not in j.equipe:
                msg = f"{e.nom} ne fait déjà plus partie de l'équipe."
            elif oui:
                j.charge("salaires", ev["prime"], "salaires")
                j.moral = min(100, j.moral + 5)
                e.moral = min(100.0, e.moral + 15)
                msg = f"Prime versée : {e.nom} reste, et l'équipe apprécie."
            else:
                j.equipe.remove(e)
                e.origine, e.moral = j.nom, 60.0
                ev["rival"].equipe.append(e)
                j.qualite = max(0, j.qualite - 4)
                msg = f"{e.nom} rejoint {ev['rival'].nom}, avec son savoir-faire. {self.s.libelle_qualite} −4."
        if msg:
            self.journal.append("→ " + msg)
        return msg

    def joueur_fragile(self) -> bool:
        j = self.joueur
        pertes = len(j.historique) >= 3 and all(x["resultat"] < 0 for x in j.historique[-3:])
        return self.mois >= 6 and (j.tresorerie < 2 * j.charges_fixes() or pertes)

    def rival_riche(self) -> Entreprise | None:
        prix = max(10_000 * self.s.echelle, self.joueur.valorisation() * 1.2)
        riches = [e for e in self.concurrents if e.actif and e.tresorerie > 2 * prix + 6 * e.charges_fixes()]
        return max(riches, key=lambda e: e.tresorerie) if riches else None

    # ------------------------------------------------------------ événements en plusieurs étapes
    def etape_chaine(self, ch: dict) -> dict | None:
        """Déclenche l'étape en cours d'un événement en chaîne et programme la suivante."""
        j, r, s = self.joueur, self.rng, self.s
        cle, etape = ch["cle"], ch["etape"]
        ev = {"cle": f"{cle}_{etape}", "choix": None}

        def suite(dans):
            ch["etape"], ch["dans"] = etape + 1, dans

        def finir():
            if ch in self.chaines:
                self.chaines.remove(ch)

        conc = [e for e in self.concurrents if e.actif]
        if cle == "ch_greve":
            if etape == 1:
                h = j.historique[-1] if j.historique else None
                cout = max(2_000 * s.echelle, round((h["pl"]["achats"] if h and "pl" in h else 0) * 0.5 / 1000) * 1000)
                ev.update(titre="Grève chez votre fournisseur", texte="Les salariés de votre principal fournisseur "
                          "sont en grève. Si le conflit s'enlise, les livraisons vont manquer dans tout le secteur. "
                          f"Vous pouvez constituer dès maintenant un stock de sécurité pour {fmt(cout)}.",
                          choix=("Constituer un stock", "Attendre"), cout=cout)
                for e in conc:
                    e.stock_secours = r.random() < (0.6 if e.strategie.cle in ("premium", "equilibre") else 0.3)
                suite(1)
            elif etape == 2:
                touches = [e.nom for e in conc if not (e.stock_secours or e.amont)]
                for e in self.actives:
                    if not (e.stock_secours or e.amont):
                        e.penurie = 2
                ev.update(titre="Pénurie !", texte="La grève s'étend : les livraisons s'arrêtent. Pendant 2 mois, "
                          "les entreprises sans stock tournent à 60 % de leur capacité. "
                          + ("Votre stock ou votre fournisseur intégré vous protège." if j.stock_secours or j.amont
                             else "Vous n'avez pas de stock : votre capacité chute.")
                          + (f" Concurrents touchés : {', '.join(touches)}." if touches else ""))
                suite(2)
            else:
                for e in self.actives:
                    e.cout_unitaire *= 1.06
                    e.stock_secours = False
                ev.update(titre="Fin de la grève… et hausse des prix", texte="Le conflit est réglé, mais le "
                          "fournisseur répercute les augmentations de salaires : vos achats coûtent 6 % de plus. "
                          "Pensez à revoir votre prix.")
                finir()
        elif cle == "ch_inflation":
            if etape == 1:
                for e in self.actives:
                    e.cout_unitaire *= 1.04
                self.taux_ref = min(0.08, self.taux_ref + 0.005)
                ev.update(titre="L'inflation s'accélère", texte="Les prix flambent dans toute l'économie : vos achats "
                          "coûtent 4 % de plus et la banque centrale relève ses taux. Vos salariés commencent à "
                          "parler de leur pouvoir d'achat…")
                suite(2)
            elif etape == 2:
                for e in conc:
                    e.salaire_mult *= 1.05
                if j.salaries:
                    ev.update(titre="Vos salariés demandent une augmentation", texte="Avec l'inflation, l'équipe "
                              f"réclame +5 % de salaire, soit {fmt(j.masse_salariale() * 0.05)} de plus "
                              "par mois. Refuser risque de provoquer un débrayage.",
                              choix=("Accorder +5 %", "Refuser"))
                else:
                    ev.update(titre="Hausse générale des salaires", texte="Vos concurrents augmentent leurs "
                              "salaires de 5 %. Vous n'avez pas encore de salariés : vous y échappez pour l'instant.")
                suite(2)
            else:
                self.conjoncture, self.duree_conjoncture = 0.9, 4
                ev.update(titre="L'activité ralentit", texte="Rogné par l'inflation, le pouvoir d'achat baisse : "
                          "−10 % d'activité pour tout le secteur pendant 4 mois.")
                finir()
        elif cle == "ch_confinement":
            f = s.confinement
            if etape == 1:
                cout = max(3_000 * s.echelle, round(s.installation * 0.02 / 1000) * 1000)
                effet = ("votre activité en souffrirait beaucoup" if f < 0.6 else "votre activité serait touchée"
                         if f < 1 else "votre activité pourrait même en profiter")
                ev.update(titre="Une épidémie se propage", texte="Les rumeurs de confinement se multiplient, et "
                          f"{effet}. Vous pouvez préparer le travail et la vente à distance pour {fmt(cout)} : "
                          "cela limiterait fortement les dégâts.",
                          choix=("Préparer le travail à distance", "Attendre"), cout=cout)
                for e in conc:
                    e.distance = r.random() < 0.5
                suite(1)
            elif etape == 2:
                self.confinement = 2
                montant = max(20_000 * s.echelle, round(j.ca_annualise() * 0.25 / 1000) * 1000)
                ev.update(titre="Confinement !", texte=f"Le gouvernement ordonne un confinement de 2 mois. "
                          f"Activité dans votre secteur : {'+' if f >= 1 else '−'}{abs(f - 1):.0%}".replace("%", " %")
                          + (" (moitié moins pour ceux qui travaillent à distance)" if f < 1 else "")
                          + f". L'État propose un prêt garanti de {fmt(montant)} à 1 % sur 5 ans.",
                          choix=("Accepter le prêt garanti", "Refuser"), montant=montant)
                suite(2)
            else:
                self.conjoncture, self.duree_conjoncture = 1.15, 2
                ev.update(titre="Déconfinement !", texte="L'activité repart en flèche : +15 % pendant 2 mois. "
                          "Assurez-vous d'avoir la capacité de suivre.")
                finir()
        elif cle == "ch_geant":
            if etape == 1:
                ev.update(titre="Un géant se prépare", texte="Rumeur persistante : un groupe international très bien "
                          "financé s'apprête à entrer sur votre marché d'ici quelques mois. Soignez votre réputation "
                          "et vos clients avant son arrivée.")
                suite(3)
            else:
                nom = self.rng.choice(["Groupe Horizon", "Maxima", "Titan & Co", "Alto Group", "Nexa"])
                g = self.ajouter_concurrent(nom, STRATEGIES["startup"])
                bonus = s.investisseurs * 0.8
                g.capital += bonus
                g.mouvement(bonus, "levees")
                g.notoriete = max(g.notoriete, 35)
                ev.update(titre=f"Le géant {nom} débarque", texte=f"{nom} arrive en fanfare, avec des moyens "
                          "énormes et des prix agressifs. Il va chercher à prendre vos clients.")
                self.nouvelles.append(f"🆕 Le géant {nom} entre sur le marché.")
                finir()
        elif cle == "ch_influenceur":
            if etape == 1:
                cout = 3_000 * s.echelle
                ev.update(titre="Partenariat avec une influenceuse", texte="Une influenceuse suivie par 2 millions "
                          f"de personnes propose de parler de vous pendant un mois contre {fmt(cout)}. Succès garanti, "
                          "promet-elle…", choix=("Signer", "Décliner"), cout=cout)
                suite(1)
            else:
                if r.random() < 0.7:
                    j.notoriete = min(100, j.notoriete + 20)
                    ev.update(titre="Carton !", texte=f"La campagne est un succès. {s.libelle_notoriete} +20.")
                else:
                    j.notoriete = max(0, j.notoriete - 12)
                    j.satisfaction = max(0, j.satisfaction - 5)
                    ev.update(titre="Bad buzz", texte="L'influenceuse est prise dans un scandale, et votre marque "
                              f"avec elle. {s.libelle_notoriete} −12.")
                finir()
        return ev if "titre" in ev else None

    def resoudre_chaine(self, ev: dict, oui: bool) -> str:
        j, cle = self.joueur, ev["cle"]
        if cle == "ch_greve_1":
            if oui:
                j.charge("achats", ev["cout"], "fournisseurs")
                j.stock_secours = True
                return f"Stock de sécurité constitué pour {fmt(ev['cout'])}."
            return "Vous prenez le risque d'attendre."
        if cle == "ch_inflation_2":
            if oui:
                j.salaire_mult *= 1.05
                j.moral = min(100, j.moral + 10)
                return "Augmentation accordée : l'équipe est soulagée (moral +10)."
            j.moral = max(0, j.moral - 15)
            if self.rng.random() < 0.4:
                j.penurie = 1
                return "Refus : une partie de l'équipe débraie. Capacité −40 % le mois prochain, moral −15."
            return "Refus : l'équipe grince des dents (moral −15)."
        if cle == "ch_confinement_1":
            if oui:
                j.investir("Travail et vente à distance", ev["cout"])
                j.distance = True
                return f"Travail à distance prêt ({fmt(ev['cout'])})."
            return "Vous attendez de voir."
        if cle == "ch_confinement_2":
            if oui:
                j.prets.append(nouveau_pret(ev["montant"], 0.01, libelle="Prêt garanti par l'État"))
                j.mouvement(ev["montant"], "emprunts")
                return f"Prêt garanti de {fmt(ev['montant'])} encaissé, à 1 %."
            return "Vous refusez le prêt garanti."
        if cle == "ch_influenceur_1":
            if oui:
                j.charge("marketing", ev["cout"], "charges")
                return "Contrat signé : verdict le mois prochain."
            self.chaines = [c for c in self.chaines if c["cle"] != "ch_influenceur"]
            return "Vous déclinez poliment."
        return ""

    # ------------------------------------------------------------ classement et bilan
    def classement(self) -> list[Entreprise]:
        return sorted(self.entreprises, key=lambda e: (e.actif, e.valorisation()), reverse=True)

    def rang_joueur(self) -> int:
        if self.fin == "faillite":
            return len(self.entreprises)
        if self.fin == "rachat":                  # vendue : classée selon le prix obtenu
            return 1 + sum(1 for e in self.concurrents if e.actif and e.valorisation() > self.prix_rachat)
        return self.classement().index(self.joueur) + 1

    def bilan(self) -> dict:
        """Bilan de fin de partie. Le score, c'est le multiple de l'argent investi (valeur finale / capital levé),
        comme le regarderait un fonds ; votre gain personnel, c'est votre part plus vos dividendes."""
        j = self.joueur
        if self.fin == "faillite":
            valeur = 0.0
        elif self.fin == "rachat":
            valeur = self.prix_rachat
        else:
            valeur = j.valorisation()
        parts = valeur * j.part_fondateur
        gain = parts + j.patrimoine
        moic = (valeur + j.dividendes_verses) / max(1.0, j.capital)
        paliers = [(1, "Valeur détruite", "L'entreprise vaut moins que l'argent qu'on y a mis. Elle tient debout, "
                    "mais les investisseurs y perdent."),
                   (2, "Entreprise saine", "Vous avez créé de la valeur : les investisseurs retrouvent leur mise, "
                    "et un peu plus."),
                   (5, "Belle réussite", "Une entreprise solide, qui a fait fructifier l'argent de ses actionnaires."),
                   (15, "Success story", "Votre entreprise est devenue une référence de son secteur !"),
                   (float("inf"), "Licorne en vue 🦄", "Exceptionnel : chaque euro investi en vaut plus de 15.")]
        if self.fin == "faillite" or valeur <= 0:
            titre, commentaire = "Faillite", ("L'aventure s'arrête là. Beaucoup de grands entrepreneurs ont connu "
                                             "un échec : surveillez la trésorerie mois après mois, et gardez toujours "
                                             "de quoi tenir jusqu'à la prochaine levée ou au prochain contrat.")
            if j.patrimoine > 0:
                commentaire += (f" Heureusement, les dividendes que vous vous êtes versés ({fmt(j.patrimoine)} nets) "
                                "restent à vous.")
        else:
            titre, commentaire = next((t, c) for seuil, t, c in paliers if moic < seuil)
        return {"titre": titre, "commentaire": commentaire, "gain": gain, "multiple": gain / APPORT, "moic": moic,
                "valeur": valeur, "capital": j.capital,
                "mois": self.mois, "salaries": j.salaries, "ca": j.ca_annualise(), "impots": j.impots_payes,
                "part": j.part_fondateur, "rang": self.rang_joueur(), "nb": len(self.entreprises),
                "parts": parts, "dividendes": j.patrimoine, "note": j.note}

    # ------------------------------------------------------------ prévisionnel
    def projeter(self, prix: float, marketing: float, qualite_inv: float, n: int = 6) -> list[dict]:
        """Simule les n prochains mois sur une copie du marché, à décisions constantes, sans embauche
        ni événement : un scénario plausible pour anticiper les tensions de trésorerie."""
        m = copy.deepcopy(self)
        m.rng.seed(1000 + self.mois)
        res = []
        for _ in range(max(0, min(n, self.duree - self.mois))):
            if m.fin or not m.joueur.actif:
                break
            date = m.date()
            m.jouer_mois(prix, marketing, qualite_inv)
            h = m.joueur.historique[-1]
            res.append({"date": date, "tresorerie": h["tresorerie"], "ca": h["ca"], "resultat": h["resultat"],
                        "ebe": h.get("ebe", 0.0), "decouvert": m.joueur.decouvert_autorise(),
                        "note": h.get("note", m.joueur.note)})
        return res


def fmt(x: float, signe: bool = False) -> str:
    s = f"{abs(x):,.0f}".replace(",", " ") + " €"
    if x < 0:
        return "−" + s
    return ("+" + s) if signe else s


def fmt_c(x: float, signe: bool = False) -> str:
    """Montant compact : 845 k€, 12,3 M€."""
    a = abs(x)
    if a >= 1e9:
        s = f"{a / 1e9:.1f} Md€"
    elif a >= 1e6:
        s = f"{a / 1e6:.1f} M€" if a < 1e8 else f"{a / 1e6:.0f} M€"
    elif a >= 1e4:
        s = f"{a / 1e3:.0f} k€"
    else:
        s = f"{a:,.0f}".replace(",", " ") + " €"
    s = s.replace(".", ",")
    if x < 0:
        return "−" + s
    return ("+" + s) if signe else s


def fmt_taux(x: float) -> str:
    return f"{x * 100:.2f}".replace(".", ",").replace(",00", "") + " %"


def fmt_n(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ")
