# SQL feladatmegoldo - PowerShell valtozat (nem kell Python, nem kell semmit telepiteni)
# Mappaba kell: adatbazis.sql, feladatok.txt   (opcionalis: elvart.txt)
# Inditas: dupla kattintas az inditas_ps.bat fajlra
# Eredmeny: megoldasok.txt

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

# ====== BEALLITASOK (altalaban nem kell atirni semmit) ======
$API_URL    = "https://api.groq.com/openai/v1"
$KULCS_FAJL = "kulcs.txt"
$ELSODLEGES = @("openai/gpt-oss-120b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b", "llama-3.1-8b-instant")

$DB_HOST   = "localhost"
$DB_PORT   = "3306"
$DB_USER   = "root"
$DB_JELSZO = ""          # XAMPP alapertelmezett: ures
$DB_NEV    = ""          # ures: az sql fajlbol keresi, ha nincs benne, megkerdezi
$MYSQL_EXE = ""          # ures: automatikusan megkeresi a XAMPP mappajaban

$SQL_FAJL     = "adatbazis.sql"
$FELADAT_FAJL = "feladatok.txt"
$ELVART_FAJL  = "elvart.txt"       # opcionalis: a mintakepek szovegesen
$KIMENET_FAJL = "megoldasok.txt"

$MAX_SOR     = 50        # ennyi sort ir ki lekerdezesenkent a txt-be
$MAX_JAVITAS = 2         # hiba/elteres eseten ennyiszer kerunk javitast
$CSAK_SELECT = $true     # $true: csak SELECT/SHOW fut le
# ============================================================

$UTF8 = New-Object System.Text.UTF8Encoding($false)
$global:MODELLEK = $ELSODLEGES

# ---------- Groq API ----------
function Http-Hivas($url, $kulcs, $adat) {
    $p = @{
        Uri             = $url
        UseBasicParsing = $true
        UserAgent       = "Mozilla/5.0 (sql-megoldo)"
        TimeoutSec      = 180
        Headers         = @{ Authorization = "Bearer $kulcs" }
    }
    if ($adat -ne $null) {
        $json = $adat | ConvertTo-Json -Depth 6 -Compress
        $p.Method = "POST"
        $p.ContentType = "application/json; charset=utf-8"
        $p.Body = $UTF8.GetBytes($json)
    } else {
        $p.Method = "GET"
    }
    try {
        $r = Invoke-WebRequest @p
        return $UTF8.GetString($r.RawContentStream.ToArray())
    } catch {
        $kod = ""
        $torzs = ""
        if ($_.Exception.Response) {
            try { $kod = [int]$_.Exception.Response.StatusCode } catch {}
            try {
                $sr = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream(), $UTF8)
                $torzs = $sr.ReadToEnd()
            } catch {}
        }
        if ("$kod" -ne "") {
            if ($torzs.Length -gt 400) { $torzs = $torzs.Substring(0, 400) }
            throw "HTTP $kod $torzs"
        }
        throw "Nincs halozati kapcsolat a Groq-hoz (ceges halozat/proxy?): $($_.Exception.Message)"
    }
}

function Modellek-Valasztasa($kulcs) {
    try {
        $o = (Http-Hivas "$API_URL/models" $kulcs $null) | ConvertFrom-Json
        $elerheto = @($o.data | ForEach-Object { $_.id })
    } catch {
        Write-Host "  Nem sikerult lekerdezni a modellek listajat: $($_.Exception.Message)"
        return $ELSODLEGES
    }
    $elerheto = @($elerheto | Where-Object { ($_.ToLower()) -notmatch 'whisper|orpheus|guard|safeguard|compound|tts|embed' })
    if ($elerheto.Count -eq 0) { return $ELSODLEGES }
    $sorrend = @($ELSODLEGES | Where-Object { $elerheto -contains $_ })
    $tobbi = @($elerheto | Where-Object { $sorrend -notcontains $_ })
    $sorrend = $sorrend + $tobbi
    return @($sorrend | Select-Object -First 5)
}

function Hivas-AI($kulcs, $uzenet) {
    $utolso = ""
    foreach ($modell in $global:MODELLEK) {
        $kovetkezo = $false
        for ($k = 0; $k -lt 4 -and -not $kovetkezo; $k++) {
            try {
                $adat = @{
                    model       = $modell
                    messages    = @(@{ role = "user"; content = $uzenet })
                    temperature = 0.1
                }
                $szoveg = Http-Hivas "$API_URL/chat/completions" $kulcs $adat
                $valasz = $szoveg | ConvertFrom-Json
                $tartalom = $valasz.choices[0].message.content
                if ($tartalom -eq $null) { $tartalom = "" }
                return $tartalom
            } catch {
                $hibaSzoveg = "$($_.Exception.Message)"
                $utolso = $hibaSzoveg
                $l = $hibaSzoveg.ToLower()
                if ($l -match '^http (429|503)|rate limit') {
                    $varakozas = 10 * ($k + 1)
                    Write-Host "  Korlat/tulterheltseg, ujraprobalom $varakozas mp mulva..."
                    Start-Sleep -Seconds $varakozas
                } elseif ($l -match '^http 404|does not exist|decommission') {
                    Write-Host "  A(z) $modell modell nem elerheto, kovetkezot probalok..."
                    $kovetkezo = $true
                } else {
                    throw
                }
            }
        }
    }
    throw "A Groq jelenleg nem elerheto: $utolso"
}

function Kulcs-Beolvas {
    $k = $env:GROQ_API_KEY
    if ($k) { return $k.Trim() }
    if (Test-Path $KULCS_FAJL) {
        $k = Get-Content $KULCS_FAJL -Raw -Encoding UTF8
        if ($k -and $k.Trim()) { return $k.Trim() }
    }
    $k = Read-Host "Illeszd be a Groq API kulcsot (gsk_...)"
    if ($k) {
        $k = $k.Trim()
        try {
            [System.IO.File]::WriteAllText((Join-Path (Get-Location).Path $KULCS_FAJL), $k, $UTF8)
            Write-Host "A kulcsot elmentettem a(z) $KULCS_FAJL fajlba, igy legkozelebb nem kell megadni."
        } catch {}
    }
    return $k
}

# ---------- MySQL a XAMPP sajat mysql.exe programjaval ----------
function Mysql-Exe-Keres {
    if ($MYSQL_EXE -and (Test-Path $MYSQL_EXE)) { return $MYSQL_EXE }
    $jeloltek = @(
        "C:\xampp\mysql\bin\mysql.exe",
        "D:\xampp\mysql\bin\mysql.exe",
        "E:\xampp\mysql\bin\mysql.exe",
        "C:\Program Files\xampp\mysql\bin\mysql.exe"
    )
    foreach ($j in $jeloltek) {
        if (Test-Path $j) { return $j }
    }
    $c = Get-Command mysql.exe -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}

function Sql-Futtat($exe, $adatbazis, $sql) {
    $arg = "-h $DB_HOST -P $DB_PORT -u $DB_USER --default-character-set=utf8mb4 --batch --raw"
    if ($DB_JELSZO) { $arg += " -p$DB_JELSZO" }
    if ($adatbazis) { $arg += " $adatbazis" }
    $sql = $sql.Trim()
    if (-not $sql.EndsWith(";")) { $sql += ";" }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = $arg
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.StandardOutputEncoding = $UTF8
    $psi.StandardErrorEncoding = $UTF8
    $p = [System.Diagnostics.Process]::Start($psi)

    $bajtok = $UTF8.GetBytes($sql)
    $p.StandardInput.BaseStream.Write($bajtok, 0, $bajtok.Length)
    $p.StandardInput.Close()
    $o = $p.StandardOutput.ReadToEndAsync()
    $e = $p.StandardError.ReadToEndAsync()
    $p.WaitForExit()
    $ki = $o.Result
    $hiba = $e.Result.Trim()
    if ($p.ExitCode -ne 0) {
        if (-not $hiba) { $hiba = "ismeretlen MySQL hiba" }
        throw $hiba
    }

    $sorok = New-Object 'System.Collections.Generic.List[object]'
    $sorSzovegek = @($ki -split "`n" | ForEach-Object { $_.TrimEnd("`r") } | Where-Object { $_ -ne "" })
    if ($sorSzovegek.Count -eq 0) {
        return [PSCustomObject]@{ Van = $false; Oszlopok = @(); Sorok = $sorok }
    }
    $oszlopok = @($sorSzovegek[0] -split "`t")
    for ($i = 1; $i -lt $sorSzovegek.Count; $i++) {
        $sorok.Add(@($sorSzovegek[$i] -split "`t"))
    }
    return [PSCustomObject]@{ Van = $true; Oszlopok = $oszlopok; Sorok = $sorok }
}

function Db-Nev-Meghataroz($sqlTartalom) {
    if ($DB_NEV) { return $DB_NEV }
    $mintak = @(
        '(?i)CREATE DATABASE\s+(?:IF NOT EXISTS\s+)?`?(\w+)`?',
        '(?im)^\s*USE\s+`?(\w+)`?',
        '(?i)Database:\s*`(\w+)`'
    )
    foreach ($minta in $mintak) {
        $m = [regex]::Match($sqlTartalom, $minta)
        if ($m.Success) { return $m.Groups[1].Value }
    }
    return (Read-Host "Add meg az adatbazis nevet (phpMyAdmin bal oldalan latszik)").Trim()
}

# ---------- fajlok, szerkezet ----------
function Fajl-Olvas($nev) {
    if (-not (Test-Path $nev)) {
        Write-Host "HIBA: Nem talalom a '$nev' fajlt a mappaban!"
        return $null
    }
    return (Get-Content $nev -Raw -Encoding UTF8)
}

function Tabla-Szerkezet($sqlTartalom) {
    $talalatok = [regex]::Matches($sqlTartalom, 'CREATE TABLE.*?;', 'Singleline,IgnoreCase')
    if ($talalatok.Count -eq 0) {
        Write-Host "FIGYELEM: Nem talaltam CREATE TABLE reszt, az elso 30 000 karaktert kuldom."
        if ($sqlTartalom.Length -gt 30000) { return $sqlTartalom.Substring(0, 30000) }
        return $sqlTartalom
    }
    return (($talalatok | ForEach-Object { $_.Value }) -join "`n`n")
}

function Sql-Tisztit($s) {
    $s = $s.Trim()
    $s = [regex]::Replace($s, '^```(?:sql)?', '', 'IgnoreCase').Trim()
    $s = [regex]::Replace($s, '```$', '').Trim()
    return $s
}

# ---------- elvart kimenet (mintakepek szovegesen) ----------
function Feladat-Kulcs($cim) {
    $m = [regex]::Match($cim, '\d+(\s*/\s*[a-zA-Z]\b)?')
    if ($m.Success) { return ($m.Value -replace '\s+', '').ToLower() }
    return $cim.Trim().ToLower()
}

function Elvart-Beolvas($nev) {
    $eredmeny = @{}
    if (-not (Test-Path $nev)) { return $eredmeny }
    $sorok = Get-Content $nev -Encoding UTF8
    $blokkok = @()
    $akt = $null
    foreach ($sor in $sorok) {
        if ($sor -match '^--\s*(.*)$') {
            if ($akt) { $blokkok += ,$akt }
            $akt = @{ Cim = $Matches[1]; Sorok = @() }
        } elseif ($akt -and $sor.Trim() -ne "") {
            $akt.Sorok += $sor.TrimEnd()
        }
    }
    if ($akt) { $blokkok += ,$akt }

    foreach ($b in $blokkok) {
        if ($b.Sorok.Count -lt 2) { continue }
        $reszek = New-Object 'System.Collections.Generic.List[object]'
        foreach ($s in $b.Sorok) {
            $mezok = @($s -split '\|' | ForEach-Object { $_.Trim() })
            $reszek.Add($mezok)
        }
        $sorLista = New-Object 'System.Collections.Generic.List[object]'
        for ($i = 1; $i -lt $reszek.Count; $i++) { $sorLista.Add($reszek[$i]) }
        $eredmeny[(Feladat-Kulcs $b.Cim)] = @{
            Oszlopok = $reszek[0]
            Sorok    = $sorLista
            Nyers    = ($b.Sorok -join "`n")
        }
    }
    return $eredmeny
}

function Normalizal($x) {
    if ($x -eq $null) { $s = "NULL" } else { $s = "$x".Trim() }
    $d = [decimal]0
    $inv = [System.Globalization.CultureInfo]::InvariantCulture
    if ([decimal]::TryParse($s.Replace(",", "."), [System.Globalization.NumberStyles]::Float, $inv, [ref]$d)) {
        return $d.ToString("0.############################", $inv)
    }
    return $s
}

function Sor-Normalizal($sor) {
    return ((@($sor) | ForEach-Object { Normalizal $_ }) -join "`t")
}

function Elteres($oszlopok, $sorok, $elvart) {
    $eo = @($elvart.Oszlopok)
    $es = $elvart.Sorok
    $hibak = @()
    $a = ((@($oszlopok) | ForEach-Object { "$_".ToLower() }) -join "|")
    $b = ((@($eo) | ForEach-Object { "$_".ToLower() }) -join "|")
    if ($a -ne $b) {
        $hibak += "Az oszlopok (aliasok) kapott: $(@($oszlopok) -join ', '), elvart: $($eo -join ', ')"
    } elseif ($sorok.Count -ne $es.Count) {
        $hibak += "A sorok szama kapott: $($sorok.Count), elvart: $($es.Count)"
    } else {
        for ($i = 0; $i -lt $sorok.Count; $i++) {
            if ((Sor-Normalizal $sorok[$i]) -ne (Sor-Normalizal $es[$i])) {
                $hibak += "A(z) $($i + 1). sor kapott: $(@($sorok[$i]) -join ', '), elvart: $(@($es[$i]) -join ', ')"
                if ($hibak.Count -ge 3) { break }
            }
        }
    }
    return ($hibak -join "`n")
}

# ---------- AI kerek ----------
function Lekerdezesek-Kerese($kulcs, $szerkezet, $feladatok, $elvartSzoveg) {
    $elvartBlokk = ""
    if ($elvartSzoveg) {
        $elvartBlokk = "`n--- ELVART KIMENETEK (a lekerdezes eredmenye pontosan ezzel egyezzen: oszlopnevek / aliasok, sorrend, rendezes, kerekites) ---`n" + $elvartSzoveg
    }
    $prompt = @"
Te profi MySQL / MariaDB szakerto vagy.
Az alabbi adatbazis-szerkezethez ird meg a feladatok SQL lekerdezeseit.

Szabalyok:
- Szabvanyos MySQL szintaxis, a XAMPP-ban azonnal futtathato legyen.
- Pontosan azokat a tabla- es oszlopneveket hasznald, amik a szerkezetben szerepelnek.
- Ha a feladat megadja az eredmeny oszlopainak nevet, azt AS aliasszal pontosan igy add meg, ugyanabban a sorrendben, es tartsd be a kert rendezest, kerekitest.
- Feladatonkent egy lekerdezes (ha a feladat tobb reszbol all, a reszeket kulon feladatkent add meg, pl. "2/a", "2/b").
- A magyarazat rovid, magyar nyelvu legyen.

Valaszolj KIZAROLAG egy JSON objektummal, ebben a formaban:
{"megoldasok": [{"feladat": "1. feladat", "sql": "SELECT ...;", "magyarazat": "..."}]}

--- ADATBAZIS SZERKEZET ---
$szerkezet

--- FELADATOK ---
$feladatok
$elvartBlokk
"@
    $szoveg = Hivas-AI $kulcs $prompt
    $m = [regex]::Match($szoveg, '\{.*\}|\[.*\]', 'Singleline')
    if ($m.Success) { $json = $m.Value } else { $json = $szoveg }
    $adat = $json | ConvertFrom-Json
    if ($adat.megoldasok) { return @($adat.megoldasok) }
    return @($adat)
}

function Javitas-Kerese($kulcs, $szerkezet, $feladat, $sql, $hiba, $elvartNyers) {
    $elvart = ""
    if ($elvartNyers) { $elvart = "`nElvart kimenet (oszlopnevek es sorok):`n$elvartNyers`n" }
    $prompt = @"
Ez a MySQL lekerdezes hibas vagy nem a vart eredmenyt adja. Javitsd ki.
Az oszlopokat AS aliasszal pontosan az elvart nevekkel add meg, az elvart sorrendben.
Valaszolj KIZAROLAG a javitott SQL-lel, magyarazat es markdown jeloles nelkul.

Szerkezet:
$szerkezet

Feladat: $feladat
Lekerdezes:
$sql

Hiba / elteres:
$hiba
$elvart
"@
    return (Sql-Tisztit (Hivas-AI $kulcs $prompt))
}

# ---------- fo program ----------
function Main {
    $sqlTartalom = Fajl-Olvas $SQL_FAJL
    if ($sqlTartalom -eq $null) { return }
    $feladatok = Fajl-Olvas $FELADAT_FAJL
    if ($feladatok -eq $null) { return }
    $szerkezet = Tabla-Szerkezet $sqlTartalom

    $elvartAdat = Elvart-Beolvas $ELVART_FAJL
    $elvartSzoveg = ""
    if ($elvartAdat.Count -gt 0) {
        Write-Host "Elvart kimenetek betoltve: $($elvartAdat.Count) feladathoz ($ELVART_FAJL)."
        $elvartSzoveg = Fajl-Olvas $ELVART_FAJL
    }

    $kulcs = Kulcs-Beolvas
    if (-not $kulcs) { Write-Host "HIBA: Nincs Groq API kulcs."; return }

    $exe = Mysql-Exe-Keres
    if (-not $exe) {
        Write-Host "HIBA: Nem talalom a XAMPP mysql.exe programjat. Add meg az utjat a MYSQL_EXE beallitasban (pl. C:\xampp\mysql\bin\mysql.exe)."
        return
    }

    $adatbazis = Db-Nev-Meghataroz $sqlTartalom
    Write-Host "Adatbazis: $adatbazis"
    try {
        [void](Sql-Futtat $exe $adatbazis "SELECT 1;")
    } catch {
        Write-Host "Nem sikerult csatlakozni: $($_.Exception.Message)"
        Write-Host "Fut a MySQL a XAMPP Control Panelben? Jo az adatbazis neve?"
        try {
            $lista = Sql-Futtat $exe "" "SHOW DATABASES;"
            if ($lista.Van) {
                $nevek = @($lista.Sorok | ForEach-Object { $_[0] })
                Write-Host ("Elerheto adatbazisok: " + ($nevek -join ", "))
            }
        } catch {}
        return
    }

    $global:MODELLEK = @(Modellek-Valasztasa $kulcs)
    Write-Host ("Hasznalt modellek (sorrendben): " + ($global:MODELLEK -join ", "))

    Write-Host "Lekerdezesek generalasa a Groq-kal..."
    try {
        $megoldasok = @(Lekerdezesek-Kerese $kulcs $szerkezet $feladatok $elvartSzoveg)
    } catch {
        Write-Host "Hiba az AI hivasa kozben: $($_.Exception.Message)"
        return
    }

    $kimenet = New-Object 'System.Collections.Generic.List[string]'
    foreach ($m in $megoldasok) {
        $cim = "$($m.feladat)"
        if (-not $cim) { $cim = "?" }
        $sql = Sql-Tisztit "$($m.sql)"
        $magyarazat = "$($m.magyarazat)"
        Write-Host "Futtatas: $cim"

        $kimenet.Add(("=" * 60))
        $kimenet.Add($cim)
        $kimenet.Add(("=" * 60))
        $kimenet.Add($sql)
        $kimenet.Add("")
        $kimenet.Add("Magyarazat: $magyarazat")
        $kimenet.Add("")

        if ($CSAK_SELECT -and ($sql -notmatch '^\s*(SELECT|SHOW|WITH|DESCRIBE)\b')) {
            $kimenet.Add("[Nem futtattam le: nem SELECT jellegu lekerdezes.]")
            $kimenet.Add("")
            continue
        }

        $elvart = $null
        $kulcsF = Feladat-Kulcs $cim
        if ($elvartAdat.ContainsKey($kulcsF)) { $elvart = $elvartAdat[$kulcsF] }

        for ($kiserlet = 0; $kiserlet -le $MAX_JAVITAS; $kiserlet++) {
            $hiba = $null
            $eredm = $null
            try {
                $eredm = Sql-Futtat $exe $adatbazis $sql
                if ($eredm.Van -and $elvart) {
                    $elt = Elteres $eredm.Oszlopok $eredm.Sorok $elvart
                    if ($elt) { $hiba = "A lekerdezes lefutott, de az eredmeny elter az elvarttol:`n$elt" }
                }
            } catch {
                $hiba = "$($_.Exception.Message)"
                $eredm = $null
            }

            if ($hiba -and $kiserlet -lt $MAX_JAVITAS) {
                $elsoSor = ($hiba -split "`n")[0]
                Write-Host "  Hiba/elteres, javitast kerek ($($kiserlet + 1)/$MAX_JAVITAS): $elsoSor"
                $nyers = ""
                if ($elvart) { $nyers = $elvart.Nyers }
                try {
                    $sql = Javitas-Kerese $kulcs $szerkezet $cim $sql $hiba $nyers
                } catch {
                    $kimenet.Add("HIBA a javitas kerese kozben: $($_.Exception.Message)")
                    break
                }
                $kimenet.Add("[Javitott lekerdezes $($kiserlet + 1). proba:]")
                $kimenet.Add($sql)
                continue
            }

            if ($eredm -eq $null) {
                if ($hiba) { $kimenet.Add("HIBA: $hiba") }
                else { $kimenet.Add("[Lefutott.]") }
            } elseif (-not $eredm.Van) {
                $kimenet.Add("[Lefutott, de nincs eredmenysor.]")
            } else {
                $db = $eredm.Sorok.Count
                $kimenet.Add("Eredmeny ($db sor):")
                $kimenet.Add(($eredm.Oszlopok -join " | "))
                $kiir = [Math]::Min($db, $MAX_SOR)
                for ($i = 0; $i -lt $kiir; $i++) {
                    $kimenet.Add((@($eredm.Sorok[$i]) -join " | "))
                }
                if ($db -gt $MAX_SOR) { $kimenet.Add("... (tovabbi $($db - $MAX_SOR) sor)") }
                if ($hiba) { $kimenet.Add("FIGYELEM: $hiba") }
                elseif ($elvart) { $kimenet.Add("Az eredmeny egyezik az elvart kimenettel.") }
            }
            break
        }
        $kimenet.Add("")
    }

    $ut = Join-Path (Get-Location).Path $KIMENET_FAJL
    [System.IO.File]::WriteAllText($ut, ($kimenet -join "`r`n"), (New-Object System.Text.UTF8Encoding($true)))
    Write-Host "SIKER! Elmentve: $KIMENET_FAJL"
}

try {
    Main
} catch {
    Write-Host "Varatlan hiba: $($_.Exception.Message)"
}
