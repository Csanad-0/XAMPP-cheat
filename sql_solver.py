import os
import re
import json
import time
from openai import OpenAI
import mysql.connector


API_KEY = os.environ.get("GROQ_API_KEY", "your_api_key")
ELSODLEGES = ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b", "llama-3.1-8b-instant"]
MODELLEK = list(ELSODLEGES)

DB_HOST = "localhost"
DB_PORT = 3306
DB_USER = "root"
DB_JELSZO = ""
DB_NEV = "name"

SQL_FAJL = "name.sql"
FELADAT_FAJL = "name_task.txt"
KIMENET_FAJL = "answers.txt"

MAX_SOR = 50               
MAX_JAVITAS = 2            
CSAK_SELECT_FUTTATAS = True
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


def lekerdezesek_kerese(client, szerkezet, feladatok):
    prompt = f"""Te profi MySQL / MariaDB szakerto vagy.
Az alabbi adatbazis-szerkezethez ird meg a feladatok SQL lekerdezeseit.

Szabalyok:
- Szabvanyos MySQL szintaxis, a XAMPP-ban azonnal futtathato legyen.
- Pontosan azokat a tabla- es oszlopneveket hasznald, amik a szerkezetben szerepelnek.
- Feladatonkent egy lekerdezes (ha a feladat tobb reszbol all, a reszeket kulon feladatkent add meg, pl. "2/a", "2/b").
- A magyarazat rovid, magyar nyelvu legyen.

Valaszolj KIZAROLAG egy JSON objektummal, ebben a formaban:
{{"megoldasok": [{{"feladat": "1. feladat", "sql": "SELECT ...;", "magyarazat": "..."}}]}}

--- ADATBAZIS SZERKEZET ---
{szerkezet}

--- FELADATOK ---
{feladatok}
"""
    szoveg = ai_hivas(client, prompt)
    talalat = re.search(r"\{.*\}|\[.*\]", szoveg, flags=re.S)
    adat = json.loads(talalat.group(0) if talalat else szoveg)
    if isinstance(adat, dict):
        return adat.get("megoldasok", [])
    return adat


def javitas_kerese(client, szerkezet, feladat, sql, hiba):
    prompt = f"""Ez a MySQL lekerdezes hibat adott. Javitsd ki.
Valaszolj KIZAROLAG a javitott SQL-lel, magyarazat es markdown jeloles nelkul.

Szerkezet:
{szerkezet}

Feladat: {feladat}
Lekerdezes:
{sql}

Hibauzenet:
{hiba}
"""
    return sql_tisztit(ai_hivas(client, prompt))


def futtat(kurzor, sql):
    """Visszaadja: (oszlopnevek, sorok) vagy (None, None), ha nincs eredmenytabla."""
    kurzor.execute(sql)
    if kurzor.description is None:
        return None, None
    oszlopok = [o[0] for o in kurzor.description]
    sorok = kurzor.fetchall()
    return oszlopok, sorok


def main():
    if API_KEY == "IDE_MASOLD_A_GROQ_KULCSOT":
        print("HIBA: Irj be Groq API kulcsot az API_KEY helyere!")
        return

    sql_tartalom = fajl_olvas(SQL_FAJL)
    feladatok = fajl_olvas(FELADAT_FAJL)
    szerkezet = tabla_szerkezet(sql_tartalom)

    client = OpenAI(api_key=API_KEY, base_url="https://api.groq.com/openai/v1")

    global MODELLEK
    MODELLEK = modellek_valasztasa(client)
    print("Hasznalt modellek (sorrendben): " + ", ".join(MODELLEK))

    print("Lekerdezesek generalasa a Groq-kal...")
    try:
        megoldasok = lekerdezesek_kerese(client, szerkezet, feladatok)
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

        for kiserlet in range(MAX_JAVITAS + 1):
            try:
                oszlopok, sorok = futtat(kurzor, sql)
                if oszlopok is None:
                    kapcsolat.commit()
                    kimenet.append("[Lefutott, nincs eredmenytabla.]")
                else:
                    kimenet.append("Eredmeny (" + str(len(sorok)) + " sor):")
                    kimenet.append(" | ".join(oszlopok))
                    for sor in sorok[:MAX_SOR]:
                        kimenet.append(" | ".join(str(x) for x in sor))
                    if len(sorok) > MAX_SOR:
                        kimenet.append(f"... (tovabbi {len(sorok) - MAX_SOR} sor)")
                break
            except Exception as e:
                if kiserlet < MAX_JAVITAS:
                    print(f"  Hiba, javitast kerek ({kiserlet + 1}/{MAX_JAVITAS}): {e}")
                    try:
                        sql = javitas_kerese(client, szerkezet, cim, sql, str(e))
                        kimenet.append(f"[Javitott lekerdezes {kiserlet + 1}. proba:]")
                        kimenet.append(sql)
                    except Exception as e2:
                        kimenet.append(f"HIBA a javitas kerese kozben: {e2}")
                        break
                else:
                    kimenet.append(f"HIBA: {e}")
        kimenet.append("")

    kurzor.close()
    kapcsolat.close()

    with open(KIMENET_FAJL, "w", encoding="utf-8") as f:
        f.write("\n".join(kimenet))

    print(f"SIKER! Elmentve: {KIMENET_FAJL}")


if __name__ == "__main__":
    main()
