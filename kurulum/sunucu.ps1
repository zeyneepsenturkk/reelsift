<#
  ReelSift kurulum sayfasinin yerel sunucusu (System.Net.HttpListener, yalnizca localhost).
  Yonetici hakki istemez. Python / Node gerekmez.

    powershell -NoProfile -ExecutionPolicy Bypass -File kurulum\sunucu.ps1

  Uclar: GET /  sayfa | GET /durum  durum JSON'u | POST /basla  kurulumu baslatir |
         POST /anahtar  dil modeli secimi (gemini | anthropic | ollama) | POST /tekrar  hatali adimdan surdurur | GET /medya/<ad>  video |
         GET /anlatim/<yol> (repoda sunum\zeynep\) ve GET /ortak/<yol> (sunum\ortak\)
  Durdurmak icin: kurulum\.durum\sunucu-dur dosyasini olusturmak ya da sureci sonlandirmak.
  Deneme parametreleri (-Deneme, -HataAdimi ...) kur.ps1'e aynen iletilir (yalniz sayfa denemesi icin).
#>
param(
    [int]$Port = 5174,
    [switch]$TarayiciAcma,
    [switch]$Deneme,
    [int]$HataAdimi = 0,
    [int]$KullaniciAdimi = 0,
    [double]$DenemeHiz = 1,
    [string]$DenemeDur = ''
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

. (Join-Path $PSScriptRoot 'adimlar\ortak.ps1')
Initialize-Ortam $PSScriptRoot -Deneme:$Deneme

$sayfaYolu = Join-Path $PSScriptRoot 'sayfa\index.html'
$kurPid = Join-Path $script:DurumDir 'kur.pid'
$sunucuPid = Join-Path $script:DurumDir 'sunucu.pid'
$durmaDosyasi = Join-Path $script:DurumDir 'sunucu-dur'
$denemeAnahtar = Join-Path $script:DurumDir 'deneme-anahtar'
$izinliHost = @(('localhost:' + $Port), ('127.0.0.1:' + $Port))
$izinliOrigin = @(('http://localhost:' + $Port), ('http://127.0.0.1:' + $Port))
$script:SonBaslatma = [datetime]::MinValue
if (Test-Path $durmaDosyasi) { Remove-Item -Force $durmaDosyasi }

$tipler = @{
    '.html' = 'text/html; charset=utf-8'; '.mp4' = 'video/mp4'; '.webm' = 'video/webm'
    '.json' = 'application/json; charset=utf-8'; '.svg' = 'image/svg+xml'; '.png' = 'image/png'
    '.css' = 'text/css; charset=utf-8'; '.js' = 'text/javascript; charset=utf-8'; '.woff2' = 'font/woff2'
    '.jpg' = 'image/jpeg'; '.jpeg' = 'image/jpeg'
}
$sunumZeynep = [System.IO.Path]::GetFullPath((Join-Path $script:Kok 'sunum\zeynep'))
$sunumOrtak = [System.IO.Path]::GetFullPath((Join-Path $script:Kok 'sunum\ortak'))

# Repodan sunulan dosyanin tam yolunu dondurur; yol kok klasorun disina cikiyorsa ya da dosya yoksa $null.
function Resolve-SunumDosya([string]$Kok, [string]$Goreli) {
    try { $g = [Uri]::UnescapeDataString($Goreli) } catch { return $null }
    if (-not $g -or $g -match '[\\:\x00-\x1f*?"<>|]' -or $g.StartsWith('/', [System.StringComparison]::Ordinal)) { return $null }
    foreach ($parca in $g.Split('/')) { if (-not $parca -or $parca -eq '.' -or $parca -eq '..' -or $parca.StartsWith('.', [System.StringComparison]::Ordinal)) { return $null } }
    $tam = [System.IO.Path]::GetFullPath((Join-Path $Kok ($g -replace '/', '\')))
    if (-not $tam.StartsWith($Kok + '\', [System.StringComparison]::OrdinalIgnoreCase)) { return $null }
    if (-not (Test-Path -LiteralPath $tam -PathType Leaf)) { return $null }
    return $tam
}

function Send-Bytes($Ctx, [int]$Kod, [string]$Tip, [byte[]]$Bytes) {
    $r = $Ctx.Response
    $r.StatusCode = $Kod
    $r.ContentType = $Tip
    $r.ContentLength64 = $Bytes.Length
    $r.AddHeader('Cache-Control', 'no-store')
    $r.AddHeader('X-Content-Type-Options', 'nosniff')
    $r.OutputStream.Write($Bytes, 0, $Bytes.Length)
    $r.OutputStream.Close()
}

function Send-Json($Ctx, [int]$Kod, $Nesne) {
    $json = ConvertTo-Json -InputObject $Nesne -Depth 8 -Compress
    Send-Bytes $Ctx $Kod 'application/json; charset=utf-8' ($script:Utf8.GetBytes($json))
}

function Send-Dosya($Ctx, [string]$Yol, [string]$Tip) {
    $r = $Ctx.Response
    $uzunluk = (Get-Item $Yol).Length
    $bas = [int64]0
    $son = $uzunluk - 1
    $kod = 200
    $aralik = $Ctx.Request.Headers['Range']
    if ($aralik -and $aralik -match '^bytes=(\d*)-(\d*)$') {
        if ($Matches[1] -ne '') { $bas = [int64]$Matches[1] }
        if ($Matches[2] -ne '') { $son = [int64]$Matches[2] }
        if ($Matches[1] -eq '' -and $Matches[2] -ne '') { $bas = $uzunluk - [int64]$Matches[2]; $son = $uzunluk - 1 }
        if ($son -ge $uzunluk) { $son = $uzunluk - 1 }
        if ($bas -gt $son -or $bas -lt 0) {
            $r.StatusCode = 416
            $r.AddHeader('Content-Range', ('bytes */' + $uzunluk))
            $r.OutputStream.Close()
            return
        }
        $kod = 206
        $r.AddHeader('Content-Range', ('bytes ' + $bas + '-' + $son + '/' + $uzunluk))
    }
    $r.StatusCode = $kod
    $r.ContentType = $Tip
    $r.AddHeader('Accept-Ranges', 'bytes')
    $r.ContentLength64 = ($son - $bas + 1)
    $fs = New-Object System.IO.FileStream($Yol, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        $null = $fs.Seek($bas, [System.IO.SeekOrigin]::Begin)
        $buf = New-Object byte[] 65536
        $kalan = $son - $bas + 1
        while ($kalan -gt 0) {
            $n = $fs.Read($buf, 0, [int][math]::Min($buf.Length, $kalan))
            if ($n -le 0) { break }
            $r.OutputStream.Write($buf, 0, $n)
            $kalan -= $n
        }
    } catch {
        # tarayici baglantiyi kapatti (video ileri sarma); sorun degil
    } finally {
        $fs.Dispose()
        try { $r.OutputStream.Close() } catch {}
    }
}

function Test-KurCalisiyor { return (Test-KurKilidiTutuluyor) }

# Donus: $true baslatildi; $false zaten suruyor (kilit tutuluyor ya da son baslatma 20 sn'den yeni).
# 20 sn kurali baslatma yarisini onler: yeni baslatilan kur.ps1 henuz kilidi / durumu yazmadiysa ikincisi acilmaz.
# Kur durum dosyasini baslatmadan SONRA guncellediyse (calisti ve bitti / takildi) yeniden deneme engellenmez.
function Start-Kur {
    if (((Get-Date) - $script:SonBaslatma).TotalSeconds -lt 20) {
        $d = Read-JsonDosya $script:DurumDosyasi
        $baslamis = $false
        if ($d -and $d.guncelleme) {
            try { $baslamis = ([datetimeoffset]::Parse([string]$d.guncelleme, [System.Globalization.CultureInfo]::InvariantCulture).UtcDateTime -gt $script:SonBaslatma.ToUniversalTime().AddSeconds(1)) } catch {}
        }
        if (-not $baslamis) { return $false }
    }
    if (Test-KurCalisiyor) { return $false }
    $liste = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'kur.ps1'))
    if ($Deneme) {
        $liste += '-Deneme'
        if ($HataAdimi -gt 0) { $liste += @('-HataAdimi', [string]$HataAdimi) }
        if ($KullaniciAdimi -gt 0) { $liste += @('-KullaniciAdimi', [string]$KullaniciAdimi) }
        if ($DenemeHiz -ne 1) { $liste += @('-DenemeHiz', ([string]$DenemeHiz)) }
        if ($DenemeDur) { $liste += @('-DenemeDur', $DenemeDur) }
    }
    $null = Start-Process -FilePath 'powershell.exe' -ArgumentList (ConvertTo-ArgString $liste) -WorkingDirectory $script:Kok -WindowStyle Hidden
    $script:SonBaslatma = Get-Date
    Write-Log 'Kurulum sureci baslatildi.'
    return $true
}

function Get-DurumCevabi {
    $d = Read-JsonDosya $script:DurumDosyasi
    $beklenenKip = 'gercek'
    if ($Deneme) { $beklenenKip = 'deneme' }
    # Durum dosyasi bu sunucunun kipiyle uyusmuyorsa durum "hazir" sayilir.
    if (-not $d -or $d.kip -ne $beklenenKip) { $d = New-Durum; $d.kip = $beklenenKip }
    $calisiyor = Test-KurCalisiyor
    $yeniBaslatildi = (((Get-Date) - $script:SonBaslatma).TotalSeconds -lt 10)
    $kesinti = $false
    if ($d.genel -eq 'suruyor' -and -not $calisiyor -and -not $yeniBaslatildi) { $kesinti = $true }
    $video = Test-Path (Join-Path $script:MedyaDir $script:Sabit.video_dosya)
    $anlatim = Test-Path (Join-Path $script:MedyaDir $script:Sabit.anlatim_dosya)
    $videoYolu = $null; $kapakYolu = $null; $anlatimYolu = $null
    if (Test-RepoVideo) { $videoYolu = '/anlatim/zeynep-icin.mp4' }
    if (Test-RepoKapak) { $kapakYolu = '/anlatim/kapak.jpg' }
    if (Test-RepoAnlatim) { $anlatimYolu = '/anlatim/index.html' }
    $d | Add-Member -NotePropertyName video_yolu -NotePropertyValue $videoYolu -Force
    $d | Add-Member -NotePropertyName kapak_yolu -NotePropertyValue $kapakYolu -Force
    $d | Add-Member -NotePropertyName anlatim_yolu -NotePropertyValue $anlatimYolu -Force
    $medya = [pscustomobject]@{ video = $video; video_adres = ('/medya/' + $script:Sabit.video_dosya); anlatim = $anlatim; anlatim_adres = ('/medya/' + $script:Sabit.anlatim_dosya) }
    $d | Add-Member -NotePropertyName medya -NotePropertyValue $medya -Force
    $d | Add-Member -NotePropertyName kesinti -NotePropertyValue $kesinti -Force
    $d | Add-Member -NotePropertyName surec_calisiyor -NotePropertyValue $calisiyor -Force
    $d | Add-Member -NotePropertyName deneme -NotePropertyValue ([bool]$Deneme) -Force
    # Sifre kurulum sirasinda uretilir; yalniz kurulum bittiginde ekrana verilir.
    $kimlik = [pscustomobject]@{ kullanici = [string]$script:Sabit.kimlik.kullanici; sifre = $null }
    if ($d.genel -eq 'tamam') {
        $hesap = Get-Hesap
        if ($hesap) { $kimlik = [pscustomobject]@{ kullanici = [string]$hesap.kullanici; sifre = [string]$hesap.sifre } }
    }
    $d | Add-Member -NotePropertyName kimlik -NotePropertyValue $kimlik -Force
    $d | Add-Member -NotePropertyName adresler -NotePropertyValue $script:Sabit.adresler -Force
    return $d
}

function Read-Govde($Ctx) {
    $sr = New-Object System.IO.StreamReader($Ctx.Request.InputStream, [System.Text.Encoding]::UTF8)
    $t = $sr.ReadToEnd()
    if ($t.Length -gt 4096) { return '' }
    return $t
}

function Invoke-Istek($Ctx) {
    $req = $Ctx.Request
    $yol = $req.Url.AbsolutePath
    $yontem = $req.HttpMethod

    # Yalniz bu bilgisayardan; Host basligi dogrulanir (DNS rebinding'e karsi).
    if (-not [System.Net.IPAddress]::IsLoopback($req.RemoteEndPoint.Address) -or ($izinliHost -notcontains $req.Headers['Host'])) {
        Send-Json $Ctx 403 @{ ok = $false; mesaj = 'Yalnızca bu bilgisayardan erişilebilir.' }
        return
    }
    if ($yontem -eq 'POST') {
        $origin = $req.Headers['Origin']
        if (-not $origin -or ($izinliOrigin -notcontains $origin)) {
            Send-Json $Ctx 403 @{ ok = $false; mesaj = 'İstek bu sayfadan gelmedi.' }
            return
        }
    }

    if ($yontem -eq 'GET' -and $yol -eq '/') {
        if (Test-Path $sayfaYolu) { Send-Bytes $Ctx 200 'text/html; charset=utf-8' ([System.IO.File]::ReadAllBytes($sayfaYolu)) }
        else { Send-Json $Ctx 404 @{ ok = $false; mesaj = 'Sayfa dosyası bulunamadı.' } }
        return
    }
    if ($yontem -eq 'GET' -and $yol -eq '/durum') {
        Send-Json $Ctx 200 (Get-DurumCevabi)
        return
    }
    if ($yontem -eq 'GET' -and $yol -cmatch '^/(anlatim|ortak)(/(.*))?$') {
        $kok = $sunumOrtak
        if ($Matches[1] -eq 'anlatim') { $kok = $sunumZeynep }
        $goreli = [string]$Matches[3]
        if ($Matches[1] -eq 'anlatim' -and ($goreli -eq '' -or $goreli -eq 'index.html')) { $goreli = 'index.html' }
        $dosya = Resolve-SunumDosya $kok $goreli
        $uzanti = ''
        if ($dosya) { $uzanti = [System.IO.Path]::GetExtension($dosya).ToLowerInvariant() }
        if (-not $dosya -or -not $tipler.ContainsKey($uzanti)) { Send-Json $Ctx 404 @{ ok = $false }; return }
        Send-Dosya $Ctx $dosya $tipler[$uzanti]
        return
    }
    if ($yontem -eq 'GET' -and $yol -cmatch '^/medya/([A-Za-z0-9._-]+)$') {
        $ad = $Matches[1]
        $dosya = Join-Path $script:MedyaDir $ad
        if ($ad.StartsWith('.', [System.StringComparison]::Ordinal) -or -not (Test-Path $dosya -PathType Leaf)) { Send-Json $Ctx 404 @{ ok = $false }; return }
        $uzanti = [System.IO.Path]::GetExtension($ad).ToLowerInvariant()
        $tip = 'application/octet-stream'
        if ($tipler.ContainsKey($uzanti)) { $tip = $tipler[$uzanti] }
        Send-Dosya $Ctx $dosya $tip
        return
    }
    if ($yontem -eq 'POST' -and ($yol -eq '/basla' -or $yol -eq '/tekrar')) {
        $d = Read-JsonDosya $script:DurumDosyasi
        $beklenenKip = 'gercek'
        if ($Deneme) { $beklenenKip = 'deneme' }
        if ($d -and $d.kip -eq $beklenenKip -and $d.genel -eq 'tamam') { Send-Json $Ctx 200 @{ ok = $true; basladi = $false; mesaj = 'Kurulum zaten bitti.' }; return }
        $basladi = Start-Kur
        if ($basladi) { Send-Json $Ctx 200 @{ ok = $true; basladi = $true; mesaj = 'Kurulum başlatıldı.' } }
        else { Send-Json $Ctx 200 @{ ok = $true; basladi = $false; mesaj = 'Kurulum zaten sürüyor.' } }
        return
    }
    if ($yontem -eq 'POST' -and $yol -eq '/anahtar') {
        $govde = Read-Govde $Ctx
        $anahtar = ''
        $saglayici = 'gemini'
        try {
            $j = $govde | ConvertFrom-Json
            $anahtar = [string]$j.anahtar
            if ($j.saglayici) { $saglayici = [string]$j.saglayici }
        } catch { $anahtar = $govde }
        $temiz = $anahtar.Trim().Trim('"').Trim("'").Trim()
        $d = Read-JsonDosya $script:DurumDosyasi
        $adim = $null
        if ($d) { $adim = $d.adimlar | Where-Object { $_.id -eq 'anahtar' } | Select-Object -First 1 }
        if (-not $adim -or $adim.durum -ne 'kullanici') {
            Send-Json $Ctx 409 @{ ok = $false; mesaj = 'Şu an dil modeli seçimi istemiyorum; sayfayı yenileyip bir bakalım.' }
            return
        }
        if ($saglayici -cne 'gemini' -and $saglayici -cne 'anthropic' -and $saglayici -cne 'ollama') {
            Send-Json $Ctx 400 @{ ok = $false; mesaj = 'Bilinmeyen seçenek.' }
            return
        }
        if ($Deneme) {
            if ($saglayici -cne 'ollama' -and ($temiz.Length -lt 8 -or $temiz -eq 'hatali')) {
                Send-Json $Ctx 200 @{ ok = $false; mesaj = "Anahtar kabul edilmedi; kopyalarken başında ya da sonunda boşluk kalmış olabilir." }
            } else {
                [System.IO.File]::WriteAllText($denemeAnahtar, '1', $script:Utf8)
                Send-Json $Ctx 200 @{ ok = $true; mesaj = 'Seçimin kaydedildi.' }
            }
            return
        }
        if (-not (Test-Path (Get-EnvYolu))) {
            Send-Json $Ctx 409 @{ ok = $false; mesaj = 'Ayar dosyası henüz hazır değil; birkaç saniye sonra tekrar dene.' }
            return
        }
        $isaret = Join-Path $script:DurumDir 'saglayici-secildi'
        $mesaj = ''
        $kabul = $false
        if ($saglayici -ceq 'ollama') {
            $o = $script:Sabit.ollama
            $od = Test-OllamaDurum $o.model
            if (-not $od.Calisiyor) {
                Write-Log 'Yerel model secildi ama Ollama calismiyor.'
                Send-Json $Ctx 200 @{ ok = $false; mesaj = $od.Mesaj; baglanti = 'https://ollama.com/download' }
                return
            }
            $yazildi = $true
            try {
                Set-EnvDeger 'LLM_PROVIDER' 'ollama'
                Set-EnvDeger 'OLLAMA_BASE_URL' ([string]$o.base_url)
                Set-EnvDeger 'OLLAMA_MODEL' ([string]$o.model)
                Set-EnvDeger 'OLLAMA_NUM_CTX' ([string]$o.num_ctx)
            } catch { $yazildi = $false }
            if ($yazildi) {
                $kabul = $true
                if ($od.ModelVar) { $mesaj = 'Ollama çalışıyor ve model bilgisayarında hazır.' } else { $mesaj = 'Ollama çalışıyor; modeli şimdi indireceğim, birkaç dakika sürebilir.' }
            }
        } elseif ($saglayici -ceq 'anthropic') {
            $t = Test-AnthropicAnahtar $temiz
            if (-not $t.Tamam) {
                Write-Log ('Claude anahtari kabul edilmedi: ' + $t.Neden)
                Send-Json $Ctx 200 @{ ok = $false; mesaj = $t.Mesaj }
                return
            }
            $yazildi = $true
            try { Set-EnvDeger 'LLM_PROVIDER' 'anthropic'; Set-EnvDeger 'ANTHROPIC_API_KEY' $temiz } catch { $yazildi = $false }
            if ($yazildi) { $kabul = $true; $mesaj = $t.Mesaj }
        } else {
            $t = Test-GeminiAnahtar $temiz
            if (-not $t.Tamam) {
                Write-Log ('Gemini anahtari kabul edilmedi: ' + $t.Neden)
                Send-Json $Ctx 200 @{ ok = $false; mesaj = $t.Mesaj }
                return
            }
            $yazildi = $true
            try { Set-EnvDeger 'LLM_PROVIDER' 'gemini'; Set-EnvDeger 'GEMINI_API_KEY' $temiz } catch { $yazildi = $false }
            if ($yazildi) { $kabul = $true; $mesaj = $t.Mesaj }
        }
        if ($kabul) {
            [System.IO.File]::WriteAllText($isaret, $saglayici, $script:Utf8)
            Write-Log ('Dil modeli secildi: ' + $saglayici + ' (anahtar degeri yazilmadi).')
            Send-Json $Ctx 200 @{ ok = $true; mesaj = $mesaj }
        } else {
            Write-Log 'Dil modeli ayarlari yazilamadi: ayar dosyasi okunamadi ya da yazilamadi (dosya degistirilmedi).'
            Send-Json $Ctx 503 @{ ok = $false; mesaj = 'Ayar dosyasına şu an yazılamadı; birkaç saniye sonra tekrar dene.' }
        }
        return
    }
    Send-Json $Ctx 404 @{ ok = $false; mesaj = 'Böyle bir adres yok.' }
}

# --- Dinleyici -------------------------------------------------------------------------------
$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add(('http://localhost:' + $Port + '/'))
$listener.Prefixes.Add(('http://127.0.0.1:' + $Port + '/'))
try {
    $listener.Start()
} catch {
    Write-Output ('Port ' + $Port + ' acilamadi (baska bir kurulum penceresi acik olabilir): ' + $_.Exception.Message)
    if (-not $TarayiciAcma) { Start-Process ('http://localhost:' + $Port + '/') }
    exit 2
}
[System.IO.File]::WriteAllText($sunucuPid, [string]$PID, $script:Utf8)
Write-Log ('Sunucu basladi: http://localhost:' + $Port + '/')
Write-Output ('Kurulum sayfasi: http://localhost:' + $Port + '/  (durdurmak icin bu pencereyi kapat)')
if (-not $TarayiciAcma) { Start-Process ('http://localhost:' + $Port + '/') }

try {
    while ($listener.IsListening) {
        $ar = $listener.BeginGetContext($null, $null)
        while (-not $ar.AsyncWaitHandle.WaitOne(500)) {
            if (Test-Path $durmaDosyasi) { break }
        }
        if (Test-Path $durmaDosyasi) { break }
        $ctx = $listener.EndGetContext($ar)
        try { Invoke-Istek $ctx }
        catch {
            Write-Log ('Sunucu istek hatasi: ' + $_.Exception.Message)
            try { Send-Json $ctx 500 @{ ok = $false; mesaj = 'Sunucuda beklenmedik bir sorun çıktı.' } } catch {}
        }
    }
} finally {
    try { $listener.Stop(); $listener.Close() } catch {}
    if (Test-Path $sunucuPid) { Remove-Item -Force $sunucuPid -ErrorAction SilentlyContinue }
    Write-Log 'Sunucu durdu.'
}
