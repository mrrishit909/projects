"""A synthetic multinational and everything its carbon accountants receive: six subsidiaries' ERP vendor masters and AP
ledgers, the freight forwarders' shipment records, utility bills, and the PDF-style sustainability disclosures some
suppliers publish. An invented emission-factor catalogue with versions sits alongside.

The generator knows the truth the service never sees: which real supplier is behind each messy vendor record, the true
spend category of every invoice line, how far each supplier's real carbon intensity sits from its sector average, and
which suppliers buy their materials from which (the tier-2 network). Tests and the evaluation read the truth; the
service sees only records.

Every random draw is keyed by (seed, purpose, month or entity), so the same company can be regenerated line for line,
and the ledger can be streamed month by month without holding two million lines in memory.
"""
import functools
import math

import numpy as np

YEAR = 2025
# code, legal name, country, currency, spend share, ERP vendor-name length limit
SUBSIDIARIES = [
    ("MDG-US", "Meridale Industrial Inc.", "US", "USD", 0.28, None),
    ("MDG-DE", "Meridale Antriebe GmbH", "DE", "EUR", 0.24, None),
    ("MDG-GB", "Meridale Controls Ltd", "GB", "GBP", 0.10, None),
    ("MDG-CN", "Meridale (Suzhou) Manufacturing Co., Ltd.", "CN", "CNY", 0.20, None),
    ("MDG-IN", "Meridale Engineering India Pvt Ltd", "IN", "INR", 0.10, 24),     # this ERP truncates vendor names at 24 characters
    ("MDG-BR", "Meridale do Brasil Ltda", "BR", "BRL", 0.08, None),
]
SUB_CODES = [s[0] for s in SUBSIDIARIES]
SUB_COUNTRY = {s[0]: s[2] for s in SUBSIDIARIES}
SUB_CURRENCY = {s[0]: s[3] for s in SUBSIDIARIES}
FX = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "CNY": 0.139, "INR": 0.0119, "BRL": 0.182, "JPY": 0.0066, "MXN": 0.054}   # USD per unit, annual mean
CURRENCY_ALIASES = {"RMB": "CNY", "US$": "USD", "EURO": "EUR", "R$": "BRL", "STG": "GBP"}
# country: (region for spend factors, latitude, longitude, grid kgCO2e/kWh in the 2025 catalogue, has a container port)
COUNTRIES = {
    "US": ("NA", 39.0, -95.0, 0.37), "MX": ("NA", 23.6, -102.5, 0.42), "DE": ("EU", 51.2, 10.4, 0.35),
    "GB": ("EU", 54.0, -2.0, 0.20), "IT": ("EU", 42.8, 12.6, 0.27), "CN": ("CN", 31.3, 120.6, 0.55),
    "IN": ("IN", 19.1, 73.0, 0.70), "BR": ("LATAM", -23.5, -46.6, 0.10), "JP": ("APAC", 35.7, 139.7, 0.45),
    "VN": ("APAC", 10.8, 106.7, 0.48),
}
REGIONS = ["NA", "EU", "CN", "IN", "LATAM", "APAC"]
REGION_MULT = {"NA": 1.0, "EU": 0.82, "CN": 1.55, "IN": 1.7, "LATAM": 1.05, "APAC": 1.2}
# key: (label, scope, scope-3 category or None, kgCO2e per USD in the 2025 catalogue (NA), GL account, share of spend)
CATEGORIES = {
    "steel_metals": ("Steel and metals", 3, 1, 1.05, "5100", 0.14),
    "plastics_resins": ("Plastics and resins", 3, 1, 0.82, "5100", 0.09),
    "chemicals": ("Chemicals and lubricants", 3, 1, 0.74, "5100", 0.05),
    "electronic_components": ("Electronic components", 3, 1, 0.41, "5150", 0.16),
    "packaging": ("Packaging", 3, 1, 0.66, "5150", 0.06),
    "machinery": ("Machinery and equipment", 3, 2, 0.36, "1600", 0.09),
    "it_software": ("IT and software", 3, 1, 0.12, "6400", 0.08),
    "professional_services": ("Professional services", 3, 1, 0.09, "6500", 0.07),
    "facility_services": ("Facility services", 3, 1, 0.24, "6200", 0.05),
    "business_travel": ("Business travel", 3, 6, 0.38, "6600", 0.04),
    "freight": ("Freight and logistics", 3, 4, 0.52, "5300", 0.09),       # AP freight invoices: the shipment records carry the emissions
    "utilities": ("Energy bills", 2, None, 0.60, "6100", 0.08),            # utility payments: the bills carry the emissions
}
CATS = list(CATEGORIES)
COVERED = {"freight": "shipment records", "utilities": "utility bills"}     # categories whose emissions come from activity data instead
MATERIALS = ("steel_metals", "plastics_resins", "chemicals")
TIER1 = ("electronic_components", "packaging", "machinery")                 # these buy materials from the mills above (tier 2)
MODES = {"air": (0.60, 1.25), "ocean": (0.016, 1.3), "road": (0.105, 1.2), "rail": (0.028, 1.3)}   # kgCO2e per tonne-km, GSD
FUELS = {"electricity": ("kWh", 1.08), "natural_gas": ("kWh", 1.05), "diesel": ("L", 1.05)}
GAS_KG_PER_KWH, DIESEL_KG_PER_L = 0.183, 2.68
SPEND_GSD, SUPPLIER_DISPERSION = 1.2, 0.5        # the catalogue's stated uncertainty of a sector mean, and of one supplier around it

# --- names -------------------------------------------------------------------------------------------------------------
CORES = """Kestrel Norland Brightwater Ashford Calloway Dunmore Elmstead Fairhaven Granton Harlow Ivybridge Juniper Kingsley
Larkspur Marlow Northgate Oakridge Pembury Quarrington Redfern Stanmore Thornbury Upwell Valemont Westbrook Yarrow Alderton
Blackwood Carrick Dalby Eastleigh Foxley Glenmore Hollins Ingleby Kelso Lowther Midhurst Newbold Orwell Penrose Rushden
Sefton Tilbury Ulverston Ventry Whitlock Axholme Rheinwald Steinbach Hoffmann-Kessler Brandauer Lindqvist Moravec Vellmar
Kirchdorf Oberland Taunus Wendelstein Hualong Jinyuan Haitai Xinda Ruifeng Tianhe Jiahe Hengtai Shakti Vasanth Kaveri
Sahyadri Trimurti Aravalli Aurora Bandeirante Itaipu Serrana Paraty Monterrey Valle Toscana Kiyomizu Sakura Phuong
Meraki Lumen Corvex Altamira Brisa Cendra Dovetail Ember Fennel Garnet Halcyon Indigo Jasper Kinetic Lattice Meridian
Nimbus Onyx Pinnacle Quartz Radiant Sterling Tessellate Umber Vantage Wexford Zenith Acorn Beacon Cobalt Delta Equinox
Falcon Gryphon Harbor Iris Javelin Keystone Lodestar Mosaic Nova Orbit Polaris Quill Ridgeway Summit Trident""".split()
INDUSTRY = {
    "steel_metals": ["Steel Works", "Metals", "Steel Trading", "Metal Products", "Alloys", "Stahl"],
    "plastics_resins": ["Polymers", "Plastics", "Resins", "Kunststoff", "Compounds"],
    "chemicals": ["Chemicals", "Lubricants", "Coatings", "Chemie", "Specialty Chemicals"],
    "electronic_components": ["Electronics", "Components", "Circuits", "Elektronik", "Sensors", "Technologies"],
    "packaging": ["Packaging", "Cartons", "Verpackung", "Embalagens", "Pallets"],
    "machinery": ["Machinery", "Machine Tools", "Automation", "Maschinenbau", "Manufacturing"],
    "it_software": ["Software", "Systems", "Digital", "IT Services", "Cloud"],
    "professional_services": ["Consulting", "Advisory", "Partners", "Associates", "Legal Services"],
    "facility_services": ["Facility Services", "Cleaning", "Maintenance", "Security Services", "Waste Solutions"],
    "business_travel": ["Travel", "Travel Management", "Hotels", "Mobility"],
    "freight": ["Logistics", "Freight", "Shipping", "Transport", "Spedition", "Cargo"],
    "utilities": ["Energy", "Power", "Gas Supply", "Utilities", "Energie"],
}
LEGAL = {"US": ["Inc", "LLC", "Corp"], "MX": ["S.A. de C.V."], "DE": ["GmbH", "AG"], "GB": ["Ltd", "PLC"], "IT": ["S.p.A.", "S.r.l."],
         "CN": ["Co., Ltd."], "IN": ["Pvt Ltd", "Ltd"], "BR": ["Ltda", "S.A."], "JP": ["K.K."], "VN": ["JSC"]}
LEGAL_VARIANTS = {"Inc": ["Inc.", "Incorporated", "INC", ""], "LLC": ["L.L.C.", "Llc", ""], "Corp": ["Corp.", "Corporation", ""],
                  "GmbH": ["Gmbh", "G.m.b.H.", "GMBH", ""], "AG": ["A.G.", ""], "Ltd": ["Ltd.", "Limited", "LTD", ""],
                  "PLC": ["plc", "P.L.C.", ""], "Co., Ltd.": ["Co Ltd", "Company Limited", "Co.,Ltd", ""], "Pvt Ltd": ["Pvt. Ltd.", "Private Limited", ""],
                  "Ltda": ["Ltda.", "LTDA", ""], "S.A.": ["SA", "S/A", ""], "S.p.A.": ["SpA", "S.P.A.", ""], "S.r.l.": ["Srl", ""],
                  "S.A. de C.V.": ["SA de CV", ""], "K.K.": ["KK", "Kabushiki Kaisha", ""], "JSC": ["J.S.C.", "Joint Stock Company", ""]}
ABBREV = {"Manufacturing": "Mfg", "Technologies": "Tech", "Logistics": "Logistic", "Components": "Comp.", "Services": "Svcs",
          "Systems": "Sys", "Products": "Prods", "Trading": "Trdg", "Electronics": "Elec.", "Packaging": "Pkg", "Chemicals": "Chem",
          "Machinery": "Mach.", "Consulting": "Cnsltg", "Maintenance": "Maint.", "Associates": "Assoc."}
GENERIC_DOMAINS = ("gmail.com", "outlook.com", "163.com")


def _rng(seed, *key):
    return np.random.default_rng([seed, *[k if isinstance(k, int) else int.from_bytes(str(k).encode()[:8].ljust(8, b"_"), "little") % (2 ** 31) for k in key]])


def fx(currency, month):
    """USD per unit in a month: the annual mean with a small deterministic swing (the normaliser looks this table up)."""
    return FX[currency] * (1 + 0.015 * math.sin(month * 0.9 + len(currency)))


def region(country):
    return COUNTRIES[country][0]


# --- the factor catalogue -------------------------------------------------------------------------------------------------
def catalogue(version):
    """The (invented, illustrative) factor catalogue: {factor_id: {...}}. Spend factors per category and region, grid
    electricity per country, fuels, freight per mode. 2024.2 is last year's frozen version; 2025.1 revises some values."""
    old = version.startswith("EF-2024")
    out = {}
    for c, (label, scope, s3, base, _gl, _share) in CATEGORIES.items():
        if c in COVERED:
            continue
        for r in REGIONS:
            v = base * REGION_MULT[r] * ((1.06 if c in MATERIALS else 0.97) if old else 1.0)
            out[f"SPEND:{c}:{r}"] = {"kind": "spend", "category": c, "geography": r, "unit": "kgCO2e/USD", "value": round(v, 4),
                                     "gsd": SPEND_GSD, "dispersion": SUPPLIER_DISPERSION, "source": "illustrative EEIO-style sector averages"}
    for k, (_r, _la, _lo, grid) in COUNTRIES.items():
        out[f"GRID:{k}"] = {"kind": "electricity", "category": "electricity", "geography": k, "unit": "kgCO2e/kWh",
                            "value": round(grid * (1.04 if old else 1.0), 4), "gsd": FUELS["electricity"][1], "dispersion": 0.0, "source": "illustrative location-based grid averages"}
    out["FUEL:natural_gas"] = {"kind": "fuel", "category": "natural_gas", "geography": "GLOBAL", "unit": "kgCO2e/kWh", "value": GAS_KG_PER_KWH, "gsd": 1.05, "dispersion": 0.0, "source": "illustrative combustion factors"}
    out["FUEL:diesel"] = {"kind": "fuel", "category": "diesel", "geography": "GLOBAL", "unit": "kgCO2e/L", "value": DIESEL_KG_PER_L, "gsd": 1.05, "dispersion": 0.0, "source": "illustrative combustion factors"}
    for m, (v, gsd) in MODES.items():
        out[f"FREIGHT:{m}"] = {"kind": "freight", "category": m, "geography": "GLOBAL", "unit": "kgCO2e/tkm", "value": round(v * (1.05 if old and m == "air" else 1.0), 4),
                               "gsd": gsd, "dispersion": 0.0, "source": "illustrative well-to-wheel freight averages"}
    for f in out.values():
        f.update(year=2024 if old else 2025, version=version)
    return out


# --- the company --------------------------------------------------------------------------------------------------------
def _alias(name, legal, country, rng, limit=None):
    """A clerk's rendering of a supplier's name in a vendor master."""
    s = name
    if legal and rng.random() < 0.7:
        s = s[: -len(legal)].rstrip() + (" " + str(rng.choice(LEGAL_VARIANTS[legal])) if LEGAL_VARIANTS.get(legal) else "")
    words = s.split()
    if rng.random() < 0.3:
        hits = [i for i, w in enumerate(words) if w in ABBREV]
        if hits:
            i = int(rng.choice(hits))
            words[i] = ABBREV[words[i]]
    if country == "CN" and rng.random() < 0.3 and len(words) > 2:       # "Suzhou Jinyuan Electronics" -> "Jinyuan Electronics (Suzhou)"
        words = words[1:] + [f"({words[0]})"]
    if rng.random() < 0.2:
        long = [i for i, w in enumerate(words) if len(w) > 4 and w.isalpha()]
        if long:
            i = int(rng.choice(long))
            w, j = words[i], int(rng.integers(1, len(words[i]) - 2))
            kind = rng.integers(3)
            words[i] = w[:j] + w[j + 1:] if kind == 0 else w[:j] + w[j + 1] + w[j] + w[j + 2:] if kind == 1 else w[:j] + w[j] + w[j:]
    s = " ".join(words)
    if "&" in s and rng.random() < 0.5:
        s = s.replace("&", "and")
    r = rng.random()
    s = s.upper() if r < 0.35 else s.lower() if r < 0.4 else s
    if rng.random() < 0.05:
        s += str(rng.choice([" (EUR)", " - USE THIS ONE", " *", " (old)"]))
    if rng.random() < 0.08:
        s = s.replace(",", "").replace(".", "")
    return s[:limit].rstrip() if limit else s


def _tax_id(country, rng):
    d = "".join(str(x) for x in rng.integers(0, 10, 12))
    return {"US": f"{d[:2]}-{d[2:9]}", "DE": f"DE{d[:9]}", "GB": f"GB{d[:9]}", "IT": f"IT{d[:11]}", "CN": f"91320{d[:12]}X",
            "IN": f"27AAB{d[:4]}C{d[4:6]}Z{d[6]}", "BR": f"{d[:2]}.{d[2:5]}.{d[5:8]}/0001-{d[8:10]}", "MX": f"MDE{d[:6]}AB1",
            "JP": f"T{d[:12]}", "VN": f"0{d[:9]}"}[country]


def _tax_variant(t, rng):
    r = rng.random()
    return t.replace("-", "").replace(".", "").replace("/", "") if r < 0.3 else " ".join([t[:2], t[2:]]) if r < 0.45 else t


@functools.lru_cache(maxsize=8)
def company(seed, n_suppliers=460):
    """The company's suppliers (with the truth behind them), vendor records, facilities and the world's true factors."""
    rng = _rng(seed, "company")
    cats = rng.choice(CATS, n_suppliers, p=np.array([CATEGORIES[c][5] for c in CATS]) ** 0.8 / (np.array([CATEGORIES[c][5] for c in CATS]) ** 0.8).sum())
    cats[:6] = "utilities"                                           # every subsidiary has a local utility
    sub_w = np.array([s[4] for s in SUBSIDIARIES])
    used, suppliers = set(), []
    intl = {"steel_metals": ["CN", "DE", "IN", "JP", "IT", "BR"], "plastics_resins": ["DE", "CN", "US", "IN"], "chemicals": ["DE", "US", "CN", "IT"],
            "electronic_components": ["CN", "VN", "JP", "DE", "US", "MX"], "machinery": ["DE", "IT", "JP", "CN", "US"], "freight": ["DE", "GB", "CN", "US"]}
    for i, cat in enumerate(cats):
        cat = str(cat)
        home = SUB_CODES[i] if cat == "utilities" and i < 6 else str(rng.choice(SUB_CODES, p=sub_w))
        country = SUB_COUNTRY[home] if (cat not in intl or rng.random() < 0.55) else str(rng.choice(intl[cat]))
        twin = suppliers and rng.random() < 0.10 and cat not in ("utilities",)
        if twin:                          # a different company with a near-identical name: same core, other country or other line of business
            base = suppliers[int(rng.integers(len(suppliers)))]
            core = base["core"]
            if rng.random() < 0.45 and base["category"] == cat:
                country = str(rng.choice([k for k in COUNTRIES if k != base["country"]]))
                ind = base["industry"]
            else:
                ind = str(rng.choice(INDUSTRY[cat]))
        else:
            core = " ".join(rng.choice(CORES, 1 + int(rng.random() < 0.35), replace=False))
            if country == "CN" and rng.random() < 0.6:
                core = str(rng.choice(["Suzhou", "Ningbo", "Shenzhen", "Dongguan", "Wuxi"])) + " " + core
            ind = str(rng.choice(INDUSTRY[cat])) if rng.random() > 0.22 else str(rng.choice(["Group", "Holdings", "Industries", "Trading", "International"]))
        legal = str(rng.choice(LEGAL[country]))
        name = f"{core} {ind} {legal}"
        if name in used:
            name = f"{core} {ind} International {legal}"
        used.add(name)
        size = float(rng.lognormal(0, 1.35))
        domain = core.lower().replace(" ", "").replace("-", "")[:14] + ind.split()[0].lower()[:6] + {"US": ".com", "GB": ".co.uk", "DE": ".de", "CN": ".cn", "IN": ".in", "BR": ".com.br", "IT": ".it", "MX": ".mx", "JP": ".jp", "VN": ".vn"}[country]
        mix = {cat: 1.0}
        if cat in ("electronic_components", "packaging", "chemicals", "it_software", "steel_metals", "facility_services") and rng.random() < 0.3:   # distributors sell a second line
            mix = {cat: 0.65, str(rng.choice([c for c in CATS if c not in (cat, "utilities", "freight", "business_travel")])): 0.35}
        suppliers.append({"idx": i, "name": name, "core": core, "industry": ind, "legal": legal, "category": cat, "mix": mix, "country": country,
                          "home": home, "size": size, "tax_id": _tax_id(country, rng), "domain": domain,
                          "mult": float(np.exp(rng.normal(-0.45 ** 2 / 2, 0.45))),           # true intensity / sector mean (mean 1)
                          "since": YEAR if (i >= 6 and rng.random() < 0.15) else YEAR - 1})      # some suppliers are new this year
    # who buys from whom: big suppliers serve several subsidiaries
    for s in suppliers:
        n_more = 0 if s["category"] == "utilities" else int(min(5, rng.poisson(0.4 + 0.6 * math.log1p(s["size"]))))
        others = [c for c in SUB_CODES if c != s["home"]]
        served = [s["home"]] + list(rng.choice(others, n_more, replace=False, p=sub_w[[SUB_CODES.index(o) for o in others]] / sub_w[[SUB_CODES.index(o) for o in others]].sum()))
        s["served"] = {c: float(rng.uniform(0.3, 1.0)) * (2.0 if c == s["home"] else 1.0) for c in served}
    # vendor records: one per (supplier, subsidiary), sometimes a second one created by another clerk
    records, k = [], {c: 0 for c in SUB_CODES}
    for s in suppliers:
        for sub in s["served"]:
            for dup in range(1 + int(rng.random() < 0.09)):
                k[sub] += 1
                limit = next(x[5] for x in SUBSIDIARIES if x[0] == sub)
                records.append({"vendor_ref": f"{sub}-V{k[sub]:05d}", "subsidiary": sub, "name": _alias(s["name"], s["legal"], s["country"], rng, limit),
                                "country": s["country"] if rng.random() > 0.03 else SUB_COUNTRY[sub],
                                "tax_id": _tax_variant(s["tax_id"], rng) if rng.random() < 0.55 else None,
                                "email_domain": (s["domain"] if rng.random() > 0.08 else str(rng.choice(GENERIC_DOMAINS))) if rng.random() < 0.5 else None,
                                "supplier": s["idx"], "primary": dup == 0})
    # the tier-2 network: component, packaging and machinery makers buy from the mills
    mills = [s for s in suppliers if s["category"] in MATERIALS]
    w = np.array([m["size"] for m in mills]) ** 1.2
    for s in suppliers:
        s["upstream"] = {}
        if s["category"] in TIER1 and mills:
            n = 1 + int(rng.integers(0, 3))
            pick = rng.choice(len(mills), min(n, len(mills)), replace=False, p=w / w.sum())
            share = float(rng.uniform(0.3, 0.6))            # of this supplier's cradle-to-gate emissions, embodied in what it buys from mills
            split = rng.dirichlet(np.ones(len(pick)) * 2)
            s["upstream"] = {int(mills[j]["idx"]): float(share * x) for j, x in zip(pick, split)}
    # the world's true factors: the catalogue's sector means are themselves estimates
    t = _rng(seed, "truth")
    bias = {c: float(np.exp(t.normal(0, 0.15))) for c in CATS}
    mode_bias = {m: float(np.exp(t.normal(0, 0.08))) for m in MODES}
    grid_bias = {k: float(np.exp(t.normal(0, 0.04))) for k in COUNTRIES}
    facilities = []
    for code, _n, country, _cur, share, _l in SUBSIDIARIES:
        for kind, scale in (("plant", 1.0), ("warehouse", 0.12), ("office", 0.05)):
            facilities.append({"id": f"{code[4:]}-{kind[:3].upper()}-01", "subsidiary": code, "kind": kind, "country": country,
                               "kwh_month": float(scale * share * 1.6e7 * t.uniform(0.8, 1.2)), "gas_share": 0.0 if country in ("IN", "BR") else float(t.uniform(0.25, 0.5)),
                               "diesel_l_month": float(scale * share * 6e4 * t.uniform(0.5, 1.5))})
    total_spend = 2.4e9
    sizes = np.array([s["size"] for s in suppliers])
    for c in CATS:          # each category gets its share of the spend
        members = [s for s in suppliers if s["category"] == c]
        tot = sum(s["size"] for s in members) or 1
        for s in members:
            s["spend_usd"] = total_spend * CATEGORIES[c][5] * s["size"] / tot
    del sizes
    return {"seed": seed, "suppliers": suppliers, "records": records, "facilities": facilities, "bias": bias, "mode_bias": mode_bias, "grid_bias": grid_bias}


def true_intensity(world, s, category):
    """kgCO2e per USD this supplier really emits per dollar of `category` (the sector mean the catalogue estimates, its error, and the supplier's own offset)."""
    return CATEGORIES[category][3] * REGION_MULT[region(s["country"])] * world["bias"][category] * s["mult"]


# --- the AP ledger, streamed month by month ---------------------------------------------------------------------------------
TEMPLATES = {
    "steel_metals": ["HR coil {a}mm S235JR", "CR sheet {a}mm DC01", "Rebar B500B {a}mm", "Round bar 42CrMo4 dia {b}", "Stahlblech {a}mm verzinkt",
                     "Aco laminado a quente {a}mm", "SS304 plate {a}mm", "Aluminium extrusion 6063 profile", "Copper busbar {a}x{b}", "Steel tube {b}x{a}"],
    "plastics_resins": ["PP homopolymer granules", "ABS resin natural {b}kg", "PA66 GF30 compound", "HDPE pellets {b}kg", "Kunststoffgranulat PA6",
                        "Polycarbonate sheet {a}mm", "Resina PP {b}kg", "PVC compound grey"],
    "chemicals": ["Hydraulic oil ISO VG {b}", "Cutting fluid concentrate", "Epoxy coating {b}L", "Industrial solvent IPA", "Kuehlschmierstoff {b}L",
                  "Graxa industrial", "Powder coating RAL{c}", "Degreaser drum {b}L"],
    "electronic_components": ["PCB assembly rev {a}", "MCU 32-bit type {c}", "Capacitor 10uF reel", "Connector M12 {a}pin", "Wire harness WH-{c}",
                              "Sensor module {c}", "Leiterplatte bestueckt", "Relay 24VDC"],
    "packaging": ["Corrugated cartons {b}x{b}", "Pallet wrap film", "Wooden pallets EUR", "Foam inserts", "Wellpappe Kartons", "Caixas de papelao",
                  "Labels thermal {b}x{a}", "Strapping PET"],
    "machinery": ["CNC lathe installation", "Hydraulic press {b}t", "Conveyor system line {a}", "Robot cell commissioning", "Werkzeugmaschine",
                  "Compressor {b}kW", "Forklift purchase", "Injection moulding machine {c}t"],
    "it_software": ["Software subscription annual", "Cloud hosting {m}", "Laptop {c}", "ERP licence maintenance", "Network switches",
                    "IT support retainer {m}", "Lizenzgebuehren Software", "Licenca de software"],
    "professional_services": ["Consulting services {m}", "Audit fees FY{y}", "Legal services matter {c}", "Engineering services", "Beratungsleistung",
                              "Recruitment fee", "Servicos de consultoria", "Tax advisory {m}"],
    "facility_services": ["Cleaning services {m}", "Security guards {m}", "Waste disposal", "HVAC maintenance", "Gebaeudereinigung", "Manutencao predial",
                          "Canteen services {m}", "Pest control"],
    "business_travel": ["Flight booking {c}", "Hotel {b} nights", "Taxi and ground transport", "Rail ticket", "Reisekosten", "Passagem aerea",
                        "Car rental {b} days", "Travel agency fee"],
    "freight": ["Air freight AWB {c}", "Ocean freight FCL 40ft", "LTL trucking", "Fuel surcharge", "Spedition Frachtkosten", "Frete rodoviario",
                "Courier express", "Customs clearance and haulage"],
    "utilities": ["Electricity {m}", "Natural gas {m}", "Stromrechnung {m}", "Energia eletrica {m}", "Power bill {m}", "Gas supply {m}",
                  "Diesel for generators", "Energy invoice {m}"],
}
GENERIC = ["Invoice {c}", "PO {c}", "Goods receipt {c}", "Services rendered", "As per contract", "Rechnung {c}", "Nota fiscal {c}", "Misc"]
SHARED = [   # descriptions several categories use: only the vendor and the account can tell them apart
    ("Spare parts {c}", ("machinery", "electronic_components", "steel_metals")), ("Service visit {c}", ("machinery", "facility_services", "it_software")),
    ("Raw material per PO {c}", ("steel_metals", "plastics_resins", "chemicals")), ("Annual contract {m}", ("it_software", "facility_services", "professional_services")),
    ("Consumables {m}", ("chemicals", "packaging", "facility_services")), ("Installation and commissioning", ("machinery", "it_software", "electronic_components")),
    ("Maintenance {m}", ("machinery", "facility_services", "it_software")), ("Project services {c}", ("professional_services", "it_software", "machinery"))]
SHARED_BY = {c: [t for t, cs in SHARED if c in cs] for c in CATEGORIES}
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def relations(world, year=YEAR):
    """(supplier idx, subsidiary, annual USD spend) for every buying relationship."""
    out = []
    for s in world["suppliers"]:
        if s["since"] > year:
            continue
        tot = sum(s["served"].values())
        for sub, w in s["served"].items():
            out.append((s["idx"], sub, s["spend_usd"] * w / tot))
    return out


def ledger_month(seed, month, n_lines, year=YEAR, defects=True):
    """One month of AP invoice lines across the six ERPs. Returns parallel lists/arrays; `true_*` fields are generator truth."""
    w = company(seed)
    rel = relations(w, year)
    spend = np.array([r[2] for r in rel])
    p = spend ** 0.7 / (spend ** 0.7).sum()
    rng = _rng(seed, "ap", year, month)
    ri = rng.choice(len(rel), n_lines, p=p)
    avg = spend / (n_lines * 12 * p)                                   # mean USD per line so a relation's lines sum to its spend
    usd = avg[ri] * rng.lognormal(-0.405, 0.9, n_lines)
    sup = np.array([rel[i][0] for i in ri])
    subs = [rel[i][1] for i in ri]
    rec_by = {}
    for r in w["records"]:
        rec_by.setdefault((r["supplier"], r["subsidiary"]), []).append(r["vendor_ref"])
    pick = rng.random(n_lines)
    vendor = [refs[0] if len(refs) == 1 or pk < 0.6 else refs[1] for refs, pk in ((rec_by[(int(s), b)], pk) for s, b, pk in zip(sup, subs, pick))]
    S = w["suppliers"]
    cat = []
    for s, u in zip(sup, rng.random(n_lines)):
        mix = S[s]["mix"]
        cat.append(next(iter(mix)) if len(mix) == 1 or u < list(mix.values())[0] else list(mix)[1])
    tmpl = rng.integers(0, 10, n_lines)
    generic = rng.random(n_lines) < 0.16
    nums = rng.integers(1, 9999, (n_lines, 3))
    desc = []
    shared = rng.random(n_lines) < 0.14
    for c, t, g, sh, (a, b, cc), dd in zip(cat, tmpl, generic, shared, nums, rng.integers(0, 3, n_lines)):
        ts = GENERIC if g else SHARED_BY[c] if sh and SHARED_BY[c] else TEMPLATES[c]
        s = ts[t % len(ts)].format(a=a % 40 + 1, b=b % 500 + 1, c=cc, m=MONTHS[month - 1], y=year % 100)
        desc.append(s if dd else f"PO{cc + 4400000} {s}")
    gl = np.array([CATEGORIES[c][4] for c in cat], dtype=object)
    r = rng.random(n_lines)
    gl[r < 0.07] = "6900"                                                 # sundry expenses: the clerk did not know
    wrong = (r >= 0.07) & (r < 0.10)
    gl[wrong] = rng.choice(["5100", "5150", "6200", "6500", "5300"], int(wrong.sum()))
    currency = [SUB_CURRENCY[b] for b in subs]
    rate = np.array([fx(c, month) for c in currency])
    credit = rng.random(n_lines) < 0.015
    usd = np.where(credit, -usd * 0.4, usd)
    amount = np.round(usd / rate, 2)
    usd = amount * rate
    day = rng.integers(1, 29, n_lines)
    inv_base = (np.arange(n_lines) * 7919 + int(rng.integers(0, 10 ** 7))) % 10 ** 7      # distinct invoice numbers within the month
    out = {"subsidiary": subs, "vendor_ref": vendor, "invoice": [f"{b[4:]}{year % 100}{month:02d}-{x:07d}" for b, x in zip(subs, inv_base)],
           "line": rng.integers(1, 4, n_lines), "period": [f"{year}-{month:02d}-{d:02d}" for d in day], "description": desc, "gl_code": list(gl),
           "amount": amount, "currency": currency, "true_supplier": sup, "true_category": cat, "true_usd": usd}
    out["true_kg"] = np.array([0.0 if c in COVERED else u * true_intensity(w, S[s], c) for s, c, u in zip(sup, cat, usd)])
    out["_injected"] = {"duplicate_postings": 0, "currency_aliases": 0, "unknown_currency": 0, "unknown_vendor": 0, "wrong_year": 0}
    if defects:     # what an ERP extract really contains: double postings, currency spelled oddly, a vendor the master lacks, a wrong year
        inj = out.pop("_injected")
        k = n_lines
        dup = np.nonzero(rng.random(k) < 0.004)[0]
        inj["duplicate_postings"] = int(len(dup))
        for f in out:
            v = out[f]
            out[f] = np.concatenate([v, v[dup]]) if isinstance(v, np.ndarray) else v + [v[i] for i in dup]
        n = len(out["amount"])
        for i in np.nonzero(rng.random(n) < 0.0008)[0]:
            j = int(rng.integers(4))
            if j == 0:
                alias = {"CNY": "RMB", "USD": "US$", "EUR": "EURO", "BRL": "R$", "GBP": "STG"}.get(out["currency"][i])
                if alias:
                    out["currency"][i] = alias
                    inj["currency_aliases"] += 1
            elif j == 1:
                out["currency"][i] = "XXX"
                inj["unknown_currency"] += 1
            elif j == 2:
                out["vendor_ref"][i] = out["vendor_ref"][i][:7] + "V9" + out["vendor_ref"][i][9:]
                inj["unknown_vendor"] += 1
            else:
                out["period"][i] = f"{year - 1}-12-{int(rng.integers(1, 29)):02d}"
                inj["wrong_year"] += 1
        out["_injected"] = inj
    return out


def month_lines(n_total):
    base = n_total // 12
    return [base + (1 if m < n_total - 12 * base else 0) for m in range(12)]


def labelled_sample(seed, n=6000, year=YEAR - 1):
    """Last year's analyst-labelled sample: n AP lines with their true category (what a carbon team labels by hand)."""
    parts = [ledger_month(seed, m, n // 12 + (1 if m <= n % 12 else 0), year=year, defects=False) for m in range(1, 13)]
    out = {k: (np.concatenate([p[k] for p in parts]) if isinstance(parts[0][k], np.ndarray) else sum((p[k] for p in parts), [])) for k in parts[0] if k != "_injected"}
    rng = _rng(seed, "labels", year)
    out["label"] = [str(rng.choice(CATS)) if rng.random() < 0.02 else c for c in out["true_category"]]     # analysts get about 2% wrong
    return out


# --- shipments and utility bills ---------------------------------------------------------------------------------------------
def _gc_km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (COUNTRIES[a][1], COUNTRIES[a][2], COUNTRIES[b][1], COUNTRIES[b][2]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def lane(a, b):
    """{'air_km', 'sea_km', 'road_km', 'intercontinental'} for a lane; sea routes are longer than the great circle."""
    gc = max(_gc_km(a, b), 150.0)
    inter = region(a) != region(b) and not {region(a), region(b)} <= {"CN", "APAC"}
    return {"air_km": round(gc * 1.08), "sea_km": round(gc * 1.55 + 800), "road_km": round(gc * 1.25), "intercontinental": inter}


def shipments(seed, n=40000, year=YEAR):
    """Freight records from the forwarders' systems: lane, mode, weight, distance. US records weigh in pounds and run in miles."""
    w = company(seed)
    rng = _rng(seed, "freight", year)
    S = w["suppliers"]
    goods = [s for s in S if s["category"] in MATERIALS + TIER1]
    gw = np.array([s["spend_usd"] for s in goods])
    carriers = {}
    for r in w["records"]:
        if S[r["supplier"]]["category"] == "freight":
            carriers.setdefault(r["subsidiary"], []).append(r["vendor_ref"])
    fac = {f["subsidiary"]: f["id"] for f in w["facilities"] if f["kind"] == "plant"}
    origin = rng.choice(len(goods), n, p=gw / gw.sum())
    out = []
    for i in range(n):
        s = goods[origin[i]]
        sub = str(rng.choice(list(s["served"])))
        dest = SUB_COUNTRY[sub]
        ln = lane(s["country"], dest)
        if ln["intercontinental"]:
            mode = "air" if rng.random() < 0.3 else "ocean"
        elif s["country"] == dest:
            mode = "road" if rng.random() < 0.85 else "rail"
        else:
            mode = "road" if rng.random() < 0.7 else "rail"
        kg = float(rng.lognormal(math.log(350), 0.8) if mode == "air" else rng.lognormal(math.log(8000), 0.5) if mode == "ocean" else rng.lognormal(math.log(7000), 0.6))
        km = ln["air_km"] if mode == "air" else ln["sea_km"] if mode == "ocean" else ln["road_km"] * (0.4 if s["country"] == dest else 1.0)
        urgent = mode == "air" and rng.random() < 0.3
        us = dest == "US"
        out.append({"shipment": f"SH{year % 100}-{i:06d}", "subsidiary": sub, "facility_id": fac[sub], "carrier_ref": str(rng.choice(carriers.get(sub) or sum(carriers.values(), []))),
                    "origin": s["country"], "destination": dest, "mode": mode, "weight": round(kg / 0.4536, 1) if us else round(kg, 1), "weight_unit": "lb" if us else "kg",
                    "distance": round(km / 1.609, 1) if us else float(km), "distance_unit": "mi" if us else "km", "urgent": bool(urgent),
                    "month": int(rng.integers(1, 13)), "true_supplier": s["idx"],
                    "true_kg": kg / 1000 * km * MODES[mode][0] * w["mode_bias"][mode]})
    return out


def utility_bills(seed, year=YEAR):
    """Monthly bills per facility: electricity (kWh; Brazil bills in MWh), natural gas (m3 in Europe, therms in the US), diesel (US gallons in the US)."""
    w = company(seed)
    rng = _rng(seed, "bills", year)
    out = []
    for f in w["facilities"]:
        c = f["country"]
        for m in range(1, 13):
            season = 1 + 0.12 * math.cos((m - 1) / 12 * 2 * math.pi)
            kwh = f["kwh_month"] * season * rng.uniform(0.92, 1.08)
            e_kwh = kwh * (1 - f["gas_share"])
            out.append({"bill": f"{f['id']}-E-{m:02d}", "facility_id": f["id"], "subsidiary": f["subsidiary"], "fuel": "electricity", "month": m,
                        "quantity": round(e_kwh / 1000, 3) if c == "BR" else round(e_kwh), "unit": "MWh" if c == "BR" else "kWh",
                        "true_kg": e_kwh * COUNTRIES[c][3] * w["grid_bias"][c]})
            if f["gas_share"]:
                g_kwh = kwh * f["gas_share"] * (1.6 if m in (1, 2, 11, 12) else 0.8)
                q, u = (round(g_kwh / 29.31, 1), "therm") if c == "US" else (round(g_kwh / 10.55, 1), "m3")
                out.append({"bill": f"{f['id']}-G-{m:02d}", "facility_id": f["id"], "subsidiary": f["subsidiary"], "fuel": "natural_gas", "month": m,
                            "quantity": q, "unit": u, "true_kg": g_kwh * GAS_KG_PER_KWH})
            litres = f["diesel_l_month"] * rng.uniform(0.7, 1.3)
            q, u = (round(litres / 3.785, 1), "gal") if c == "US" else (round(litres, 1), "L")
            out.append({"bill": f"{f['id']}-D-{m:02d}", "facility_id": f["id"], "subsidiary": f["subsidiary"], "fuel": "diesel", "month": m,
                        "quantity": q, "unit": u, "true_kg": litres * DIESEL_KG_PER_L})
    out.append(dict(out[5]))         # one bill keyed in twice
    return out


# --- supplier disclosures ----------------------------------------------------------------------------------------------------
def disclosures(seed, year=YEAR - 1):
    """Sustainability disclosures from the larger material, component and machinery suppliers, as text. Returns
    [{'supplier': idx, 'text': ..., 'truth': {...}}]. A few omit their upstream emissions; one has a unit slip."""
    w = company(seed)
    rng = _rng(seed, "disclosures")
    S = w["suppliers"]
    cands = sorted([s for s in S if s["category"] in MATERIALS + TIER1], key=lambda s: -s["spend_usd"])[:60]
    out = []
    for s in cands:
        if rng.random() > 0.55:
            continue
        cat = s["category"]
        intensity = true_intensity(w, s, cat) * (1 + rng.normal(0, 0.03))
        revenue_usd = s["spend_usd"] / rng.uniform(0.008, 0.06)
        total_t = intensity * revenue_usd / 1000
        s1f, s2f = rng.uniform(0.25, 0.45), rng.uniform(0.1, 0.25)
        s1, s2, s3 = total_t * s1f, total_t * s2f, total_t * (1 - s1f - s2f)
        cur = {"US": "USD", "DE": "EUR", "GB": "GBP", "IT": "EUR", "CN": "CNY", "IN": "INR", "BR": "BRL", "JP": "JPY", "VN": "USD", "MX": "MXN"}[s["country"]]
        rev_local = revenue_usd / FX[cur]
        partial = rng.random() < 0.15
        slip = not out          # the first disclosure carries a unit slip (revenue in thousands, labelled millions)
        principals = [S[m]["name"] for m in sorted(s["upstream"], key=lambda m: -s["upstream"][m])]
        out.append({"supplier": s["idx"], "text": _render(s, rng, year, cur, rev_local * (1000 if slip else 1), s1, s2, None if partial else s3, principals),
                    "truth": {"revenue_usd": revenue_usd, "scope1_t": s1, "scope2_t": s2, "scope3_upstream_t": None if partial else s3,
                              "intensity": intensity, "unit_slip": slip, "currency": cur, "principal_suppliers": [S[m]["idx"] for m in s["upstream"]]}})
    return out


def _money(v, rng):
    if v >= 2e9 and rng.random() < 0.6:
        return f"{v / 1e9:.2f} billion"
    if rng.random() < 0.5:
        return f"{v / 1e6:,.1f} million"
    return f"{v / 1e6:,.1f}m"


def _mass(t, rng):
    r = rng.random()
    if t > 2e5 and r < 0.3:
        return f"{t / 1e6:.3f} MtCO2e"
    if t > 2e3 and r < 0.6:
        return f"{t / 1e3:,.1f} ktCO2e"
    return f"{t:,.0f} tCO2e"


def _render(s, rng, year, cur, revenue, s1, s2, s3, principals):
    style = int(rng.integers(3))
    name = s["name"]
    if style == 0:
        lines = [f"{name.upper()}", f"Sustainability Report {year}: key figures", f"Reporting period: 1 January {year} to 31 December {year}",
                 f"Net revenue: {cur} {_money(revenue, rng)}", f"Scope 1 emissions: {_mass(s1, rng)}", f"Scope 2 emissions (location-based): {_mass(s2, rng)}"]
        if s3 is not None:
            lines.append(f"Scope 3, category 1 (purchased goods and services): {_mass(s3, rng)}")
        lines.append("Assurance: limited assurance by an independent verifier" if rng.random() < 0.6 else "Assurance: none")
    elif style == 1:
        lines = [f"{name} - Climate disclosure FY{year}", "Metric | Value | Unit", f"Revenue | {revenue / 1e6:,.1f} | {cur} million",
                 f"Scope 1 | {s1:,.0f} | tCO2e", f"Scope 2 | {s2:,.0f} | tCO2e"]
        if s3 is not None:
            lines.append(f"Scope 3 cat. 1 upstream | {s3:,.0f} | tCO2e")
        lines.append(f"Verification | {'reasonable' if rng.random() < 0.3 else 'limited'} | -")
    else:
        lines = [f"Nachhaltigkeitsbericht {year} / Sustainability statement", f"Unternehmen / Company: {name}", f"Umsatz (revenue): {_money(revenue, rng)} {cur}",
                 f"Scope-1-Emissionen: {_mass(s1, rng)}", f"Scope-2-Emissionen: {_mass(s2, rng)}"]
        if s3 is not None:
            lines.append(f"Scope 3 Kategorie 1 (eingekaufte Waren): {_mass(s3, rng)}")
    if principals:
        lines.append("Principal material suppliers: " + "; ".join(principals[:2]))
    return "\n".join(lines)


# --- truth helpers for tests and the evaluation ------------------------------------------------------------------------------
def true_influence(world, emissions):
    """emissions: {supplier idx: true tCO2e attributable to us}. Returns {idx: own + embodied in what our tier-1 suppliers buy from it}."""
    out = dict(emissions)
    for s in world["suppliers"]:
        for m, share in s["upstream"].items():
            out[m] = out.get(m, 0.0) + emissions.get(s["idx"], 0.0) * share
    return out
