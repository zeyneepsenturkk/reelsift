# Ortak yardimcilar: kur.ps1 ve sunucu.ps1 tarafindan nokta-kaynak (dot-source) ile yuklenir.
# Windows PowerShell 5.1 uyumlu: && || ?? ve uclu isleç YOK. Python / Node gerekmez.
# Gizli bilgi kurali: GitHub kimligi ve Gemini anahtari yalniz bellekte tutulur; log / durum / komut
# satiri argumanina yazilmaz (curl'e `-K -` ile stdin'den verilir).

$script:Utf8 = New-Object System.Text.UTF8Encoding $false

function Initialize-Ortam {
    param([string]$KurulumKlasoru, [switch]$Deneme)
    $script:KurulumDir = $KurulumKlasoru
    $script:Kok = Split-Path -Parent $KurulumKlasoru
    # Deneme kipi gercek kuruluma karismasin diye kendi durum klasorunu kullanir.
    $durumAdi = '.durum'
    if ($Deneme) { $durumAdi = '.durum-deneme' }
    $script:DurumDir = Join-Path $KurulumKlasoru $durumAdi
    $script:MedyaDir = Join-Path $script:DurumDir 'medya'
    $script:IndirmeDir = Join-Path $script:DurumDir 'indirme'
    $script:DurumDosyasi = Join-Path $script:DurumDir 'durum.json'
    $script:LogDosyasi = Join-Path $script:DurumDir 'kurulum.log'
    foreach ($d in @($script:DurumDir, $script:MedyaDir, $script:IndirmeDir)) {
        if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
    }
    $script:Sabit = Read-JsonDosya (Join-Path $KurulumKlasoru 'sabitler.json')
    $script:GecerliLog = $null
    # Surec stdin'ine BOM yazilmasin (konsol kod sayfasi UTF-8 ise .NET BOM ekler; git / curl girdisini bozar).
    try { [Console]::InputEncoding = New-Object System.Text.UTF8Encoding $false } catch {}
}

# Kultur: bu dosyadaki dizge islemleri Turkce (tr-TR) Windows'ta da ayni sonucu verir (i / I tuzagi); karsilastirmalar
# -cmatch / Ordinal / Invariant ile yapilir. Tarih biçimi de kulturden bagimsizdir.
function Get-Now { return (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz', [System.Globalization.CultureInfo]::InvariantCulture) }

# --- Dosya okuma / yazma ---------------------------------------------------------------------

function Read-MetinDosya([string]$Yol) {
    for ($i = 0; $i -lt 8; $i++) {
        try {
            $fs = New-Object System.IO.FileStream($Yol, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, ([System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete))
            try {
                $sr = New-Object System.IO.StreamReader($fs, $script:Utf8, $true)
                return $sr.ReadToEnd()
            } finally { $fs.Dispose() }
        } catch { Start-Sleep -Milliseconds 80 }
    }
    return $null
}

# Yazan taraf dosyayi atomik degistirirken (File.Replace) okuyan bir anlik "dosya yok / okunamadi" gorebilir
# (olculdu: sik yazimda ~%10). Bu yuzden bos / eksik okuma birkac kez yeniden denenir; yoksa durum "hazir"a sicrar.
function Read-JsonDosya([string]$Yol) {
    for ($i = 0; $i -lt 6; $i++) {
        if (Test-Path $Yol) {
            $t = Read-MetinDosya $Yol
            if ($t) {
                try { return ($t | ConvertFrom-Json) } catch {}
            }
        }
        Start-Sleep -Milliseconds 40
    }
    return $null
}

# Zorunlu: degistirme basarisiz kalirsa (durum dosyasi gibi vazgecilebilir olmayan yazimlar icin) hata firlatir.
function Write-MetinAtomik([string]$Yol, [string]$Metin, [switch]$Zorunlu) {
    $tmp = $Yol + '.tmp'
    [System.IO.File]::WriteAllText($tmp, $Metin, $script:Utf8)
    for ($i = 0; $i -lt 15; $i++) {
        try {
            if (Test-Path $Yol) { [System.IO.File]::Replace($tmp, $Yol, [NullString]::Value) } else { [System.IO.File]::Move($tmp, $Yol) }
            return
        } catch { Start-Sleep -Milliseconds 100 }
    }
    if ($Zorunlu) {
        if (Test-Path $tmp) { Remove-Item -Force $tmp -ErrorAction SilentlyContinue }
        throw ('Dosya yazilamadi: ' + (Split-Path -Leaf $Yol))
    }
}

function Get-DosyaSonSatirlar([string]$Yol, [int]$Adet = 20) {
    if (-not $Yol -or -not (Test-Path $Yol)) { return @() }
    try {
        $fs = New-Object System.IO.FileStream($Yol, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, ([System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete))
        try {
            $oku = [Math]::Min($fs.Length, 32768)
            $null = $fs.Seek(-$oku, [System.IO.SeekOrigin]::End)
            $buf = New-Object byte[] $oku
            $n = $fs.Read($buf, 0, $oku)
            $metin = $script:Utf8.GetString($buf, 0, $n)
        } finally { $fs.Dispose() }
        $satirlar = @($metin -split "`r?`n|`r" | Where-Object { $_ -ne '' })
        if ($satirlar.Count -gt $Adet) { $satirlar = $satirlar[($satirlar.Count - $Adet)..($satirlar.Count - 1)] }
        return $satirlar
    } catch { return @() }
}

function Write-Log([string]$Mesaj) {
    $satir = '[' + (Get-Date).ToString('HH:mm:ss', [System.Globalization.CultureInfo]::InvariantCulture) + '] ' + $Mesaj
    for ($i = 0; $i -lt 5; $i++) {
        try { [System.IO.File]::AppendAllText($script:LogDosyasi, $satir + "`r`n", $script:Utf8); return } catch { Start-Sleep -Milliseconds 50 }
    }
}

# --- Durum dosyasi ---------------------------------------------------------------------------

function New-Durum {
    $adimlar = @()
    foreach ($a in $script:Sabit.adimlar) {
        $adimlar += [pscustomobject][ordered]@{
            id = $a.id; ad = $a.ad; aciklama = $a.aciklama
            durum = 'bekliyor'; yuzde = $null; bayt = $null; toplam = $null; kalan_sn = $null
            baslangic = $null; bitis = $null; mesaj = ''; ne_oldu = ''; ne_yapmali = ''
            baglanti = $null; gunluk = @()
        }
    }
    return [pscustomobject][ordered]@{
        surum = 1; kip = 'gercek'; genel = 'hazir'; baslangic = $null; bitis = $null
        guncelleme = (Get-Now); tahmini_toplam = $script:Sabit.tahmini_toplam; aktif = $null
        adimlar = $adimlar
    }
}

function Get-GenelDurum($Durum) {
    $d = @($Durum.adimlar | ForEach-Object { $_.durum })
    if ($d -contains 'hata') { return 'hata' }
    if ($d -contains 'kullanici') { return 'kullanici' }
    $bitmis = @($d | Where-Object { $_ -eq 'tamam' -or $_ -eq 'atlandi' })
    if ($bitmis.Count -eq $d.Count) { return 'tamam' }
    if ($d -contains 'suruyor' -or $bitmis.Count -gt 0) { return 'suruyor' }
    return 'hazir'
}

function Save-Durum {
    $d = $script:Durum
    $d.genel = Get-GenelDurum $d
    $d.guncelleme = Get-Now
    $json = ConvertTo-Json -InputObject $d -Depth 8
    Write-MetinAtomik $script:DurumDosyasi $json
}

function Get-Adim([string]$Id) {
    return ($script:Durum.adimlar | Where-Object { $_.id -eq $Id } | Select-Object -First 1)
}

function Set-Adim {
    param([string]$Id, [hashtable]$Alan, [switch]$GunlukGuncelle)
    $s = Get-Adim $Id
    foreach ($k in $Alan.Keys) { $s.$k = $Alan[$k] }
    if ($GunlukGuncelle) {
        $kaynak = $script:LogDosyasi
        if ($script:GecerliLog) { $kaynak = $script:GecerliLog }
        $s.gunluk = @(Get-DosyaSonSatirlar $kaynak 20)
    }
    Save-Durum
}

# --- Biçim yardimcilari ----------------------------------------------------------------------

function Format-Boyut([double]$Bayt) {
    $ci = [System.Globalization.CultureInfo]::InvariantCulture
    if ($Bayt -ge 1GB) { return ([math]::Round($Bayt / 1GB, 2)).ToString($ci) + ' GB' }
    if ($Bayt -ge 1MB) { return ([math]::Round($Bayt / 1MB, 1)).ToString($ci) + ' MB' }
    return ([math]::Round($Bayt / 1KB, 0)).ToString($ci) + ' KB'
}

# Surec baslatirken kullanilan arguman birlestirme (bosluk / tirnak kacisi).
function ConvertTo-ArgString([string[]]$Liste) {
    $sonuc = @()
    foreach ($a in $Liste) {
        if ($a -eq '') { $sonuc += '""'; continue }
        if ($a -notmatch '[\s"]') { $sonuc += $a; continue }
        $k = $a -replace '(\\*)"', '$1$1\"'
        $k = $k -replace '(\\+)$', '$1$1'
        $sonuc += ('"' + $k + '"')
    }
    return ($sonuc -join ' ')
}

# Surecin stdin'ine BOM'suz UTF-8 yazar (StandardInput.Write konsol kod sayfasina gore BOM ekleyebilir;
# bu `git credential fill` ve `curl -K -` girdisini bozar).
function Write-Stdin($Surec, [string]$Metin) {
    $bytes = $script:Utf8.GetBytes($Metin)
    $Surec.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
    $Surec.StandardInput.BaseStream.Flush()
}

# --- curl ------------------------------------------------------------------------------------
# Yapilandirma metni (gizli basliklar) curl'e `-K -` ile STDIN'den verilir; komut satirinda gorunmez.

function Invoke-Curl {
    param(
        [string[]]$Argumanlar,
        [string]$Yapilandirma = '',
        [scriptblock]$Tik = $null,
        [int]$TikMs = 2000,
        [int]$ZamanAsimiSn = 0
    )
    $liste = @('-sS')
    if ($Yapilandirma) { $liste += @('-K', '-') }
    $liste += $Argumanlar
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'curl.exe'
    $psi.Arguments = ConvertTo-ArgString $liste
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $p = [System.Diagnostics.Process]::Start($psi)
    $outTask = $p.StandardOutput.ReadToEndAsync()
    $errTask = $p.StandardError.ReadToEndAsync()
    if ($Yapilandirma) { Write-Stdin $p $Yapilandirma }
    $p.StandardInput.Close()
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while (-not $p.WaitForExit($TikMs)) {
        if ($Tik) { & $Tik }
        if ($ZamanAsimiSn -gt 0 -and $sw.Elapsed.TotalSeconds -gt $ZamanAsimiSn) { try { $p.Kill() } catch {}; break }
    }
    $p.WaitForExit()
    return [pscustomobject]@{ Kod = $p.ExitCode; Cikti = $outTask.Result; Hata = $errTask.Result }
}

# Cikti: govde + son satirda HTTP kodu (-w ile).
function Split-HttpCevap($Sonuc) {
    $metin = [string]$Sonuc.Cikti
    $i = $metin.LastIndexOf("`n", [System.StringComparison]::Ordinal)
    $kod = 0
    $govde = $metin
    if ($i -ge 0) {
        $son = $metin.Substring($i + 1).Trim()
        $govde = $metin.Substring(0, $i)
        [int]::TryParse($son, [ref]$kod) | Out-Null
    }
    return [pscustomobject]@{ Http = $kod; Govde = $govde; CurlKodu = $Sonuc.Kod; Hata = $Sonuc.Hata }
}

# --- GitHub ----------------------------------------------------------------------------------

# Saklanan GitHub kimligini `git credential fill` ile alir. Donen deger yalniz bellekte tutulur.
function Get-GitHubToken {
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = 'git'
        $psi.Arguments = 'credential fill'
        $psi.UseShellExecute = $false
        $psi.RedirectStandardInput = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.CreateNoWindow = $true
        $psi.EnvironmentVariables['GIT_TERMINAL_PROMPT'] = '0'
        $psi.EnvironmentVariables['GCM_INTERACTIVE'] = 'never'
        $p = [System.Diagnostics.Process]::Start($psi)
        $outTask = $p.StandardOutput.ReadToEndAsync()
        $errTask = $p.StandardError.ReadToEndAsync()
        Write-Stdin $p "protocol=https`nhost=github.com`n`n"
        $p.StandardInput.Close()
        if (-not $p.WaitForExit(30000)) { try { $p.Kill() } catch {}; return $null }
        $p.WaitForExit()
        if ($p.ExitCode -ne 0) { return $null }
        foreach ($satir in ($outTask.Result -split "`n")) {
            if ($satir.StartsWith('password=', [System.StringComparison]::Ordinal)) {
                $v = $satir.Substring(9).Trim()
                if ($v) { return $v }
            }
        }
    } catch {}
    return $null
}

function Get-GitHubYapilandirma([string]$Token) {
    if (-not $Token) { return '' }
    return ('header = "Authorization: token ' + $Token + '"' + "`n")
}

# Release'in JSON'unu getirir: @{ Http; Release } (Release: ConvertFrom-Json nesnesi ya da $null).
# Token bos olabilir: herkese acik repoda kimliksiz sorgulanir.
function Get-ReleaseBilgi([string]$Token = '') {
    $url = 'https://api.github.com/repos/' + $script:Sabit.repo + '/releases/tags/' + $script:Sabit.etiket
    $r = Invoke-Curl -Argumanlar @('-m', '40', '-H', 'Accept: application/vnd.github+json', '-H', 'X-GitHub-Api-Version: 2022-11-28', '-w', "`n%{http_code}", $url) -Yapilandirma (Get-GitHubYapilandirma $Token)
    $c = Split-HttpCevap $r
    $rel = $null
    if ($c.Http -eq 200) { try { $rel = $c.Govde | ConvertFrom-Json } catch {} }
    return [pscustomobject]@{ Http = $c.Http; Release = $rel; CurlKodu = $c.CurlKodu }
}

# Release dosyasini kaldigi yerden indirir (curl -C -). Tik: ilerleme icin her 2 sn cagrilir ($mevcut bayt).
function Save-ReleaseDosya {
    param([string]$Token = '', $Asset, [string]$Hedef, [scriptblock]$Tik)
    $toplam = [int64]$Asset.size
    if ((Test-Path $Hedef) -and ((Get-Item $Hedef).Length -eq $toplam)) { return $true }
    $part = $Hedef + '.part'
    if ((Test-Path $part) -and ((Get-Item $part).Length -eq $toplam)) {
        Move-Item -Force $part $Hedef
        return $true
    }
    $url = 'https://api.github.com/repos/' + $script:Sabit.repo + '/releases/assets/' + $Asset.id
    $ilerleme = $Tik
    $tikBlok = {
        if ($ilerleme -and (Test-Path $part)) { & $ilerleme ((Get-Item $part).Length) }
    }
    $r = Invoke-Curl -Argumanlar @('-L', '--fail', '-C', '-', '--retry', '5', '--retry-delay', '3', '--retry-connrefused', '-H', 'Accept: application/octet-stream', '-o', $part, $url) -Yapilandirma (Get-GitHubYapilandirma $Token) -Tik $tikBlok -TikMs 2000
    if ($r.Kod -ne 0) {
        Write-Log ('curl indirme kodu ' + $r.Kod + ': ' + ([string]$r.Hata).Trim())
        return $false
    }
    if ((Get-Item $part).Length -ne $toplam) {
        Write-Log 'Indirilen dosya boyutu beklenenle eslesmiyor.'
        return $false
    }
    Move-Item -Force $part $Hedef
    return $true
}

# Indirilen dosyanin SHA256 ozetini (ve istenirse boyutunu) denetler. Tutmazsa dosyayi siler ve BIR kez bastan indirir.
# Indir: dosyayi $Yol'a indiren scriptblock ($true / $false dondurur). Bildir: ozet hesabi basladiginda cagrilir.
# Donus: 'tamam' | 'indirme' (indirilemedi) | 'bozuk' (iki indirmede de ozet tutmadi).
function Confirm-DosyaOzeti {
    param([string]$Yol, [string]$Beklenen, [int64]$BeklenenBoyut = 0, [scriptblock]$Indir, [scriptblock]$Bildir = $null)
    $beklenen = ([string]$Beklenen).Trim().ToLowerInvariant()
    for ($deneme = 1; $deneme -le 2; $deneme++) {
        if (-not (Test-Path $Yol)) {
            if (-not (& $Indir)) { return 'indirme' }
        }
        if ($Bildir) { $null = & $Bildir }
        $boyutTamam = ($BeklenenBoyut -le 0) -or ((Get-Item $Yol).Length -eq $BeklenenBoyut)
        $ozet = ''
        if ($boyutTamam) { $ozet = (Get-FileHash -Algorithm SHA256 -LiteralPath $Yol).Hash.ToLowerInvariant() }
        if ($boyutTamam -and $ozet -eq $beklenen) { return 'tamam' }
        Write-Log ('Indirilen dosyanin ozeti tutmadi (deneme ' + $deneme + '/2): ' + (Split-Path -Leaf $Yol))
        Remove-Item -Force -LiteralPath $Yol -ErrorAction SilentlyContinue
        if (Test-Path ($Yol + '.part')) { Remove-Item -Force -LiteralPath ($Yol + '.part') -ErrorAction SilentlyContinue }
    }
    return 'bozuk'
}

# --- Repodan sunulan tanitim varliklari ------------------------------------------------------
# Repoda sunum\zeynep\ altinda (varsa) hazirsa video ve anlatim sayfasi Release'ten degil bu klasorden sunulur.
function Test-RepoVideo { return (Test-Path -LiteralPath (Join-Path $script:Kok 'sunum\zeynep\zeynep-icin.mp4') -PathType Leaf) }
function Test-RepoKapak { return (Test-Path -LiteralPath (Join-Path $script:Kok 'sunum\zeynep\kapak.jpg') -PathType Leaf) }
function Test-RepoAnlatim { return (Test-Path -LiteralPath (Join-Path $script:Kok 'sunum\zeynep\index.html') -PathType Leaf) }

# --- .env ------------------------------------------------------------------------------------

function Get-EnvYolu { return (Join-Path $script:Kok '.env') }

function Read-EnvSatirlari {
    $f = Get-EnvYolu
    if (-not (Test-Path $f)) { return @() }
    $t = Read-MetinDosya $f
    # Dosya var ama okunamadi: bos liste donmek yazan tarafta sifreleri kaybettirir; hata firlat.
    if ($null -eq $t) { throw 'Ayar dosyasi okunamadi.' }
    if (-not $t) { return @() }
    $l = @($t -split "`r?`n")
    if ($l.Count -gt 0 -and $l[$l.Count - 1] -eq '') { $l = @($l | Select-Object -First ($l.Count - 1)) }
    return $l
}

function Read-EnvDeger([string]$Ad) {
    foreach ($satir in (Read-EnvSatirlari)) {
        if ($satir -cmatch ('^' + [regex]::Escape($Ad) + '=(.*)$')) { return $Matches[1].Trim().Trim('"') }
    }
    return $null
}

# .env atomik yazilir (gecici dosya + yeniden adlandirma): yarim yazilmis ayar dosyasi kalmaz.
function Write-EnvSatirlari([string[]]$Satirlar) {
    Write-MetinAtomik (Get-EnvYolu) (($Satirlar -join "`n") + "`n") -Zorunlu
}

function Set-EnvDeger([string]$Ad, [string]$Deger) {
    $satirlar = @(Read-EnvSatirlari)
    $bulundu = $false
    for ($i = 0; $i -lt $satirlar.Count; $i++) {
        if ($satirlar[$i] -cmatch ('^' + [regex]::Escape($Ad) + '=')) { $satirlar[$i] = $Ad + '=' + $Deger; $bulundu = $true }
    }
    if (-not $bulundu) { $satirlar += ($Ad + '=' + $Deger) }
    Write-EnvSatirlari $satirlar
}

function New-Rastgele([int]$Uzunluk) {
    $alfabe = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    $rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
    $bytes = New-Object byte[] $Uzunluk
    $rng.GetBytes($bytes)
    $sb = New-Object System.Text.StringBuilder
    foreach ($b in $bytes) { [void]$sb.Append($alfabe[$b % $alfabe.Length]) }
    return $sb.ToString()
}

# --- Gemini anahtari -------------------------------------------------------------------------
# Bicim denetimi kulturden bagimsiz ve buyuk-kucuk harf DUYARLI (-cmatch): tr-TR'de 'I' -match '[A-Za-z]' False doner.
# Google'in yeni anahtarlari 'AQ.' ile baslar ve nokta icerir; eski 'AIza...' anahtarlar da gecerli.
function Test-AnahtarBicimi([string]$Anahtar) {
    return ([string]$Anahtar -cmatch '^[A-Za-z0-9_.\-]{20,200}$')
}

# Donus: @{ Tamam; Neden; Mesaj }. Neden: bicim | reddedildi | kota | ag | tamam
function Test-GeminiAnahtar([string]$Anahtar) {
    $Anahtar = ([string]$Anahtar).Trim().Trim('"').Trim("'").Trim()
    if (-not (Test-AnahtarBicimi $Anahtar)) {
        return [pscustomobject]@{ Tamam = $false; Neden = 'bicim'; Mesaj = "Anahtar kabul edilmedi; kopyalarken başında ya da sonunda boşluk kalmış, ya da eksik kopyalanmış olabilir." }
    }
    $cfg = 'header = "x-goog-api-key: ' + $Anahtar + '"' + "`n"
    $taban = 'https://generativelanguage.googleapis.com'
    if ($env:RS_GEMINI_TABAN) { $taban = $env:RS_GEMINI_TABAN }
    $r = Invoke-Curl -Argumanlar @('-m', '20', '-w', "`n%{http_code}", ($taban + '/v1beta/models?pageSize=1')) -Yapilandirma $cfg
    $c = Split-HttpCevap $r
    if ($c.Http -eq 200) { return [pscustomobject]@{ Tamam = $true; Neden = 'tamam'; Mesaj = 'Anahtar çalışıyor.' } }
    if ($c.Http -eq 429) { return [pscustomobject]@{ Tamam = $true; Neden = 'kota'; Mesaj = 'Anahtar çalışıyor (Google şu an istek sınırını hatırlattı, bu normal).' } }
    if ($c.Http -eq 400 -or $c.Http -eq 401 -or $c.Http -eq 403) {
        return [pscustomobject]@{ Tamam = $false; Neden = 'reddedildi'; Mesaj = "Anahtar kabul edilmedi; kopyalarken başında ya da sonunda boşluk kalmış olabilir. Google AI Studio'dan yeni bir anahtar da alabilirsin." }
    }
    return [pscustomobject]@{ Tamam = $false; Neden = 'ag'; Mesaj = "Google'a şu an ulaşamadım. İnternet bağlantını kontrol edip bir daha dene." }
}

# --- Claude (Anthropic) anahtari -------------------------------------------------------------
function Test-AnthropicBicimi([string]$Anahtar) {
    return ([string]$Anahtar -cmatch '^[A-Za-z0-9_.\-]{20,300}$')
}

# Donus: @{ Tamam; Neden; Mesaj }. Neden: bicim | reddedildi | ag | tamam
function Test-AnthropicAnahtar([string]$Anahtar) {
    $Anahtar = ([string]$Anahtar).Trim().Trim('"').Trim("'").Trim()
    if (-not (Test-AnthropicBicimi $Anahtar)) {
        return [pscustomobject]@{ Tamam = $false; Neden = 'bicim'; Mesaj = "Anahtar kabul edilmedi; içinde boşluk var ya da eksik kopyalanmış olabilir. Anahtarı baştan sona yeniden kopyalayıp yapıştır." }
    }
    $cfg = 'header = "x-api-key: ' + $Anahtar + '"' + "`n" + 'header = "anthropic-version: 2023-06-01"' + "`n"
    $taban = 'https://api.anthropic.com'
    if ($env:RS_ANTHROPIC_TABAN) { $taban = $env:RS_ANTHROPIC_TABAN }
    $r = Invoke-Curl -Argumanlar @('-m', '20', '-w', "`n%{http_code}", ($taban + '/v1/models?limit=1')) -Yapilandirma $cfg
    $c = Split-HttpCevap $r
    if ($c.Http -eq 200 -or $c.Http -eq 429) { return [pscustomobject]@{ Tamam = $true; Neden = 'tamam'; Mesaj = 'Anahtar çalışıyor.' } }
    if ($c.Http -eq 400 -or $c.Http -eq 401 -or $c.Http -eq 403) {
        return [pscustomobject]@{ Tamam = $false; Neden = 'reddedildi'; Mesaj = "Anahtar kabul edilmedi. Anthropic Console'dan (console.anthropic.com) yeni bir anahtar alabilirsin; hesapta bakiye olması gerekir." }
    }
    return [pscustomobject]@{ Tamam = $false; Neden = 'ag'; Mesaj = "Anthropic'e şu an ulaşamadım. İnternet bağlantını kontrol edip bir daha dene." }
}

# --- Yerel model (Ollama) --------------------------------------------------------------------
function Get-OllamaTaban {
    if ($env:RS_OLLAMA_TABAN) { return $env:RS_OLLAMA_TABAN }
    return 'http://localhost:11434'
}

# Donus: @{ Calisiyor; ModelVar; Mesaj }. Model adi tam eslesmeli (Ordinal).
function Test-OllamaDurum([string]$Model) {
    $r = Invoke-Curl -Argumanlar @('-m', '8', '-w', "`n%{http_code}", ((Get-OllamaTaban) + '/api/tags'))
    $c = Split-HttpCevap $r
    if ($c.Http -ne 200) {
        return [pscustomobject]@{ Calisiyor = $false; ModelVar = $false; Mesaj = "Ollama çalışmıyor ya da kurulu değil. Ollama'yı https://ollama.com/download adresinden indirip kur, aç (sağ altta simgesi görünür), sonra yeniden dene." }
    }
    $var = $false
    try {
        $j = $c.Govde | ConvertFrom-Json
        foreach ($m in @($j.models)) { if ([string]$m.name -ceq $Model) { $var = $true } }
    } catch {}
    return [pscustomobject]@{ Calisiyor = $true; ModelVar = $var; Mesaj = '' }
}

# Modeli Ollama'nin /api/pull ucundan indirir (akis dosyaya yazilir; Tik her 2 sn'de bayt bilgisiyle cagrilir).
# Donus: $true / $false.
function Save-OllamaModel {
    param([string]$Model, [string]$AkisDosyasi, [scriptblock]$Tik = $null)
    if (Test-Path $AkisDosyasi) { Remove-Item -Force $AkisDosyasi }
    $govde = '{"model":"' + $Model + '","stream":true}'
    # Invoke-Curl'un kendi $Tik parametresi var: ad cakismasin diye yerel kopya alinir.
    $ilerleme = $Tik
    $akis = $AkisDosyasi
    $tikBlok = {
        if ($ilerleme -and (Test-Path $akis)) {
            $s = @(Get-DosyaSonSatirlar $akis 3)
            if ($s.Count -gt 0) { & $ilerleme $s[$s.Count - 1] }
        }
    }
    $r = Invoke-Curl -Argumanlar @('-N', '-X', 'POST', '-H', 'Content-Type: application/json', '-d', $govde, '-o', $AkisDosyasi, ((Get-OllamaTaban) + '/api/pull')) -Tik $tikBlok -TikMs 2000
    if ($r.Kod -ne 0) { Write-Log ('ollama pull curl kodu ' + $r.Kod); return $false }
    $son = @(Get-DosyaSonSatirlar $AkisDosyasi 3)
    foreach ($s in $son) { if ($s -cmatch '"error"') { Write-Log ('ollama pull hatasi: ' + $s); return $false } }
    foreach ($s in $son) { if ($s -cmatch '"status"\s*:\s*"success"') { return $true } }
    return $false
}

# Kurulum sonu icin rastgele sifre (en az 12 karakter, harf+rakam, karisik gorunen karakter yok).
function New-Parola([int]$Uzunluk = 14) {
    $alfabe = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    $rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
    $bytes = New-Object byte[] 1
    $sb = New-Object System.Text.StringBuilder
    while ($sb.Length -lt $Uzunluk) {
        $rng.GetBytes($bytes)
        # Yanliliksiz dagilim: alfabe uzunlugunun tam kati altinda kalan degerler kabul edilir.
        if ($bytes[0] -lt (256 - (256 % $alfabe.Length))) { [void]$sb.Append($alfabe[$bytes[0] % $alfabe.Length]) }
    }
    return $sb.ToString()
}

# Kullanici hesabi bilgisi (kurulum sirasinda uretilir; yalniz bu klasorde, git disinda durur).
function Get-HesapYolu { return (Join-Path $script:DurumDir 'hesap.json') }
function Get-Hesap {
    $h = Read-JsonDosya (Get-HesapYolu)
    if ($h -and $h.kullanici -and $h.sifre) { return $h }
    return $null
}

# --- Süreç yardimcilari ----------------------------------------------------------------------

# Kurulum kilidi: kur.ps1 dosyayi FileShare.None ile acip surec bitene kadar tutar (surec olunce isletim sistemi birakir).
function Get-KurKilitYolu { return (Join-Path $script:DurumDir 'kur.lock') }

# Kilidi alir ve akisi dondurur; baska kopya tutuyorsa $null.
function Enter-KurKilidi {
    try {
        return (New-Object System.IO.FileStream((Get-KurKilitYolu), [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None))
    } catch { return $null }
}

# Kilit baska bir surecte tutuluyor mu? (Kilit bossa hemen birakir.)
# Kilidi alir; sunucunun /durum yoklamasi kilidi anlik acabildigi icin kisa aralikla yeniden dener (en cok 8 x 250 ms).
function Enter-KurKilidiBekle {
    for ($i = 0; $i -lt 8; $i++) {
        $akis = Enter-KurKilidi
        if ($akis) { return $akis }
        Start-Sleep -Milliseconds 250
    }
    return $null
}

function Test-KurKilidiTutuluyor {
    $akis = Enter-KurKilidi
    if ($akis) { $akis.Dispose(); return $false }
    return $true
}

function Test-SurecCalisiyor([string]$PidDosyasi) {
    if (-not (Test-Path $PidDosyasi)) { return $false }
    $t = (Read-MetinDosya $PidDosyasi)
    $id = 0
    if (-not $t -or -not [int]::TryParse($t.Trim(), [ref]$id)) { return $false }
    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName.StartsWith('powershell', [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
    return $false
}
