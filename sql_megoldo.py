import os
import re
import json
import time
from decimal import Decimal
from openai import OpenAI
import mysql.connector

# ====== BEALLITASOK ======
API_KEY = os.environ.get("GROQ_API_KEY", "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")  # console.groq.com/keys
ELSODLEGES = ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b", "llama-3.1-8b-instant"]
# A script lekerdezi, mely modellek elerhetok a kulcsodhoz, es ezekbol valaszt.
MODELLEK = list(ELSODLEGES)

DB_HOST = "localhost"
DB_PORT = 3306
DB_USER = "root"
DB_JELSZO = ""             # XAMPP alapertelmezett: ures
DB_NEV = "sql1"  # ide a phpMyAdminban importalt adatbazis neve

SQL_FAJL = "adatbazis.sql"
FELADAT_FAJL = "feladatok.txt"
ELVART_FAJL = "elvart.txt"   # opcionalis: a munkaltato mintakepeinek szovegesen leirt tartalma
KIMENET_FAJL = "megoldasok.txt"

MAX_SOR = 50               # ennyi sort ir ki lekerdezesenkent a txt-be
MAX_JAVITAS = 2            # hiba eseten ennyiszer kerjuk az AI-t javitasra
KEP_KESZITES = False       # True: minden eredmenytablarol PNG kep keszul (phpMyAdmin-szeru)
KEP_MAPPA = "kepek"        # ide kerulnek a kepek
MAX_KEP_SOR = 30           # ennyi sor kerul egy kepre
CSAK_SELECT_FUTTATAS = True  # True: csak SELECT/SHOW fut le, INSERT/UPDATE/DELETE nem
# =========================


def elerheto_modellek(client):
    """Lekerdezi a kulcsodhoz tenylegesen elerheto szoveges modelleket."""
    try:
        azonositok = [m.id for m in client.models.list().data]
    except Exception as e:
        print(f"  Nem sikerult lekerdezni a modellek listajat: {e}")
        return []
    kizar = ("whisper", "orpheus", "guard", "safeguard", "compound", "tts", "embed")
    return [m for m in azonositok if not any(k in m.lower() for k in kizar)]


def modellek_valasztasa(client):
    elerheto = elerheto_modellek(client)
    if not elerheto:
        return list(ELSODLEGES)
    sorrend = [m for m in ELSODLEGES if m in elerheto]
    sorrend += [m for m in elerheto if m not in sorrend]
    return sorrend[:5]


def ai_hivas(client, uzenet):
    """Groq hivas ujraprobalassal (429/503), es kovetkezo modellre valtassal. Visszaadja a valasz szoveget."""
    utolso_hiba = None
    for modell in MODELLEK:
        for kiserlet in range(4):
            try:
                valasz = client.chat.completions.create(
                    model=modell,
                    messages=[{"role": "user", "content": uzenet}],
                    temperature=0.1,
                )
                return valasz.choices[0].message.content or ""
            except Exception as e:
                utolso_hiba = e
                szoveg = str(e).lower()
                if "429" in szoveg or "503" in szoveg or "rate limit" in szoveg:
                    varakozas = 10 * (kiserlet + 1)
                    print(f"  Korlat/tulterheltseg, ujraprobalom {varakozas} mp mulva...")
                    time.sleep(varakozas)
                elif "404" in szoveg or "does not exist" in szoveg or "decommission" in szoveg:
                    print(f"  A(z) {modell} modell nem elerheto, kovetkezot probalok...")
                    break
                else:
                    raise
        else:
            print(f"  A(z) {modell} nem valaszol, masik modellt probalok...")
    raise RuntimeError(f"A Groq jelenleg nem elerheto: {utolso_hiba}")


def feladat_kulcs(cim):
    """'1. feladat' / 'Feladat 1' / '2/a' -> '1' / '1' / '2/a'"""
    m = re.search(r"\d+(?:\s*/\s*[a-zA-Z]\b)?", cim)
    return re.sub(r"\s+", "", m.group(0)).lower() if m else cim.strip().lower()


def elvart_beolvas(nev):
    """elvart.txt formatuma:
    -- 1. feladat
    oszlop1 | oszlop2 | oszlop3
    ertek | ertek | ertek
    Visszaad: {kulcs: (oszlopok, sorok, nyers_szoveg)}"""
    if not os.path.exists(nev):
        return {}
    with open(nev, "r", encoding="utf-8") as f:
        szoveg = f.read()
    eredmeny = {}
    for blokk in re.split(r"(?m)^--\s*", szoveg):
        sorok = [l.rstrip() for l in blokk.strip().splitlines() if l.strip()]
        if len(sorok) < 2:
            continue
        cim, tabla = sorok[0], sorok[1:]
        reszek = [[c.strip() for c in sor.split("|")] for sor in tabla]
        eredmeny[feladat_kulcs(cim)] = (reszek[0], reszek[1:], "\n".join(tabla))
    return eredmeny


def normal(x):
    """Osszehasonlitashoz: a szamokat egységes alakra hozza (64800.0000 == 64800)."""
    szoveg = "NULL" if x is None else str(x).strip()
    try:
        return format(Decimal(szoveg.replace(",", ".")).normalize(), "f")
    except Exception:
        return szoveg


def elteres(oszlopok, sorok, elvart):
    """Ures szoveg, ha egyezik; kulonben leirja az elteres(eke)t."""
    elvart_oszlopok, elvart_sorok = elvart[0], elvart[1]
    hibak = []
    if [str(o).lower() for o in oszlopok] != [o.lower() for o in elvart_oszlopok]:
        hibak.append(f"Az oszlopok (aliasok) kapott: {list(oszlopok)}, elvart: {elvart_oszlopok}")
    elif len(sorok) != len(elvart_sorok):
        hibak.append(f"A sorok szama kapott: {len(sorok)}, elvart: {len(elvart_sorok)}")
    else:
        for i, (kapott, vart) in enumerate(zip(sorok, elvart_sorok), start=1):
            if [normal(x) for x in kapott] != [normal(x) for x in vart]:
                hibak.append(f"A(z) {i}. sor kapott: {list(map(str, kapott))}, elvart: {vart}")
                if len(hibak) >= 3:
                    break
    return "\n".join(hibak)


def fajl_olvas(nev):
    try:
        with open(nev, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"HIBA: Nem talalom a '{nev}' fajlt a mappaban!")
        raise SystemExit(1)


def tabla_szerkezet(sql_tartalom):
    """Csak a CREATE TABLE utasitasokat tartja meg (az adatsorokra nincs szukseg)."""
    tablak = re.findall(r"CREATE TABLE.*?;", sql_tartalom, flags=re.S | re.I)
    if not tablak:
        print("FIGYELEM: Nem talaltam CREATE TABLE reszt, az elso 30 000 karaktert kuldom.")
        return sql_tartalom[:30000]
    return "\n\n".join(tablak)


def sql_tisztit(szoveg):
    szoveg = re.sub(r"^```(?:sql)?", "", szoveg.strip(), flags=re.I).strip()
    szoveg = re.sub(r"```$", "", szoveg).strip()
    return szoveg


def lekerdezesek_kerese(client, szerkezet, feladatok, elvart_szoveg=""):
    elvart_blokk = ""
    if elvart_szoveg:
        elvart_blokk = ("\n--- ELVART KIMENETEK (a lekerdezes eredmenye pontosan ezzel egyezzen: "
                        "oszlopnevek / aliasok, sorrend, rendezes, kerekites) ---\n" + elvart_szoveg)
    prompt = f"""Te profi MySQL / MariaDB szakerto vagy.
Az alabbi adatbazis-szerkezethez ird meg a feladatok SQL lekerdezeseit.

Szabalyok:
- Szabvanyos MySQL szintaxis, a XAMPP-ban azonnal futtathato legyen.
- Pontosan azokat a tabla- es oszlopneveket hasznald, amik a szerkezetben szerepelnek.
- Ha a feladat megadja az eredmeny oszlopainak nevet, azt AS aliasszal pontosan igy add meg, ugyanabban a sorrendben, es tartsd be a kert rendezest, kerekitest.
- Feladatonkent egy lekerdezes (ha a feladat tobb reszbol all, a reszeket kulon feladatkent add meg, pl. "2/a", "2/b").
- A magyarazat rovid, magyar nyelvu legyen.

Valaszolj KIZAROLAG egy JSON objektummal, ebben a formaban:
{{"megoldasok": [{{"feladat": "1. feladat", "sql": "SELECT ...;", "magyarazat": "..."}}]}}

--- ADATBAZIS SZERKEZET ---
{szerkezet}

--- FELADATOK ---
{feladatok}
{elvart_blokk}"""
    szoveg = ai_hivas(client, prompt)
    talalat = re.search(r"\{.*\}|\[.*\]", szoveg, flags=re.S)
    adat = json.loads(talalat.group(0) if talalat else szoveg)
    if isinstance(adat, dict):
        return adat.get("megoldasok", [])
    return adat


def javitas_kerese(client, szerkezet, feladat, sql, hiba, elvart_nyers=""):
    elvart = f"\nElvart kimenet (oszlopnevek es sorok):\n{elvart_nyers}\n" if elvart_nyers else ""
    prompt = f"""Ez a MySQL lekerdezes hibas vagy nem a vart eredmenyt adja. Javitsd ki.
Az oszlopokat AS aliasszal pontosan az elvart nevekkel add meg, az elvart sorrendben.
Valaszolj KIZAROLAG a javitott SQL-lel, magyarazat es markdown jeloles nelkul.

Szerkezet:
{szerkezet}

Feladat: {feladat}
Lekerdezes:
{sql}

Hiba / elteres:
{hiba}
{elvart}"""
    return sql_tisztit(ai_hivas(client, prompt))


def futtat(kurzor, sql):
    """Visszaadja: (oszlopnevek, sorok) vagy (None, None), ha nincs eredmenytabla."""
    kurzor.execute(sql)
    if kurzor.description is None:
        return None, None
    oszlopok = [o[0] for o in kurzor.description]
    sorok = kurzor.fetchall()
    return oszlopok, sorok


FONT_NORMAL = ["arial.ttf", "Arial.ttf", "segoeui.ttf", "DejaVuSans.ttf",
               "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
FONT_VASTAG = ["arialbd.ttf", "Arial Bold.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf",
               "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


def betutipus(lista, meret):
    from PIL import ImageFont
    for ut in lista:
        try:
            return ImageFont.truetype(ut, meret)
        except Exception:
            continue
    print("  FIGYELEM: nem talaltam TTF betutipust, az ekezetes betuk hibasak lehetnek a kepen.")
    return ImageFont.load_default()


def kep_keszit(oszlopok, sorok, cim):
    """phpMyAdmin-szeru eredmenytabla PNG-kent. Visszaadja a fajl utvonalat."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("  A kepkeszitéshez kell a Pillow: python -m pip install pillow")
        return None

    os.makedirs(KEP_MAPPA, exist_ok=True)
    nev = re.sub(r"[^\w\-]+", "_", cim, flags=re.U).strip("_") or "feladat"
    ut = os.path.join(KEP_MAPPA, nev + ".png")

    font = betutipus(FONT_NORMAL, 15)
    vastag = betutipus(FONT_VASTAG, 15)
    sorok = sorok[:MAX_KEP_SOR]
    szoveg = [[("NULL" if x is None else str(x)) for x in sor] for sor in sorok]
    szam = [[isinstance(x, (int, float, Decimal)) for x in sor] for sor in sorok]

    meres = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    pad, sor_mag = 8, 30
    szelessegek = []
    for i, o in enumerate(oszlopok):
        w = meres.textlength(str(o), font=vastag)
        for sor in szoveg:
            w = max(w, meres.textlength(sor[i], font=font))
        szelessegek.append(int(w) + 2 * pad)

    szeles = sum(szelessegek) + 1
    magas = sor_mag * (len(szoveg) + 1) + 1
    kep = Image.new("RGB", (szeles, magas), "white")
    d = ImageDraw.Draw(kep)

    d.rectangle([0, 0, szeles, sor_mag], fill="#f3f3f3")
    x = 0
    for i, o in enumerate(oszlopok):
        d.text((x + pad, 6), str(o), font=vastag, fill="#222222")
        x += szelessegek[i]
    d.line([0, sor_mag, szeles, sor_mag], fill="#aaaaaa")

    for r, sor in enumerate(szoveg):
        y = sor_mag * (r + 1)
        d.rectangle([0, y + 1, szeles, y + sor_mag], fill="#e6e6e6" if r % 2 == 0 else "#ffffff")
        x = 0
        for i, ertek in enumerate(sor):
            if szam[r][i]:
                w = meres.textlength(ertek, font=font)
                d.text((x + szelessegek[i] - pad - w, y + 7), ertek, font=font, fill="#222222")
            else:
                d.text((x + pad, y + 7), ertek, font=font, fill="#222222")
            x += szelessegek[i]

    kep.save(ut)
    return ut


def main():
    if API_KEY == "IDE_MASOLD_A_GROQ_KULCSOT":
        print("HIBA: Irj be Groq API kulcsot az API_KEY helyere!")
        return

    sql_tartalom = fajl_olvas(SQL_FAJL)
    feladatok = fajl_olvas(FELADAT_FAJL)
    szerkezet = tabla_szerkezet(sql_tartalom)
    ELVART = elvart_beolvas(ELVART_FAJL)
    elvart_szoveg = ""
    if ELVART:
        print(f"Elvart kimenetek betoltve: {len(ELVART)} feladathoz ({ELVART_FAJL}).")
        elvart_szoveg = fajl_olvas(ELVART_FAJL)

    client = OpenAI(api_key=API_KEY, base_url="https://api.groq.com/openai/v1")

    global MODELLEK
    MODELLEK = modellek_valasztasa(client)
    print("Hasznalt modellek (sorrendben): " + ", ".join(MODELLEK))

    print("Lekerdezesek generalasa a Groq-kal...")
    try:
        megoldasok = lekerdezesek_kerese(client, szerkezet, feladatok, elvart_szoveg)
    except Exception as e:
        print(f"Hiba az AI hivasa kozben: {e}")
        return

    print("Kapcsolodas az adatbazishoz...")
    try:
        kapcsolat = mysql.connector.connect(
            host=DB_HOST, port=DB_PORT, user=DB_USER,
            password=DB_JELSZO, database=DB_NEV,
        )
    except Exception as e:
        print(f"Nem sikerult csatlakozni (fut a MySQL a XAMPP-ban? Jo a DB_NEV?): {e}")
        return
    kurzor = kapcsolat.cursor()

    kimenet = []
    for m in megoldasok:
        cim = m.get("feladat", "?")
        sql = sql_tisztit(m.get("sql", ""))
        magyarazat = m.get("magyarazat", "")
        print(f"Futtatas: {cim}")

        kimenet.append("=" * 60)
        kimenet.append(cim)
        kimenet.append("=" * 60)
        kimenet.append(sql)
        kimenet.append("")
        kimenet.append(f"Magyarazat: {magyarazat}")
        kimenet.append("")

        if CSAK_SELECT_FUTTATAS and not re.match(r"\s*(SELECT|SHOW|WITH|DESCRIBE)\b", sql, re.I):
            kimenet.append("[Nem futtattam le: nem SELECT jellegu lekerdezes.]")
            kimenet.append("")
            continue

        elvart = ELVART.get(feladat_kulcs(cim))
        for kiserlet in range(MAX_JAVITAS + 1):
            hiba_szoveg = None
            oszlopok = sorok = None
            try:
                oszlopok, sorok = futtat(kurzor, sql)
                if oszlopok is None:
                    kapcsolat.commit()
                elif elvart:
                    elt = elteres(oszlopok, sorok, elvart)
                    if elt:
                        hiba_szoveg = "A lekerdezes lefutott, de az eredmeny elter az elvarttol:\n" + elt
            except Exception as e:
                hiba_szoveg = str(e)
                oszlopok = sorok = None

            if hiba_szoveg and kiserlet < MAX_JAVITAS:
                print(f"  Hiba/elteres, javitast kerek ({kiserlet + 1}/{MAX_JAVITAS}): {hiba_szoveg.splitlines()[0]}")
                try:
                    sql = javitas_kerese(client, szerkezet, cim, sql, hiba_szoveg,
                                         elvart[2] if elvart else "")
                except Exception as e2:
                    kimenet.append(f"HIBA a javitas kerese kozben: {e2}")
                    break
                kimenet.append(f"[Javitott lekerdezes {kiserlet + 1}. proba:]")
                kimenet.append(sql)
                continue

            # vegleges eredmeny kiirasa
            if oszlopok is None:
                if hiba_szoveg:
                    kimenet.append(f"HIBA: {hiba_szoveg}")
                else:
                    kimenet.append("[Lefutott, nincs eredmenytabla.]")
            else:
                kimenet.append("Eredmeny (" + str(len(sorok)) + " sor):")
                kimenet.append(" | ".join(oszlopok))
                for sor in sorok[:MAX_SOR]:
                    kimenet.append(" | ".join(str(x) for x in sor))
                if len(sorok) > MAX_SOR:
                    kimenet.append(f"... (tovabbi {len(sorok) - MAX_SOR} sor)")
                if KEP_KESZITES:
                    kep_utvonal = kep_keszit(oszlopok, sorok, cim)
                    if kep_utvonal:
                        kimenet.append(f"Kep: {kep_utvonal}")
                if hiba_szoveg:
                    kimenet.append("FIGYELEM: " + hiba_szoveg)
                elif elvart:
                    kimenet.append("Az eredmeny egyezik az elvart kimenettel.")
            break
        kimenet.append("")
    kurzor.close()
    kapcsolat.close()

    with open(KIMENET_FAJL, "w", encoding="utf-8") as f:
        f.write("\n".join(kimenet))

    print(f"SIKER! Elmentve: {KIMENET_FAJL}")


if __name__ == "__main__":
    main()