<#
  Turkce (tr-TR) kultur denemesi: betik yardimcilari 'i' / 'I' tuzagina dusmeden calisiyor mu?
  Hicbir gercek is yapmaz (ag, Docker, kurulum yok); gecici klasorde calisir.
    powershell -NoProfile -ExecutionPolicy Bypass -File kurulum\test-tr-kulturu.ps1
  Cikis kodu 0 = hepsi gecti.
#>
$ErrorActionPreference = 'Stop'
$tr = [System.Globalization.CultureInfo]::GetCultureInfo('tr-TR')
[System.Threading.Thread]::CurrentThread.CurrentCulture = $tr
[System.Threading.Thread]::CurrentThread.CurrentUICulture = $tr

$kurulum = $PSScriptRoot
. (Join-Path $kurulum 'adimlar\ortak.ps1')
. (Join-Path $kurulum 'adimlar\adimlar.ps1')
Initialize-Ortam $kurulum -Deneme

$gecici = Join-Path ([System.IO.Path]::GetTempPath()) ('reelsift-trtest-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $gecici | Out-Null
$script:Kok = $gecici

$script:Gecen = 0
$script:Kalan = 0
function Denetle([string]$Ad, [bool]$Sonuc) {
    if ($Sonuc) { $script:Gecen++; Write-Output ('GECTI  ' + $Ad) }
    else { $script:Kalan++; Write-Output ('KALDI  ' + $Ad) }
}

try {
    Denetle 'kultur tr-TR' ([System.Threading.Thread]::CurrentThread.CurrentCulture.Name -eq 'tr-TR')
    Denetle "tuzak var: tr-TR'de 'I' -match '^[A-Za-z]$' False (bu denemenin anlami)" (-not ('I' -match '^[A-Za-z]$'))

    # 1. Gemini anahtari bicim denetimi (sahte anahtarlar; gercek degil)
    $sahte = 'AIzaSyD-sahte_anahtar_0123456789ABCDEFGHI'
    Denetle 'eski desen sahte AIza anahtarini reddederdi (hata A kaniti)' ($sahte -notmatch '^[A-Za-z0-9_\-]{20,100}$')
    Denetle 'AIza... bicimli sahte anahtar KABUL' (Test-AnahtarBicimi $sahte)
    Denetle 'buyuk I iceren anahtar KABUL' (Test-AnahtarBicimi 'IIIIIIIIIIIIIIIIIIIIIIIIIIIIIIII')
    Denetle 'bosluklu anahtar RET' (-not (Test-AnahtarBicimi 'AIzaSyD sahte_anahtar_0123456789'))
    Denetle 'basinda bosluk kalan anahtar RET' (-not (Test-AnahtarBicimi (' ' + $sahte)))
    Denetle 'kisa anahtar RET' (-not (Test-AnahtarBicimi 'AIzaKisa'))
    Denetle 'Turkce harfli (I noktali) anahtar RET' (-not (Test-AnahtarBicimi ('AIzaSyD-sahte_anahtar_' + [char]0x0130 + '0123456789')))
    Denetle 'bos anahtar RET' (-not (Test-AnahtarBicimi ''))
    Denetle 'yeni bicim AQ. (noktali) sahte anahtar KABUL' (Test-AnahtarBicimi 'AQ.Ab8sahte_anahtar-0123456789abcdefGHIJ')
    Denetle 'cok uzun anahtar RET' (-not (Test-AnahtarBicimi ('A' * 201)))

    # 2. .env okuma / yazma: I iceren anahtar adlari, buyuk-kucuk harf duyarli
    $envYolu = Get-EnvYolu
    [System.IO.File]::WriteAllText($envYolu, "LLM_PROVIDER=anthropic`nGEMINI_API_KEY=`nDJANGO_DB_PASSWORD=x`nllm_provider=kucuk`n", $script:Utf8)
    Denetle 'Read-EnvDeger LLM_PROVIDER (I iceren ad)' ((Read-EnvDeger 'LLM_PROVIDER') -ceq 'anthropic')
    Set-EnvDeger 'LLM_PROVIDER' 'gemini'
    Set-EnvDeger 'GEMINI_API_KEY' 'abc'
    Denetle 'Set-EnvDeger LLM_PROVIDER guncelledi' ((Read-EnvDeger 'LLM_PROVIDER') -ceq 'gemini')
    Denetle 'Set-EnvDeger GEMINI_API_KEY guncelledi' ((Read-EnvDeger 'GEMINI_API_KEY') -ceq 'abc')
    Denetle 'kucuk harfli satira dokunmadi' ((Read-EnvSatirlari) -contains 'llm_provider=kucuk')
    Denetle 'olmayan ad bos' ($null -eq (Read-EnvDeger 'YOK_BOYLE_AD'))

    # 3. Indirilen dosya ozeti (buyuk harfli beklenen ozet de kabul; yanlis ozet silinir)
    $dosya = Join-Path $gecici 'sahte.bin'
    $govde = [byte[]](1..200)
    $dogru = (Get-FileHash -Algorithm SHA256 -InputStream (New-Object System.IO.MemoryStream(, $govde))).Hash
    $indirildi = 0
    $indir = { $script:IndirmeSayisi++; [System.IO.File]::WriteAllBytes($dosya, $govde); return $true }
    $script:IndirmeSayisi = 0
    Denetle 'dogru ozet (BUYUK HARF) -> tamam' ((Confirm-DosyaOzeti -Yol $dosya -Beklenen $dogru -Indir $indir) -eq 'tamam')
    Remove-Item -Force $dosya
    $script:IndirmeSayisi = 0
    $sonuc = Confirm-DosyaOzeti -Yol $dosya -Beklenen ('0' * 64) -Indir $indir
    Denetle 'yanlis ozet -> bozuk, dosya silindi, bir kez yeniden indirildi' (($sonuc -eq 'bozuk') -and (-not (Test-Path $dosya)) -and ($script:IndirmeSayisi -eq 2))

    # 4. Http cevabini ayirma (LastIndexOf ordinal)
    $c = Split-HttpCevap ([pscustomobject]@{ Cikti = "{`"a`":1}`n200"; Kod = 0; Hata = '' })
    Denetle 'Split-HttpCevap govde ve kod' (($c.Http -eq 200) -and ($c.Govde -ceq '{"a":1}'))

    # 5. Surucu harfi: tr-TR'de 'i'.ToUpper() noktali I olur; Invariant kullaniliyor
    Denetle "surucu harfi 'i' -> 'I' (Invariant)" (('i'.ToUpperInvariant()) -ceq 'I')

    # 6. Arama hazir satiri (noktasiz i) ve KULLANICI_TAMAM ayni harfle eslesir
    Denetle "'Arama hazir' (dotless) gunluk eslesmesi" ('INFO Arama hazır (12 sn)' -cmatch 'Arama hazır')
    Denetle 'KULLANICI_TAMAM eslesmesi' ('KULLANICI_TAMAM' -cmatch 'KULLANICI_TAMAM')

    # 7. Modeller hazir.json isareti
    $modelKlasoru = Join-Path $gecici 'modeller'
    New-Item -ItemType Directory -Force -Path $modelKlasoru | Out-Null
    $hazirYolu = Join-Path $modelKlasoru 'hazir.json'
    Denetle 'hazir.json yokken Test-ModellerHazir False' (-not (Test-ModellerHazir))
    $liste = @()
    foreach ($b in @($script:Sabit.modeller)) { $liste += @{ model = $b.model; surum = $b.surum; dosya_sayisi = $b.dosya_sayisi; bayt = 1000 } }
    [System.IO.File]::WriteAllText($hazirYolu, (ConvertTo-Json -InputObject @{ surum = 1; modeller = $liste } -Depth 5), $script:Utf8)
    Denetle 'dogru hazir.json -> True' (Test-ModellerHazir)
    $liste[0].surum = 'yanlis'
    [System.IO.File]::WriteAllText($hazirYolu, (ConvertTo-Json -InputObject @{ surum = 1; modeller = $liste } -Depth 5), $script:Utf8)
    Denetle 'yanlis surum -> False' (-not (Test-ModellerHazir))
    $liste[0].surum = $script:Sabit.modeller[0].surum
    $liste[1].dosya_sayisi = 1
    [System.IO.File]::WriteAllText($hazirYolu, (ConvertTo-Json -InputObject @{ surum = 1; modeller = $liste } -Depth 5), $script:Utf8)
    Denetle 'eksik dosya sayisi -> False' (-not (Test-ModellerHazir))

    # 8. Model ilerlemesi: .incomplete dosyalar sayilir, hazir.json sayilmaz, gunluk ILERLEME satiri buyukse o alinir
    $hub = Join-Path $modelKlasoru 'hub\models--x\blobs'
    New-Item -ItemType Directory -Force -Path $hub | Out-Null
    [System.IO.File]::WriteAllBytes((Join-Path $hub 'abc.incomplete'), (New-Object byte[] 5000))
    $log = Join-Path $gecici 'adim.log'
    [System.IO.File]::WriteAllText($log, "INDIRILIYOR x`r`nILERLEME 3000`r`n", $script:Utf8)
    Denetle 'Get-ModelBayt: .incomplete sayilir, hazir.json sayilmaz (5000)' ((Get-ModelBayt $log) -eq 5000)
    [System.IO.File]::WriteAllText($log, "ILERLEME 9000`r`n", $script:Utf8)
    Denetle 'Get-ModelBayt: gunluk ILERLEME daha buyukse o (9000)' ((Get-ModelBayt $log) -eq 9000)
}
finally {
    Remove-Item -Recurse -Force $gecici -ErrorAction SilentlyContinue
}

Write-Output ('--- ' + $script:Gecen + ' gecti, ' + $script:Kalan + ' kaldi ---')
if ($script:Kalan -gt 0) { exit 1 }
exit 0
