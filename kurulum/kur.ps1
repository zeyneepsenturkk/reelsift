<#
  ReelSift kurulum motoru (Windows PowerShell 5.1; Python / Node gerekmez).
  Adimlar bagimsiz ve yeniden calistirilabilir: biten adim atlanir, yarim indirme kaldigi yerden surer.
  Durum: kurulum\.durum\durum.json (atomik yazilir); tam gunluk: kurulum\.durum\kurulum.log.

  Normal kullanim (sayfa bunu kendisi baslatir):
    powershell -NoProfile -ExecutionPolicy Bypass -File kurulum\kur.ps1

  Sayfa dogrulamasi icin gercek is yapmayan kip (yalniz gorunum denemesi):
    kur.ps1 -Deneme                     tum adimlar sahte sure ve ilerlemeyle
    kur.ps1 -Deneme -HataAdimi 4        4. adim ornek hatayla biter (Tekrar dene ile gecer)
    kur.ps1 -Deneme -KullaniciAdimi 1   1. adim "Docker yok" gibi kullanicidan is bekler
    kur.ps1 -Deneme -DenemeDur 4:40     4. adim %40'ta durur (ilerleme gorunumu icin)
    kur.ps1 -Deneme -DenemeDur 4:kontrol  4. adim "indirilen dosyayi kontrol ediyorum" durumunda durur
  Deneme kipi kendi durum klasorunu (kurulum\.durum-deneme\) kullanir; gercek kuruluma karismaz.
  Gercek modda tek adim: kur.ps1 -Sadece kontrol
#>
param(
    [switch]$Deneme,
    [int]$HataAdimi = 0,
    [int]$KullaniciAdimi = 0,
    [double]$DenemeHiz = 1,
    [string]$DenemeDur = '',
    [switch]$Bastan,
    [string]$Sadece = ''
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

. (Join-Path $PSScriptRoot 'adimlar\ortak.ps1')
. (Join-Path $PSScriptRoot 'adimlar\adimlar.ps1')
Initialize-Ortam $PSScriptRoot -Deneme:$Deneme

# Ayni anda tek kurulum: kilit alinamazsa baska kopya calisiyordur; hicbir seye dokunmadan cik.
$kilit = Enter-KurKilidiBekle
if (-not $kilit) {
    Write-Log 'Baska bir kurulum calisiyor; bu kopya hicbir sey yapmadan cikti.'
    Write-Output 'Kurulum zaten calisiyor.'
    exit 3
}
$pidDosyasi = Join-Path $script:DurumDir 'kur.pid'
[System.IO.File]::WriteAllText($pidDosyasi, [string]$PID, $script:Utf8)

$denemeIsareti = Join-Path $script:DurumDir 'deneme-hata-verildi'
$denemeAnahtar = Join-Path $script:DurumDir 'deneme-anahtar'
$kip = 'gercek'
if ($Deneme) { $kip = 'deneme' }

# --- Durumu yukle / sifirla ------------------------------------------------------------------
$mevcut = $null
if (-not $Bastan) { $mevcut = Read-JsonDosya $script:DurumDosyasi }
$yeni = $false
if (-not $mevcut -or $mevcut.kip -ne $kip) { $yeni = $true }
elseif (@($mevcut.adimlar).Count -ne @($script:Sabit.adimlar).Count) { $yeni = $true }
if ($yeni) {
    $script:Durum = New-Durum
    foreach ($f in @($denemeIsareti, $denemeAnahtar, $script:LogDosyasi, (Join-Path $script:DurumDir 'saglayici-secildi'))) { if (Test-Path $f) { Remove-Item -Force $f } }
} else {
    $script:Durum = $mevcut
    # Yarim kalan adimlar bastan denenir; biten adimlar kalir.
    foreach ($a in $script:Durum.adimlar) {
        if ($a.durum -eq 'suruyor' -or $a.durum -eq 'hata' -or $a.durum -eq 'kullanici') {
            $a.durum = 'bekliyor'; $a.ne_oldu = ''; $a.ne_yapmali = ''; $a.baglanti = $null; $a.mesaj = ''
            $a.yuzde = $null; $a.bayt = $null; $a.toplam = $null; $a.kalan_sn = $null
        }
    }
}
$script:Durum.kip = $kip
if (-not $script:Durum.baslangic) { $script:Durum.baslangic = Get-Now }
$script:Durum.bitis = $null
$script:Durum.tahmini_toplam = $script:Sabit.tahmini_toplam
Save-Durum
Write-Log ('--- Kurulum ' + $kip + ' kipinde basladi ---')

# --- Deneme kipi: gercek is yapmadan adimlari canlandirir -------------------------------------
$denemeSureleri = @(4, 5, 0, 12, 10, 12, 8, 4, 2, 8, 3)
$denemeBayt = @{ 4 = 2100000000; 6 = 4586557909 }
$denemeMesajlari = @{
    1 = @('Windows sürümüne bakıyorum.', 'Diskteki boş yere bakıyorum.', 'Docker Desktop çalışıyor mu bakıyorum.', 'Ekran kartına bakıyorum.')
    2 = @('Videonun burada olup olmadığına bakıyorum.')
    4 = @('Film arşivini indiriyorum.')
    5 = @('Şu an: [backend 3/7] RUN pip install -r requirements-ml.txt', 'Şu an: [frontend 4/6] RUN npm ci', 'Şu an: [backend 6/7] COPY . .')
    6 = @('Modelleri indiriyorum.')
    7 = @('Veritabanını açıyorum.', 'Film verisini yerleştiriyorum ve arama indekslerini kuruyorum (bu adım uzun sürer).', 'Veritabanı düzenini güncelliyorum.')
    8 = @('Dizini kuruyorum; birkaç dakika sürebilir.')
    9 = @('Hesabını açıyorum.')
    10 = @('Uygulamayı başlatıyorum.', 'Uygulama açıldı; arama modelleri ısınıyor (2-4 dakika).')
    11 = @('Giriş deniyorum.', 'Yapay zekâya kısa bir soru soruyorum (anahtar ve kota deneniyor).')
}
$denemeSonMesaj = @{
    1 = 'Her şey hazır. Ekran kartın: NVIDIA GeForce (deneme).'
    4 = 'Film arşivi indi.'; 5 = 'Uygulama ortamı hazır.'; 6 = 'Modeller indi.'; 7 = 'Film arşivi yüklendi.'
    8 = 'Arama dizini hazır.'; 9 = 'Hesabın hazır: editor'; 10 = 'Uygulama ve arama hazır.'; 11 = 'Her şey çalışıyor.'
}

function Invoke-DenemeAdimi($Adim, [int]$Sira) {
    $id = $Adim.id
    $sn = $denemeSureleri[$Sira - 1] / $DenemeHiz
    $sahteGunluk = @(
        '[deneme] bu satirlar sayfa denemesi icindir, gercek bir komut calismadi.',
        '[deneme] adim: ' + $id
    )

    if ($KullaniciAdimi -eq $Sira -and -not (Test-Path $denemeIsareti)) {
        [System.IO.File]::WriteAllText($denemeIsareti, '1', $script:Utf8)
        Start-Sleep -Milliseconds 800
        $b = [pscustomobject]@{ ad = "Docker Desktop'ı indir"; url = 'https://www.docker.com/products/docker-desktop/' }
        $yap = "1. Aşağıdaki bağlantıdan Docker Desktop'ı indirip kur. Kurulumda 'WSL 2' seçeneği açık kalsın.`n2. Kurulum bilgisayarı yeniden başlatmanı isteyebilir; yeniden başlat.`n3. Başlat menüsünden Docker Desktop'ı aç ve sol altta 'Engine running' (yeşil) yazana kadar bekle.`n4. Bu sayfaya dönüp Tekrar dene'ye bas. (Bilgisayarı yeniden başlattıysan Claude'a 'kuruluma devam edelim' yaz.)"
        return New-Sonuc 'kullanici' '' 'Docker Desktop kurulu değil. Uygulama onun içinde çalışacak.' $yap $b
    }

    if ($id -eq 'anahtar') {
        Set-Adim $id @{ durum = 'kullanici'; mesaj = 'Anahtarını bekliyorum.'; gunluk = $sahteGunluk }
        while (-not (Test-Path $denemeAnahtar)) { Start-Sleep -Milliseconds 700 }
        Set-Adim $id @{ durum = 'suruyor'; mesaj = 'Anahtarı aldım.' }
        Start-Sleep -Milliseconds 700
        return New-Sonuc 'tamam' 'Anahtar kaydedildi ve çalışıyor.'
    }

    $mesajlar = @($denemeMesajlari[$Sira])
    $toplam = $null
    if ($denemeBayt.ContainsKey($Sira)) { $toplam = [int64]$denemeBayt[$Sira] }
    $adimSayisi = [math]::Max(4, [int]($sn * 2))
    if ($toplam) { $adimSayisi = 50 }
    $bekleMs = [int]([math]::Max(30, ($sn * 1000) / $adimSayisi))
    for ($i = 1; $i -le $adimSayisi; $i++) {
        $p = $i / $adimSayisi
        $alan = @{ gunluk = $sahteGunluk }
        if ($mesajlar.Count -gt 0 -and $mesajlar[0]) {
            $alan.mesaj = $mesajlar[[math]::Min($mesajlar.Count - 1, [int]([math]::Floor($p * $mesajlar.Count * 0.999)))]
        }
        if ($toplam) {
            $bayt = [int64]($toplam * $p)
            $alan.bayt = $bayt; $alan.toplam = $toplam
            $alan.yuzde = [int][math]::Min(99, [math]::Floor($p * 100))
            $alan.kalan_sn = [int](($sn * (1 - $p)) * $DenemeHiz * 3)
        }
        if ($HataAdimi -eq $Sira -and $p -ge 0.6 -and -not (Test-Path $denemeIsareti)) {
            [System.IO.File]::WriteAllText($denemeIsareti, '1', $script:Utf8)
            $alan.gunluk = @(
                '[deneme] curl: (18) transfer closed with outstanding read data remaining',
                '[deneme] 3 kez yeniden denendi, baglanti yine kesildi.',
                '[deneme] bu bir deneme hatasidir; gercek bir indirme yapilmadi.'
            )
            Set-Adim $id $alan
            return New-Sonuc 'hata' '' 'İndirme yarıda kesildi (deneme hatası).' ("İnternet bağlantını kontrol edip Tekrar dene'ye bas; indirme kaldığı yerden devam eder.")
        }
        if ($DenemeDur) {
            $parca = $DenemeDur.Split(':')
            if ($parca[1] -match '^\d+$' -and [int]$parca[0] -eq $Sira -and $alan.ContainsKey('yuzde') -and $alan.yuzde -ge [int]$parca[1]) {
                Set-Adim $id $alan
                while ($true) { Start-Sleep -Seconds 5 }
            }
        }
        Set-Adim $id $alan
        Start-Sleep -Milliseconds $bekleMs
    }
    if ($id -eq 'video' -and (Test-RepoVideo)) { return New-Sonuc 'tamam' 'Video hazır; beklerken izleyebilirsin.' }
    if ($id -eq 'video') { return New-Sonuc 'atlandi' 'Bu sefer video yok; kurulum bundan etkilenmiyor.' }
    $son = $denemeSonMesaj[$Sira]
    if ($toplam) { Set-Adim $id @{ bayt = $toplam; toplam = $toplam; yuzde = 100 } }
    if ($id -eq 'arsiv') {
        # Gercek adimdaki ozet denetimi (SHA256) gorunumu: -DenemeDur 4:kontrol burada durur.
        Set-Adim $id @{ mesaj = 'İndirilen dosyayı kontrol ediyorum.'; yuzde = $null; bayt = $null; toplam = $null; kalan_sn = $null; gunluk = $sahteGunluk }
        if ($DenemeDur -eq ($Sira.ToString() + ':kontrol')) { while ($true) { Start-Sleep -Seconds 5 } }
        Start-Sleep -Milliseconds ([int](3000 / $DenemeHiz))
    }
    return New-Sonuc 'tamam' $son
}

# --- Ana dongu ------------------------------------------------------------------------------
$islevler = @{
    kontrol = 'Adim-Kontrol'; video = 'Adim-Video'; anahtar = 'Adim-Anahtar'; arsiv = 'Adim-Arsiv'
    uygulama = 'Adim-Uygulama'; modeller = 'Adim-Modeller'; yukleme = 'Adim-Yukleme'; dizin = 'Adim-Dizin'
    kullanici = 'Adim-Kullanici'; baslatma = 'Adim-Baslatma'; son = 'Adim-Son'
}
$cikis = 0
try {
    $sira = 0
    foreach ($adim in @($script:Durum.adimlar)) {
        $sira++
        if ($Sadece -and $adim.id -ne $Sadece) { continue }
        $guncel = Get-Adim $adim.id
        if ($guncel.durum -eq 'tamam' -or $guncel.durum -eq 'atlandi') { continue }

        $script:GecerliLog = $null
        $script:Durum.aktif = $adim.id
        $t0 = Get-Date
        Set-Adim $adim.id @{ durum = 'suruyor'; baslangic = (Get-Now); bitis = $null; mesaj = ''; ne_oldu = ''; ne_yapmali = ''; baglanti = $null; gunluk = @() }
        Write-Log ('== Adim ' + $sira + ': ' + $adim.ad)

        $sonuc = $null
        try {
            if ($Deneme) { $sonuc = Invoke-DenemeAdimi $adim $sira }
            else { $sonuc = & $islevler[$adim.id] }
        } catch {
            Write-Log ('ISTISNA: ' + $_.Exception.Message)
            Write-Log ('  ' + ($_.ScriptStackTrace -replace "`r?`n", ' | '))
            $sonuc = New-Sonuc 'hata' '' 'Beklenmedik bir sorun çıktı.' ("Tekrar dene'ye bas. Yine olursa: " + (Get-ClaudeCumlesi $adim.ad))
        }

        $alan = @{ bitis = (Get-Now); durum = $sonuc.Durum }
        if ($sonuc.Mesaj) { $alan.mesaj = $sonuc.Mesaj }
        if ($sonuc.Durum -eq 'tamam') { $alan.yuzde = 100; $alan.kalan_sn = $null; $alan.ne_oldu = ''; $alan.ne_yapmali = ''; $alan.baglanti = $null }
        if ($sonuc.Durum -eq 'atlandi') { $alan.yuzde = $null; $alan.kalan_sn = $null }
        if ($sonuc.Durum -eq 'hata' -or $sonuc.Durum -eq 'kullanici') {
            $alan.ne_oldu = $sonuc.NeOldu
            $alan.ne_yapmali = $sonuc.NeYapmali
            $alan.baglanti = $sonuc.Baglanti
            $alan.kalan_sn = $null
            if ($sonuc.Mesaj) { $alan.mesaj = $sonuc.Mesaj } else { $alan.mesaj = '' }
        }
        Set-Adim $adim.id $alan -GunlukGuncelle
        Write-Log ('   sonuc: ' + $sonuc.Durum + ' (' + [int]((Get-Date) - $t0).TotalSeconds + ' sn)')

        if ($sonuc.Durum -eq 'hata' -or $sonuc.Durum -eq 'kullanici') { $cikis = 1; break }
    }
    if ($cikis -eq 0) {
        $script:Durum.aktif = $null
        if ((Get-GenelDurum $script:Durum) -eq 'tamam') { $script:Durum.bitis = Get-Now }
        Save-Durum
        Write-Log '--- Kurulum bitti ---'
    }
} finally {
    if (Test-Path $pidDosyasi) { Remove-Item -Force $pidDosyasi -ErrorAction SilentlyContinue }
    $kilit.Dispose()
}
exit $cikis
