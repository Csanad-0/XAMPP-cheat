<?php
/*
 * SQL feladatmegoldo - XAMPP / PHP valtozat
 * Nem kell hozza Python, PowerShell, csomag vagy telepites: a XAMPP-ban levo PHP-t hasznalja.
 * A tablak szerkezetet kozvetlenul a MySQL-bol olvassa, az .sql fajlra nincs szukseg.
 *
 * Inditas: lasd a hozza adott inditas_php.bat fajlt, vagy masold a C:\xampp\htdocs mappaba
 * es nyisd meg: http://localhost/sql_megoldo.php
 */
set_time_limit(900);
mb_internal_encoding('UTF-8');
mysqli_report(MYSQLI_REPORT_OFF);
header('Content-Type: text/html; charset=utf-8');

// ====== BEALLITASOK ======
$API_URL    = 'https://api.groq.com/openai/v1';
$ELSODLEGES = ['openai/gpt-oss-120b', 'llama-3.3-70b-versatile', 'openai/gpt-oss-20b', 'llama-3.1-8b-instant'];
$DB_HOST = '127.0.0.1';
$DB_PORT = 3306;
$DB_USER = 'root';
$DB_PASS = '';            // XAMPP alapertelmezett: ures
$MAX_SOR = 50;            // ennyi sort ir ki lekerdezesenkent
$MAX_JAVITAS = 2;         // hiba/elteres eseten ennyiszer kerunk javitast
// =========================

$MODELLEK = $ELSODLEGES;
$NAPLO = [];
$SSL_KI = false;

function h($s) { return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8'); }
function logol($s) { global $NAPLO; $NAPLO[] = $s; }

// ---------- Groq API ----------
function ca_fajl() {
    $j = [];
    foreach (['curl.cainfo', 'openssl.cafile'] as $k) { $v = ini_get($k); if ($v) $j[] = $v; }
    $j[] = dirname(PHP_BINARY) . '/extras/ssl/cacert.pem';
    if (!empty($_SERVER['DOCUMENT_ROOT'])) {
        $j[] = $_SERVER['DOCUMENT_ROOT'] . '/../php/extras/ssl/cacert.pem';
        $j[] = $_SERVER['DOCUMENT_ROOT'] . '/../apache/bin/curl-ca-bundle.crt';
    }
    foreach (['C:/xampp', 'D:/xampp', 'E:/xampp'] as $x) {
        $j[] = "$x/php/extras/ssl/cacert.pem";
        $j[] = "$x/apache/bin/curl-ca-bundle.crt";
    }
    foreach ($j as $f) { if ($f && @is_file($f)) return $f; }
    return null;
}

function http_hivas($url, $kulcs, $adat = null) {
    global $SSL_KI;
    if (!function_exists('curl_init')) {
        throw new Exception('A PHP curl kiterjesztese nincs bekapcsolva (php.ini: extension=curl).');
    }
    $ch = curl_init($url);
    $opt = [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER => ['Authorization: Bearer ' . $kulcs, 'Content-Type: application/json'],
        CURLOPT_USERAGENT => 'Mozilla/5.0 (sql-megoldo)',
        CURLOPT_TIMEOUT => 180,
        CURLOPT_CONNECTTIMEOUT => 20,
    ];
    if ($adat !== null) {
        $opt[CURLOPT_POST] = true;
        $opt[CURLOPT_POSTFIELDS] = json_encode($adat, JSON_UNESCAPED_UNICODE);
    }
    if ($SSL_KI) {
        $opt[CURLOPT_SSL_VERIFYPEER] = false;
        $opt[CURLOPT_SSL_VERIFYHOST] = 0;
    } else {
        $ca = ca_fajl();
        if ($ca) $opt[CURLOPT_CAINFO] = $ca;
    }
    curl_setopt_array($ch, $opt);
    $valasz = curl_exec($ch);
    if ($valasz === false) {
        $hiba = curl_error($ch);
        $kod = curl_errno($ch);
        curl_close($ch);
        $toldalek = ($kod == 60 || $kod == 77)
            ? ' - A tanusitvany-ellenorzes nem sikerult. Jelold be lent a "Tanusitvany-ellenorzes kikapcsolasa" opciot (kevesbe biztonsagos).'
            : ' (ceges halozat/proxy?)';
        throw new Exception("Halozati hiba a Groq-hoz ($kod): $hiba$toldalek");
    }
    $http = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    if ($http != 200) {
        throw new Exception("HTTP $http " . mb_substr((string)$valasz, 0, 400));
    }
    return $valasz;
}

function modellek_valasztasa($kulcs) {
    global $API_URL, $ELSODLEGES;
    try {
        $o = json_decode(http_hivas("$API_URL/models", $kulcs), true);
        $elerheto = array_map(function ($m) { return $m['id']; }, $o['data'] ?? []);
    } catch (Exception $e) {
        logol('Nem sikerult lekerdezni a modellek listajat: ' . $e->getMessage());
        return $ELSODLEGES;
    }
    $elerheto = array_values(array_filter($elerheto, function ($m) {
        return !preg_match('/whisper|orpheus|guard|safeguard|compound|tts|embed/i', $m);
    }));
    if (!$elerheto) return $ELSODLEGES;
    $sorrend = array_values(array_intersect($ELSODLEGES, $elerheto));
    foreach ($elerheto as $m) { if (!in_array($m, $sorrend)) $sorrend[] = $m; }
    return array_slice($sorrend, 0, 5);
}

function ai_hivas($kulcs, $uzenet) {
    global $API_URL, $MODELLEK;
    $utolso = '';
    foreach ($MODELLEK as $modell) {
        for ($k = 0; $k < 4; $k++) {
            try {
                $v = json_decode(http_hivas("$API_URL/chat/completions", $kulcs, [
                    'model' => $modell,
                    'messages' => [['role' => 'user', 'content' => $uzenet]],
                    'temperature' => 0.1,
                ]), true);
                return $v['choices'][0]['message']['content'] ?? '';
            } catch (Exception $e) {
                $utolso = $e->getMessage();
                $l = mb_strtolower($utolso);
                if (preg_match('/^http (429|503)|rate limit/', $l)) {
                    $var = 10 * ($k + 1);
                    logol("Korlat/tulterheltseg, ujraprobalom $var mp mulva...");
                    sleep($var);
                } elseif (preg_match('/^http 404|does not exist|decommission/', $l)) {
                    logol("A(z) $modell modell nem elerheto, kovetkezot probalok...");
                    break;
                } else {
                    throw $e;
                }
            }
        }
    }
    throw new Exception("A Groq jelenleg nem elerheto: $utolso");
}

// ---------- MySQL ----------
function db_kapcsolat($nev = '') {
    global $DB_HOST, $DB_USER, $DB_PASS, $DB_PORT;
    $db = @new mysqli($DB_HOST, $DB_USER, $DB_PASS, $nev, $DB_PORT);
    if ($db->connect_errno) {
        throw new Exception('MySQL kapcsolodasi hiba: ' . $db->connect_error . ' (fut a MySQL a XAMPP Control Panelben?)');
    }
    $db->set_charset('utf8mb4');
    return $db;
}

function adatbazisok() {
    $db = db_kapcsolat();
    $r = $db->query('SHOW DATABASES');
    $lista = [];
    while ($s = $r->fetch_row()) {
        if (!in_array(strtolower($s[0]), ['information_schema', 'mysql', 'performance_schema', 'phpmyadmin', 'sys', 'test'])) {
            $lista[] = $s[0];
        }
    }
    return $lista;
}

function tabla_szerkezet($db) {
    $r = $db->query('SHOW TABLES');
    $t = [];
    while ($s = $r->fetch_row()) {
        $c = $db->query('SHOW CREATE TABLE `' . $db->real_escape_string($s[0]) . '`');
        if ($c && ($row = $c->fetch_row())) $t[] = $row[1] . ';';
    }
    return implode("\n\n", $t);
}

function sql_futtat($db, $sql) {
    $res = $db->query(trim($sql));
    if ($res === false) throw new Exception($db->error);
    if ($res === true) return ['van' => false, 'oszlopok' => [], 'sorok' => []];
    $oszlopok = array_map(function ($f) { return $f->name; }, $res->fetch_fields());
    $sorok = [];
    while ($r = $res->fetch_row()) {
        $sorok[] = array_map(function ($x) { return $x === null ? 'NULL' : (string)$x; }, $r);
    }
    $res->free();
    return ['van' => true, 'oszlopok' => $oszlopok, 'sorok' => $sorok];
}

function sql_tisztit($s) {
    $s = trim($s);
    $s = trim(preg_replace('/^```(?:sql)?/i', '', $s));
    $s = trim(preg_replace('/```$/', '', $s));
    return $s;
}

// ---------- elvart kimenet ----------
function feladat_kulcs($cim) {
    if (preg_match('/\d+(?:\s*\/\s*[a-zA-Z]\b)?/u', $cim, $m)) {
        return strtolower(preg_replace('/\s+/', '', $m[0]));
    }
    return strtolower(trim($cim));
}

function elvart_beolvas($szoveg) {
    $blokkok = [];
    $akt = null;
    foreach (preg_split('/\R/u', $szoveg) as $sor) {
        if (preg_match('/^--\s*(.*)$/u', $sor, $m)) {
            if ($akt) $blokkok[] = $akt;
            $akt = ['cim' => $m[1], 'sorok' => []];
        } elseif ($akt && trim($sor) !== '') {
            $akt['sorok'][] = rtrim($sor);
        }
    }
    if ($akt) $blokkok[] = $akt;
    $eredmeny = [];
    foreach ($blokkok as $b) {
        if (count($b['sorok']) < 2) continue;
        $reszek = array_map(function ($s) { return array_map('trim', explode('|', $s)); }, $b['sorok']);
        $eredmeny[feladat_kulcs($b['cim'])] = [
            'oszlopok' => $reszek[0],
            'sorok' => array_slice($reszek, 1),
            'nyers' => implode("\n", $b['sorok']),
        ];
    }
    return $eredmeny;
}

function normalizal($x) {
    $s = trim((string)$x);
    $t = str_replace(',', '.', $s);
    if ($t !== '' && is_numeric($t)) {
        $d = rtrim(rtrim(number_format((float)$t, 12, '.', ''), '0'), '.');
        return ($d === '' || $d === '-0') ? '0' : $d;
    }
    return $s;
}

function elteres($oszlopok, $sorok, $elvart) {
    $hibak = [];
    $a = implode('|', array_map('mb_strtolower', $oszlopok));
    $b = implode('|', array_map('mb_strtolower', $elvart['oszlopok']));
    if ($a !== $b) {
        $hibak[] = 'Az oszlopok (aliasok) kapott: ' . implode(', ', $oszlopok) . ', elvart: ' . implode(', ', $elvart['oszlopok']);
    } elseif (count($sorok) !== count($elvart['sorok'])) {
        $hibak[] = 'A sorok szama kapott: ' . count($sorok) . ', elvart: ' . count($elvart['sorok']);
    } else {
        foreach ($sorok as $i => $sor) {
            $n1 = implode("\t", array_map('normalizal', $sor));
            $n2 = implode("\t", array_map('normalizal', $elvart['sorok'][$i]));
            if ($n1 !== $n2) {
                $hibak[] = 'A(z) ' . ($i + 1) . '. sor kapott: ' . implode(', ', $sor) . ', elvart: ' . implode(', ', $elvart['sorok'][$i]);
                if (count($hibak) >= 3) break;
            }
        }
    }
    return implode("\n", $hibak);
}

// ---------- AI kerések ----------
function lekerdezesek_kerese($kulcs, $szerkezet, $feladatok, $elvartSzoveg) {
    $elvartBlokk = '';
    if ($elvartSzoveg !== '') {
        $elvartBlokk = "\n--- ELVART KIMENETEK (a lekerdezes eredmenye pontosan ezzel egyezzen: oszlopnevek / aliasok, sorrend, rendezes, kerekites) ---\n" . $elvartSzoveg;
    }
    $prompt = "Te profi MySQL / MariaDB szakerto vagy.\n"
        . "Az alabbi adatbazis-szerkezethez ird meg a feladatok SQL lekerdezeseit.\n\n"
        . "Szabalyok:\n"
        . "- Szabvanyos MySQL szintaxis, a XAMPP-ban azonnal futtathato legyen.\n"
        . "- Pontosan azokat a tabla- es oszlopneveket hasznald, amik a szerkezetben szerepelnek.\n"
        . "- Ha a feladat megadja az eredmeny oszlopainak nevet, azt AS aliasszal pontosan igy add meg, ugyanabban a sorrendben, es tartsd be a kert rendezest, kerekitest.\n"
        . "- Feladatonkent egy lekerdezes (ha a feladat tobb reszbol all, a reszeket kulon feladatkent add meg, pl. \"2/a\", \"2/b\").\n"
        . "- A magyarazat rovid, magyar nyelvu legyen.\n\n"
        . "Valaszolj KIZAROLAG egy JSON objektummal, ebben a formaban:\n"
        . '{"megoldasok": [{"feladat": "1. feladat", "sql": "SELECT ...;", "magyarazat": "..."}]}' . "\n\n"
        . "--- ADATBAZIS SZERKEZET ---\n$szerkezet\n\n"
        . "--- FELADATOK ---\n$feladatok\n$elvartBlokk";
    $szoveg = ai_hivas($kulcs, $prompt);
    $json = preg_match('/\{.*\}|\[.*\]/s', $szoveg, $m) ? $m[0] : $szoveg;
    $adat = json_decode($json, true);
    if (!is_array($adat)) throw new Exception('Az AI valasza nem ertelmezheto JSON-kent.');
    return isset($adat['megoldasok']) ? $adat['megoldasok'] : $adat;
}

function javitas_kerese($kulcs, $szerkezet, $feladat, $sql, $hiba, $elvartNyers) {
    $elvart = $elvartNyers !== '' ? "\nElvart kimenet (oszlopnevek es sorok):\n$elvartNyers\n" : '';
    $prompt = "Ez a MySQL lekerdezes hibas vagy nem a vart eredmenyt adja. Javitsd ki.\n"
        . "Az oszlopokat AS aliasszal pontosan az elvart nevekkel add meg, az elvart sorrendben.\n"
        . "Valaszolj KIZAROLAG a javitott SQL-lel, magyarazat es markdown jeloles nelkul.\n\n"
        . "Szerkezet:\n$szerkezet\n\nFeladat: $feladat\nLekerdezes:\n$sql\n\nHiba / elteres:\n$hiba\n$elvart";
    return sql_tisztit(ai_hivas($kulcs, $prompt));
}

// ---------- fo folyamat ----------
function feldolgoz($kulcs, $adatbazis, $feladatok, $elvartSzoveg, $csakSelect) {
    global $MODELLEK, $MAX_SOR, $MAX_JAVITAS;
    $db = db_kapcsolat($adatbazis);
    $szerkezet = tabla_szerkezet($db);
    if (trim($szerkezet) === '') throw new Exception('Az adatbazisban nincsenek tablak. Jo adatbazist valasztottal?');

    $elvartAdat = $elvartSzoveg !== '' ? elvart_beolvas($elvartSzoveg) : [];
    if ($elvartAdat) logol('Elvart kimenetek betoltve ' . count($elvartAdat) . ' feladathoz.');

    $MODELLEK = modellek_valasztasa($kulcs);
    logol('Hasznalt modellek (sorrendben): ' . implode(', ', $MODELLEK));
    logol('Lekerdezesek generalasa...');
    $megoldasok = lekerdezesek_kerese($kulcs, $szerkezet, $feladatok, $elvartSzoveg);

    $ki = [];
    foreach ($megoldasok as $m) {
        $cim = $m['feladat'] ?? '?';
        $sql = sql_tisztit($m['sql'] ?? '');
        logol("Futtatas: $cim");
        $ki[] = str_repeat('=', 60);
        $ki[] = $cim;
        $ki[] = str_repeat('=', 60);
        $ki[] = $sql;
        $ki[] = '';
        $ki[] = 'Magyarazat: ' . ($m['magyarazat'] ?? '');
        $ki[] = '';

        if ($csakSelect && !preg_match('/^\s*(SELECT|SHOW|WITH|DESCRIBE)\b/i', $sql)) {
            $ki[] = '[Nem futtattam le: nem SELECT jellegu lekerdezes.]';
            $ki[] = '';
            continue;
        }

        $elvart = $elvartAdat[feladat_kulcs($cim)] ?? null;
        for ($kiserlet = 0; $kiserlet <= $MAX_JAVITAS; $kiserlet++) {
            $hiba = null;
            $eredm = null;
            try {
                $eredm = sql_futtat($db, $sql);
                if ($eredm['van'] && $elvart) {
                    $elt = elteres($eredm['oszlopok'], $eredm['sorok'], $elvart);
                    if ($elt !== '') $hiba = "A lekerdezes lefutott, de az eredmeny elter az elvarttol:\n$elt";
                }
            } catch (Exception $e) {
                $hiba = $e->getMessage();
                $eredm = null;
            }

            if ($hiba && $kiserlet < $MAX_JAVITAS) {
                logol('Hiba/elteres, javitast kerek (' . ($kiserlet + 1) . "/$MAX_JAVITAS): " . strtok($hiba, "\n"));
                try {
                    $sql = javitas_kerese($kulcs, $szerkezet, $cim, $sql, $hiba, $elvart ? $elvart['nyers'] : '');
                } catch (Exception $e) {
                    $ki[] = 'HIBA a javitas kerese kozben: ' . $e->getMessage();
                    break;
                }
                $ki[] = '[Javitott lekerdezes ' . ($kiserlet + 1) . '. proba:]';
                $ki[] = $sql;
                continue;
            }

            if ($eredm === null) {
                $ki[] = $hiba ? "HIBA: $hiba" : '[Lefutott.]';
            } elseif (!$eredm['van']) {
                $ki[] = '[Lefutott, de nincs eredmenysor.]';
            } else {
                $db_sor = count($eredm['sorok']);
                $ki[] = "Eredmeny ($db_sor sor):";
                $ki[] = implode(' | ', $eredm['oszlopok']);
                foreach (array_slice($eredm['sorok'], 0, $MAX_SOR) as $sor) $ki[] = implode(' | ', $sor);
                if ($db_sor > $MAX_SOR) $ki[] = '... (tovabbi ' . ($db_sor - $MAX_SOR) . ' sor)';
                if ($hiba) $ki[] = "FIGYELEM: $hiba";
                elseif ($elvart) $ki[] = 'Az eredmeny egyezik az elvart kimenettel.';
            }
            break;
        }
        $ki[] = '';
    }
    return implode("\n", $ki);
}

// ---------- kérés kezelése ----------
$HIBA = '';
$EREDMENY = '';
$DB_LISTA = [];
try { $DB_LISTA = adatbazisok(); } catch (Exception $e) { $HIBA = $e->getMessage(); }

$p_kulcs = trim($_POST['kulcs'] ?? '');
$p_db = $_POST['adatbazis'] ?? '';
$p_feladat = $_POST['feladatok'] ?? '';
$p_elvart = $_POST['elvart'] ?? '';
$p_csak = !isset($_POST['kuldve']) || isset($_POST['csak_select']);
$SSL_KI = isset($_POST['ssl_ki']);

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    try {
        if ($p_kulcs === '') throw new Exception('Add meg a Groq API kulcsot.');
        if ($p_db === '') throw new Exception('Valassz adatbazist.');
        if (trim($p_feladat) === '') throw new Exception('Illeszd be a feladatok szoveget.');
        $EREDMENY = feldolgoz($p_kulcs, $p_db, $p_feladat, trim($p_elvart), $p_csak);
    } catch (Exception $e) {
        $HIBA = $e->getMessage();
    }
}
?>
<!DOCTYPE html>
<html lang="hu">
<head>
<meta charset="utf-8">
<title>SQL feladatmegoldo</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font-family: Arial, sans-serif; max-width: 900px; margin: 24px auto; padding: 0 16px; color: #222; }
  label { display: block; margin-top: 14px; font-weight: bold; }
  input[type=password], select, textarea { width: 100%; box-sizing: border-box; padding: 8px; font-size: 14px; }
  textarea { font-family: Consolas, monospace; }
  .opcio { font-weight: normal; margin-top: 8px; }
  button { margin-top: 18px; padding: 10px 18px; font-size: 15px; cursor: pointer; }
  .hiba { background: #fde8e8; border: 1px solid #e99; padding: 10px; margin-top: 14px; white-space: pre-wrap; }
  .naplo { background: #f1f1f1; padding: 10px; margin-top: 14px; font-size: 13px; white-space: pre-wrap; }
  pre { background: #fafafa; border: 1px solid #ddd; padding: 12px; overflow-x: auto; }
  small { color: #666; font-weight: normal; }
</style>
</head>
<body>
<h1>SQL feladatmegoldo</h1>

<?php if ($HIBA): ?><div class="hiba"><?= h($HIBA) ?></div><?php endif; ?>

<form method="post">
  <input type="hidden" name="kuldve" value="1">

  <label>Groq API kulcs <small>(csak erre a futtatasra hasznalja, nem menti el)</small></label>
  <input type="password" name="kulcs" value="<?= h($p_kulcs) ?>" autocomplete="off" placeholder="gsk_...">

  <label>Adatbázis</label>
  <select name="adatbazis">
    <option value="">-- válassz --</option>
    <?php foreach ($DB_LISTA as $d): ?>
      <option value="<?= h($d) ?>" <?= $d === $p_db ? 'selected' : '' ?>><?= h($d) ?></option>
    <?php endforeach; ?>
  </select>

  <label>Feladatok szövege</label>
  <textarea name="feladatok" rows="10" placeholder="Másold ide a feladatokat..."><?= h($p_feladat) ?></textarea>

  <label>Elvárt kimenetek <small>(opcionális, a mintaképek szövegesen; ha üres, kihagyja az ellenőrzést)</small></label>
  <textarea name="elvart" rows="7" placeholder="-- 1. feladat&#10;foglalas_id | vendeg_neve | kedvezmenyes_szallasi_dij&#10;1 | Kiss Dániel | 64800.0000"><?= h($p_elvart) ?></textarea>

  <label class="opcio"><input type="checkbox" name="csak_select" <?= $p_csak ? 'checked' : '' ?>> Csak SELECT jellegű lekérdezéseket futtasson (ajánlott)</label>
  <label class="opcio"><input type="checkbox" name="ssl_ki" <?= $SSL_KI ? 'checked' : '' ?>> Tanúsítvány-ellenőrzés kikapcsolása <small>(csak ha SSL hibát ír; kevésbé biztonságos)</small></label>

  <button type="submit">Megoldások generálása</button>
  <small>&nbsp;Eltarthat egy-két percig, ne zárd be az oldalt.</small>
</form>

<?php if ($NAPLO): ?><div class="naplo"><?= h(implode("\n", $NAPLO)) ?></div><?php endif; ?>

<?php if ($EREDMENY !== ''): ?>
  <h2>Eredmény</h2>
  <button type="button" onclick="letoltes()">Letöltés (megoldasok.txt)</button>
  <button type="button" onclick="masolas()">Másolás</button>
  <pre id="eredmeny"><?= h($EREDMENY) ?></pre>
  <script>
    function szoveg() { return document.getElementById('eredmeny').textContent; }
    function letoltes() {
      var b = new Blob(["\uFEFF" + szoveg()], {type: 'text/plain;charset=utf-8'});
      var a = document.createElement('a');
      a.href = URL.createObjectURL(b); a.download = 'megoldasok.txt';
      document.body.appendChild(a); a.click(); a.remove();
    }
    function masolas() { navigator.clipboard.writeText(szoveg()); }
  </script>
<?php endif; ?>
</body>
</html>
