<#
  Veri paketini GitHub Release olarak yayinlar (repo zeyneepsenturkk/reelsift, etiket veri-2026-11-18).
  BU BETIK YAYIN YAPAR: yalniz depo sahibi calistirir. Kimlik `git credential fill` ile betigin icinde
  alinir; ekrana / loga / dosyaya yazilmaz, curl'e stdin'den (-K -) verilir. `gh` gerekmez.

    powershell -NoProfile -ExecutionPolicy Bypass -File kurulum\paket\yayinla.ps1
    # video / anlatim sayfasi hazirsa:  -Ekler D:\...\zeynep-icin.mp4, D:\...\anlatim.html
    # ayni adli dosya zaten varsa degistirmek icin: -Yeniden

  Release dosya siniri 2 GiB; asan dosya yuklenmez.
#>
param(
    [string]$Yedek = 'D:\reelsift-data\yayin\reelsift-veri-2026-11-18.dump',
    [string[]]$Ekler = @(),
    [switch]$Yeniden
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$kurulum = Split-Path -Parent $PSScriptRoot
. (Join-Path $kurulum 'adimlar\ortak.ps1')
Initialize-Ortam $kurulum

function Fail([string]$m) { Write-Output ('HATA: ' + $m); exit 1 }

$repo = $script:Sabit.repo
$etiket = $script:Sabit.etiket
$sinir = 2GB
$dosyalar = @($Yedek) + @($Ekler | Where-Object { $_ })
foreach ($d in $dosyalar) {
    if (-not (Test-Path $d -PathType Leaf)) { Fail ('Dosya yok: ' + $d) }
    if ((Get-Item $d).Length -ge $sinir) { Fail ('Dosya 2 GiB sinirini asiyor: ' + $d) }
}

$tok = Get-GitHubToken
if (-not $tok) { Fail 'GitHub kimligi alinamadi (git credential fill bos dondu).' }
$cfg = Get-GitHubYapilandirma $tok
$api = 'https://api.github.com/repos/' + $repo

# Yuklemeden once reponun OZEL oldugunu API'den dogrula; degilse dur (veri paketi herkese acik olmamali).
$rr = Invoke-Curl -Argumanlar @('-m', '40', '-H', 'Accept: application/vnd.github+json', '-w', "`n%{http_code}", $api) -Yapilandirma $cfg
$rc = Split-HttpCevap $rr
if ($rc.Http -ne 200) { Fail ('Repo bilgisi okunamadi (HTTP ' + $rc.Http + '); ozel oldugu dogrulanamadigi icin yukleme yapilmadi.') }
$repoBilgi = $null
try { $repoBilgi = $rc.Govde | ConvertFrom-Json } catch {}
if (-not $repoBilgi -or $repoBilgi.private -ne $true) { Fail ('Repo (' + $repo + ') ozel gorunmuyor; yukleme yapilmadi. Once reponun ozel oldugundan emin ol.') }
Write-Output ('Repo ozel: ' + $repo)

function Get-Rel {
    $r = Invoke-Curl -Argumanlar @('-m', '40', '-H', 'Accept: application/vnd.github+json', '-w', "`n%{http_code}", ($api + '/releases/tags/' + $etiket)) -Yapilandirma $cfg
    return (Split-HttpCevap $r)
}

$c = Get-Rel
if ($c.Http -eq 200) {
    $rel = $c.Govde | ConvertFrom-Json
    Write-Output ('Release zaten var (id ' + $rel.id + '); eksik dosyalar eklenecek.')
} elseif ($c.Http -eq 404) {
    $govdeDosya = Join-Path $script:DurumDir 'release-govde.json'
    $json = ConvertTo-Json -Compress -InputObject ([ordered]@{
        tag_name = $etiket
        name = 'ReelSift veri paketi'
        body = 'ReelSift kurulumu icin veri paketi: temiz veritabani yedegi (film / arama verisi; kullanici ve sohbet verisi yok). Kurulum betigi (kurulum/kur.ps1) bunu kendisi indirir.'
        draft = $false
        prerelease = $false
    })
    [System.IO.File]::WriteAllText($govdeDosya, $json, $script:Utf8)
    $r = Invoke-Curl -Argumanlar @('-m', '60', '-X', 'POST', '-H', 'Accept: application/vnd.github+json', '-H', 'Content-Type: application/json', '--data-binary', ('@' + $govdeDosya), '-w', "`n%{http_code}", ($api + '/releases')) -Yapilandirma $cfg
    Remove-Item -Force $govdeDosya -ErrorAction SilentlyContinue
    $k = Split-HttpCevap $r
    if ($k.Http -ne 201) { Fail ('Release olusturulamadi (HTTP ' + $k.Http + ').') }
    $rel = $k.Govde | ConvertFrom-Json
    Write-Output ('Release olusturuldu (id ' + $rel.id + ').')
} else {
    Fail ('Release sorgusu beklenmedik cevap verdi (HTTP ' + $c.Http + ').')
}

foreach ($d in $dosyalar) {
    $ad = Split-Path -Leaf $d
    $boyut = (Get-Item $d).Length
    $var = @($rel.assets | Where-Object { $_.name -eq $ad }) | Select-Object -First 1
    if ($var) {
        if (-not $Yeniden) {
            if ($var.state -ne 'uploaded' -or [int64]$var.size -ne $boyut) {
                Write-Output ('YARIM / FARKLI dosya duruyor: ' + $ad + ' (durum ' + $var.state + ', ' + $var.size + ' / ' + $boyut + ' bayt). Silip bastan yuklemek icin ayni komutu -Yeniden ile calistir.')
            } else {
                Write-Output ('Zaten var, atlandi: ' + $ad + ' (degistirmek icin -Yeniden ile calistir)')
            }
            continue
        }
        $s = Invoke-Curl -Argumanlar @('-m', '60', '-X', 'DELETE', '-o', 'NUL', '-w', '%{http_code}', ($api + '/releases/assets/' + $var.id)) -Yapilandirma $cfg
        if (([string]$s.Cikti).Trim() -ne '204') { Fail ('Eski dosya silinemedi: ' + $ad) }
    }
    Write-Output ('Yukleniyor: ' + $ad + ' (' + (Format-Boyut $boyut) + ')')
    $url = 'https://uploads.github.com/repos/' + $repo + '/releases/' + $rel.id + '/assets?name=' + [uri]::EscapeDataString($ad)
    $r = Invoke-Curl -Argumanlar @('-X', 'POST', '-H', 'Accept: application/vnd.github+json', '-H', 'Content-Type: application/octet-stream', '-T', $d, '-w', "`n%{http_code}", $url) -Yapilandirma $cfg -TikMs 5000
    $k = Split-HttpCevap $r
    if ($k.Http -ne 201) { Fail ('Yukleme basarisiz: ' + $ad + ' (HTTP ' + $k.Http + ', curl ' + $k.CurlKodu + '). Yarim kalmis bir dosya release icinde duruyor olabilir; ayni komutu -Yeniden ile calistir (yarim dosya silinip bastan yuklenir).') }
}

# Dogrulama: dosya adlari ve boyutlari yerelle eslesmeli.
$c = Get-Rel
if ($c.Http -ne 200) { Fail 'Yayin sonrasi release okunamadi.' }
$rel = $c.Govde | ConvertFrom-Json
$tamam = $true
foreach ($d in $dosyalar) {
    $ad = Split-Path -Leaf $d
    $a = @($rel.assets | Where-Object { $_.name -eq $ad }) | Select-Object -First 1
    if ($a -and $a.state -eq 'uploaded' -and [int64]$a.size -eq (Get-Item $d).Length) {
        Write-Output ('TAMAM  ' + $ad + '  ' + $a.size + ' bayt')
    } else {
        Write-Output ('EKSIK  ' + $ad + '  (yarim ya da eksik kalmis olabilir: ayni komutu -Yeniden ile calistir)'); $tamam = $false
    }
}
if (-not $tamam) { exit 1 }
Write-Output ('Yayin tamam: etiket ' + $etiket)
