# Gercek kurulum adimlari (kur.ps1 tarafindan nokta-kaynak ile yuklenir; ortak.ps1 once yuklenmis olmali).
# Her adim fonksiyonu bir sonuc nesnesi dondurur: Durum = tamam | atlandi | kullanici | hata.
# Windows PowerShell 5.1 uyumlu. Gizli bilgi (GitHub kimligi, Gemini anahtari) ne loga ne duruma yazilir.

function New-Sonuc {
    param([string]$Durum, [string]$Mesaj = '', [string]$NeOldu = '', [string]$NeYapmali = '', $Baglanti = $null)
    return [pscustomobject]@{ Durum = $Durum; Mesaj = $Mesaj; NeOldu = $NeOldu; NeYapmali = $NeYapmali; Baglanti = $Baglanti }
}

function Get-ClaudeCumlesi([string]$AdimAdi) {
    return ("Yapay zekâ asistanına şunu yaz: Kurulum '" + $AdimAdi + "' adımında takıldı.")
}

# Kisa komut calistirir (zaman asimli); stdout/stderr toplanir.
function Invoke-Komut {
    param([string]$Exe, [string[]]$Argumanlar = @(), [int]$ZamanAsimiSn = 60, [string]$Girdi = $null, [string]$Klasor = $null)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe
    $psi.Arguments = ConvertTo-ArgString $Argumanlar
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    if ($Klasor) { $psi.WorkingDirectory = $Klasor }
    try { $p = [System.Diagnostics.Process]::Start($psi) } catch {
        return [pscustomobject]@{ Kod = -1; Cikti = ''; Hata = $_.Exception.Message; ZamanAsimi = $false }
    }
    $outTask = $p.StandardOutput.ReadToEndAsync()
    $errTask = $p.StandardError.ReadToEndAsync()
    if ($Girdi) { Write-Stdin $p $Girdi }
    $p.StandardInput.Close()
    $zamanAsimi = $false
    if (-not $p.WaitForExit($ZamanAsimiSn * 1000)) {
        $zamanAsimi = $true
        try { & taskkill.exe /PID $p.Id /T /F | Out-Null } catch {}
    }
    $p.WaitForExit()
    return [pscustomobject]@{ Kod = $p.ExitCode; Cikti = $outTask.Result; Hata = $errTask.Result; ZamanAsimi = $zamanAsimi }
}

# Uzun docker komutu: cikti bir dosyaya yazilir, her $TikMs'de $Tik cagrilir.
function Invoke-DockerLog {
    param([string]$Argumanlar, [string]$Log, [scriptblock]$Tik = $null, [int]$TikMs = 2000, [int]$ZamanAsimiSn = 0)
    if (Test-Path $Log) { Remove-Item -Force $Log }
    $script:GecerliLog = $Log
    $inner = 'docker ' + $Argumanlar + ' > "' + $Log + '" 2>&1'
    Write-Log ('docker ' + $Argumanlar)
    $p = Start-Process -FilePath 'cmd.exe' -ArgumentList ('/d /s /c "' + $inner + '"') -WorkingDirectory $script:Kok -WindowStyle Hidden -PassThru
    $null = $p.Handle
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while (-not $p.WaitForExit($TikMs)) {
        if ($Tik) { & $Tik }
        if ($ZamanAsimiSn -gt 0 -and $sw.Elapsed.TotalSeconds -gt $ZamanAsimiSn) {
            try { & taskkill.exe /PID $p.Id /T /F | Out-Null } catch {}
            break
        }
    }
    $p.WaitForExit()
    $kod = $p.ExitCode
    foreach ($s in (Get-DosyaSonSatirlar $Log 30)) { Write-Log ('  | ' + $s) }
    Write-Log ('  -> cikis kodu ' + $kod)
    return $kod
}

function Get-AdimLogu([string]$Id) { return (Join-Path $script:DurumDir ('adim-' + $Id + '.log')) }

function Get-DbKonteyner {
    $r = Invoke-Komut 'docker' @('compose', 'ps', '-q', 'db') 30 $null $script:Kok
    if ($r.Kod -ne 0) { return $null }
    $ilk = ($r.Cikti -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -First 1)
    if ($ilk) { return $ilk.Trim() }
    return $null
}

function Invoke-Sql([string]$Konteyner, [string]$Sql, [int]$ZamanAsimiSn = 120) {
    return (Invoke-Komut 'docker' @('exec', '-i', $Konteyner, 'sh', '-c', 'psql -U $POSTGRES_USER -d $POSTGRES_DB -At -v ON_ERROR_STOP=1') $ZamanAsimiSn $Sql)
}

# --- Indirme ilerlemesi ----------------------------------------------------------------------

function Start-Ilerleme([string]$Id, [int64]$Toplam) {
    $script:Il = @{ Id = $Id; Toplam = $Toplam; Ornekler = (New-Object System.Collections.ArrayList) }
}

# Kalan sure son ~30 sn'nin hizindan hesaplanir (tum sureyi ortalamak sicrama ve yanlis tahmin verir).
function Update-Ilerleme([int64]$Bayt) {
    $il = $script:Il
    $simdi = Get-Date
    [void]$il.Ornekler.Add(@{ T = $simdi; B = $Bayt })
    while ($il.Ornekler.Count -gt 2 -and (($simdi - $il.Ornekler[1].T).TotalSeconds -gt 30)) { $il.Ornekler.RemoveAt(0) }
    $ilk = $il.Ornekler[0]
    $gecen = ($simdi - $ilk.T).TotalSeconds
    $hiz = 0.0
    if ($gecen -gt 4) { $hiz = ($Bayt - $ilk.B) / $gecen }
    $kalan = $null
    if ($hiz -gt 1024 -and $il.Toplam -gt $Bayt) { $kalan = [int](($il.Toplam - $Bayt) / $hiz) }
    $yuzde = 0
    if ($il.Toplam -gt 0) { $yuzde = [int][math]::Min(99, [math]::Floor(100.0 * $Bayt / $il.Toplam)) }
    Set-Adim $il.Id @{ bayt = [int64]$Bayt; toplam = [int64]$il.Toplam; yuzde = $yuzde; kalan_sn = $kalan }
}

# Release bilgisi (bir calistirmada bir kez). Once KIMLIKSIZ denenir (herkese acik repo); 401 / 403 / 404 gelirse ve
# bilgisayarda saklanan bir GitHub kimligi varsa bir kez de onunla denenir (ozel repo destegi). Kimlik yoksa bu hata degildir.
function Get-ReleaseVeKimlik {
    if ($script:ReleaseOnbellek) { return $script:ReleaseOnbellek }
    $rb = Get-ReleaseBilgi ''
    $token = $null
    if (-not $rb.Release -and ($rb.Http -eq 401 -or $rb.Http -eq 403 -or $rb.Http -eq 404)) {
        $token = Get-GitHubToken
        if ($token) {
            Write-Log ('Kimliksiz sorgu http ' + $rb.Http + '; saklanan GitHub kimligiyle bir kez daha deneniyor.')
            $rb = Get-ReleaseBilgi $token
        }
    }
    $sonuc = [pscustomobject]@{ Neden = 'tamam'; Token = $token; Release = $rb.Release; Http = $rb.Http; KimlikVardi = [bool]$token }
    if (-not $rb.Release) { $sonuc.Neden = 'release' }
    else { $script:ReleaseOnbellek = $sonuc }
    return $sonuc
}

# --- 1. Bilgisayar kontrolu ------------------------------------------------------------------

function Adim-Kontrol {
    $id = 'kontrol'
    $baglanti = $null
    Set-Adim $id @{ mesaj = 'Windows sürümüne bakıyorum.' } -GunlukGuncelle

    $os = Get-CimInstance Win32_OperatingSystem
    $build = [int]$os.BuildNumber
    Write-Log ('Windows: ' + $os.Caption + ' derleme ' + $build)
    if ($build -lt 19041) {
        return New-Sonuc 'kullanici' '' 'Windows sürümün Docker için fazla eski.' "Ayarlar > Windows Update'ten Windows'u güncelle, sonra Tekrar dene'ye bas."
    }

    Set-Adim $id @{ mesaj = 'Diskteki boş yere bakıyorum.' }
    $gb = 1GB
    $projeSurucu = (Split-Path -Qualifier $script:Kok).TrimEnd(':').ToUpperInvariant()
    $sistemSurucu = ([string]$env:SystemDrive).TrimEnd(':').ToUpperInvariant()
    $projeBos = ([System.IO.DriveInfo]($projeSurucu + ':\')).AvailableFreeSpace
    $sistemBos = ([System.IO.DriveInfo]($sistemSurucu + ':\')).AvailableFreeSpace
    Write-Log ('Bos alan: ' + $projeSurucu + ': ' + (Format-Boyut $projeBos) + '; sistem diski ' + $sistemSurucu + ': ' + (Format-Boyut $sistemBos))
    $d = $script:Sabit.disk
    if ($projeSurucu -eq $sistemSurucu) {
        if ($projeBos -lt ($d.toplam_gb * $gb)) {
            return New-Sonuc 'kullanici' '' ($projeSurucu + ': diskinde ' + [math]::Floor($projeBos / $gb) + ' GB boş yer var; kurulum için en az ' + $d.toplam_gb + ' GB gerekiyor.') 'Kullanmadığın büyük dosyaları sil ya da Geri Dönüşüm Kutusu''nu boşalt, sonra Tekrar dene''ye bas.'
        }
    } else {
        if ($projeBos -lt ($d.proje_diski_gb * $gb)) {
            return New-Sonuc 'kullanici' '' ($projeSurucu + ': diskinde ' + [math]::Floor($projeBos / $gb) + ' GB boş yer var; en az ' + $d.proje_diski_gb + ' GB gerekiyor.') 'Bu diskte yer aç, sonra Tekrar dene''ye bas.'
        }
        if ($sistemBos -lt ($d.docker_diski_gb * $gb)) {
            return New-Sonuc 'kullanici' '' ($sistemSurucu + ': diskinde ' + [math]::Floor($sistemBos / $gb) + ' GB boş yer var; Docker için en az ' + $d.docker_diski_gb + ' GB gerekiyor.') 'Bu diskte yer aç, sonra Tekrar dene''ye bas.'
        }
    }

    Set-Adim $id @{ mesaj = 'İnternet bağlantısına bakıyorum.' }
    if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
        return New-Sonuc 'kullanici' '' 'Bu bilgisayarda curl yok (Windows 10 sürümün eski olabilir).' "Windows'u güncelle, sonra Tekrar dene'ye bas."
    }
    foreach ($adres in @('https://api.github.com/', 'https://huggingface.co/')) {
        $r = Invoke-Curl -Argumanlar @('-m', '15', '-o', 'NUL', '-w', '%{http_code}', $adres)
        $kod = 0
        [int]::TryParse(([string]$r.Cikti).Trim(), [ref]$kod) | Out-Null
        Write-Log ('Internet: ' + $adres + ' -> ' + $kod)
        if ($kod -eq 0) {
            return New-Sonuc 'kullanici' '' 'İnternete ya da bu siteye ulaşamadım.' "Wi-Fi'nin bağlı olduğundan emin ol (tarayıcıda bir sayfa açılıyor mu?), sonra Tekrar dene'ye bas."
        }
    }

    Set-Adim $id @{ mesaj = 'Git kurulu mu bakıyorum.' }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        $b = [pscustomobject]@{ ad = "Git'i indir"; url = 'https://git-scm.com/download/win' }
        return New-Sonuc 'kullanici' '' 'Bilgisayarında Git yok.' "Aşağıdaki bağlantıdan Git'i indirip kur (hep 'Next' diyebilirsin), sonra Tekrar dene'ye bas." $b
    }

    Set-Adim $id @{ mesaj = 'Docker Desktop kurulu mu bakıyorum.' }
    $dockerYolu = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $dockerYolu) {
        $b = [pscustomobject]@{ ad = "Docker Desktop'ı indir"; url = 'https://www.docker.com/products/docker-desktop/' }
        $yap = "1. Aşağıdaki bağlantıdan Docker Desktop'ı indirip kur. Kurulumda 'WSL 2' seçeneği açık kalsın.`n2. Kurulum bilgisayarı yeniden başlatmanı isteyebilir; yeniden başlat.`n3. Başlat menüsünden Docker Desktop'ı aç ve sol altta 'Engine running' (yeşil) yazana kadar bekle.`n4. Bu sayfaya dönüp Tekrar dene'ye bas. (Bilgisayarı yeniden başlattıysan Claude'a 'kuruluma devam edelim' yaz.)"
        return New-Sonuc 'kullanici' '' "Docker Desktop kurulu değil. Uygulama onun içinde çalışacak." $yap $b
    }
    Set-Adim $id @{ mesaj = 'Docker çalışıyor mu bakıyorum.' }
    $info = Invoke-Komut 'docker' @('info', '--format', '{{.OSType}}|{{.MemTotal}}') 60
    Write-Log ('docker info kodu ' + $info.Kod + ' zaman asimi ' + $info.ZamanAsimi)
    if ($info.Kod -ne 0) {
        $yap = "1. Başlat menüsünden Docker Desktop'ı aç.`n2. Sol altta 'Engine running' (yeşil) yazana kadar bekle; ilk açılışta bir iki dakika sürebilir.`n3. Sonra Tekrar dene'ye bas."
        return New-Sonuc 'kullanici' '' 'Docker Desktop kurulu ama şu an açık değil.' $yap
    }
    $parca = ([string]$info.Cikti).Trim().Split('|')
    if ($parca[0] -ne 'linux') {
        return New-Sonuc 'kullanici' '' "Docker şu an 'Windows kapsayıcıları' kipinde." "Görev çubuğunun sağındaki Docker simgesine sağ tıkla, 'Switch to Linux containers' seç; sonra Tekrar dene'ye bas."
    }
    $bellekGb = 0
    if ($parca.Count -gt 1) { $bellekGb = [math]::Round([double]$parca[1] / 1GB, 1) }
    Write-Log ('Docker bellegi: ' + $bellekGb + ' GB')

    Set-Adim $id @{ mesaj = 'Ekran kartına bakıyorum.' }
    $nv = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    $nvYol = $null
    if ($nv) { $nvYol = $nv.Source }
    else {
        foreach ($aday in @("$env:SystemRoot\System32\nvidia-smi.exe", "$env:ProgramFiles\NVIDIA Corporation\NVSMI\nvidia-smi.exe")) {
            if (Test-Path $aday) { $nvYol = $aday; break }
        }
    }
    if (-not $nvYol) {
        $b = [pscustomobject]@{ ad = 'NVIDIA sürücü sayfası'; url = 'https://www.nvidia.com/Download/index.aspx' }
        return New-Sonuc 'kullanici' '' 'NVIDIA ekran kartı sürücüsünü bulamadım.' "Aşağıdaki sayfadan ekran kartın için güncel sürücüyü indirip kur, bilgisayarı yeniden başlat; sonra Tekrar dene'ye bas." $b
    }
    $g = Invoke-Komut $nvYol @('--query-gpu=name,driver_version,memory.total', '--format=csv,noheader') 30
    if ($g.Kod -ne 0 -or -not ([string]$g.Cikti).Trim()) {
        return New-Sonuc 'kullanici' '' 'Ekran kartı sürücüsü cevap vermiyor.' "Bilgisayarı yeniden başlatıp Tekrar dene'ye bas. Olmazsa NVIDIA sürücüsünü yeniden kur."
    }
    $gpuSatiri = (([string]$g.Cikti -split "`r?`n")[0]).Trim()
    Write-Log ('Ekran karti: ' + $gpuSatiri)
    $gpuAdi = ($gpuSatiri -split ',')[0].Trim()

    Set-Adim $id @{ mesaj = 'Docker ekran kartını görüyor mu bakıyorum (ilk seferde bir dakika sürebilir).' }
    $imaj = $null
    foreach ($aday in @('postgres:16', 'node:24-slim', 'pgvector/pgvector:pg18', 'debian:12-slim')) {
        $x = Invoke-Komut 'docker' @('image', 'inspect', $aday) 30
        if ($x.Kod -eq 0) { $imaj = $aday; break }
    }
    if (-not $imaj) {
        $imaj = 'debian:12-slim'
        Set-Adim $id @{ mesaj = 'Küçük bir deneme kabı indiriyorum.' }
        $pl = Invoke-Komut 'docker' @('pull', $imaj) 600
        if ($pl.Kod -ne 0) { Write-Log ('docker pull hatasi: ' + ([string]$pl.Hata).Trim()) }
    }
    $t = Invoke-Komut 'docker' @('run', '--rm', '--gpus', 'all', $imaj, 'nvidia-smi', '-L') 300
    Write-Log ('Docker GPU denemesi (' + $imaj + ') kodu ' + $t.Kod + ': ' + ([string]$t.Cikti).Trim() + ' ' + ([string]$t.Hata).Trim())
    if ($t.Kod -ne 0) {
        $yap = "1. Ekran kartı sürücünü güncelle.`n2. PowerShell'i aç ve 'wsl --update' yaz, Enter'a bas.`n3. Docker Desktop > Settings > General'da 'Use the WSL 2 based engine' açık olsun.`n4. Docker Desktop'ı kapatıp yeniden aç, sonra Tekrar dene'ye bas."
        return New-Sonuc 'kullanici' '' 'Docker ekran kartını göremiyor; ekran kartı olmadan arama çok yavaş kalır.' $yap
    }

    return New-Sonuc 'tamam' ('Her şey hazır. Ekran kartın: ' + $gpuAdi + '.')
}

# --- 2. Tanitim videosu ----------------------------------------------------------------------

function Adim-Video {
    $id = 'video'
    Set-Adim $id @{ mesaj = 'Videonun burada olup olmadığına bakıyorum.' } -GunlukGuncelle
    if (Test-RepoVideo) {
        Write-Log 'Video repoda hazir; indirme yok.'
        return New-Sonuc 'tamam' 'Video hazır; beklerken izleyebilirsin.'
    }
    $rk = Get-ReleaseVeKimlik
    if ($rk.Neden -ne 'tamam') {
        Write-Log ('Video atlandi: ' + $rk.Neden + ' (http ' + $rk.Http + ')')
        return New-Sonuc 'atlandi' 'Bu sefer video yok; kurulum bundan etkilenmiyor.'
    }
    $asset = @($rk.Release.assets | Where-Object { $_.name -eq $script:Sabit.video_dosya }) | Select-Object -First 1
    if (-not $asset) {
        Write-Log 'Release icinde video dosyasi yok.'
        return New-Sonuc 'atlandi' 'Bu sefer video yok; kurulum bundan etkilenmiyor.'
    }
    $anlatim = @($rk.Release.assets | Where-Object { $_.name -eq $script:Sabit.anlatim_dosya }) | Select-Object -First 1
    if ($anlatim) {
        $null = Save-ReleaseDosya -Token $rk.Token -Asset $anlatim -Hedef (Join-Path $script:MedyaDir $script:Sabit.anlatim_dosya) -Tik $null
    }
    Start-Ilerleme $id ([int64]$asset.size)
    Set-Adim $id @{ mesaj = 'Videoyu indiriyorum.'; toplam = [int64]$asset.size; bayt = 0; yuzde = 0 }
    $hedef = Join-Path $script:MedyaDir $script:Sabit.video_dosya
    $tamam = Save-ReleaseDosya -Token $rk.Token -Asset $asset -Hedef $hedef -Tik { param($b) Update-Ilerleme $b }
    if (-not $tamam) {
        return New-Sonuc 'atlandi' 'Video inmedi; kurulum bundan etkilenmiyor.'
    }
    return New-Sonuc 'tamam' 'Video hazır; sayfada izleyebilirsin.'
}

# --- 3. Dil modeli (Gemini / Claude / yerel model) ----------------------------------------------

function New-EnvDosyasi {
    $ornek = Join-Path $script:Kok 'app\.env.example'
    $satirlar = @()
    if (Test-Path $ornek) { $satirlar = @([System.IO.File]::ReadAllLines($ornek, $script:Utf8)) }
    $veri = (Join-Path $script:Kok 'veri') -replace '\\', '/'
    $modeller = (Join-Path $script:Kok 'modeller') -replace '\\', '/'
    foreach ($d in @($veri, $modeller)) { if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null } }
    $degerler = [ordered]@{
        DJANGO_SECRET_KEY = (New-Rastgele 50)
        DJANGO_ALLOWED_HOSTS = 'localhost,127.0.0.1,backend'
        DJANGO_DB_NAME = 'reelsift'
        DJANGO_DB_USER = 'reelsift'
        DJANGO_DB_PASSWORD = (New-Rastgele 24)
        DATA_DIR = $veri
        MODELS_DIR = $modeller
        LLM_PROVIDER = 'gemini'
        GEMINI_MODEL = $script:Sabit.gemini.model
        GEMINI_RPM = [string]$script:Sabit.gemini.rpm
    }
    $cikti = @()
    $kullanilan = @{}
    foreach ($s in $satirlar) {
        $yazildi = $false
        foreach ($k in $degerler.Keys) {
            if ($s -cmatch ('^' + $k + '=')) { $cikti += ($k + '=' + $degerler[$k]); $kullanilan[$k] = $true; $yazildi = $true; break }
        }
        if (-not $yazildi) { $cikti += $s }
    }
    foreach ($k in $degerler.Keys) { if (-not $kullanilan.ContainsKey($k)) { $cikti += ($k + '=' + $degerler[$k]) } }
    Write-EnvSatirlari $cikti
    Write-Log '.env olusturuldu (degerler yazilmadi).'
}

function Get-SaglayiciIsareti { return (Join-Path $script:DurumDir 'saglayici-secildi') }

# Yerel model secildiyse modelin inmis olmasini saglar (inmemisse Ollama'dan ceker).
function Confirm-YerelModel {
    param([string]$Id)
    $o = $script:Sabit.ollama
    $d = Test-OllamaDurum $o.model
    if (-not $d.Calisiyor) {
        return New-Sonuc 'kullanici' '' 'Ollama şu an çalışmıyor.' ("Ollama'yı aç (kurulu değilse https://ollama.com/download adresinden indirip kur), sonra Tekrar dene'ye bas.") ([pscustomobject]@{ ad = "Ollama'yı indir"; url = 'https://ollama.com/download' })
    }
    if ($d.ModelVar) { return New-Sonuc 'tamam' 'Yerel model hazır.' }
    Start-Ilerleme $Id ([int64]$o.model_boyut_bayt)
    Set-Adim $Id @{ durum = 'suruyor'; mesaj = ('Yerel modeli indiriyorum (' + $o.model + '); birkaç dakika sürebilir.'); toplam = [int64]$o.model_boyut_bayt; bayt = 0; yuzde = 0 }
    $akis = Join-Path $script:DurumDir 'ollama-pull.log'
    $tik = {
        param($satir)
        if ($satir -cmatch '"completed"\s*:\s*(\d+)') { Update-Ilerleme ([int64]$Matches[1]) }
    }
    $tamam = Save-OllamaModel -Model $o.model -AkisDosyasi $akis -Tik $tik
    if (-not $tamam) {
        return New-Sonuc 'hata' '' 'Yerel model indirilemedi.' ("İnternet bağlantını ve Ollama'nın açık olduğunu kontrol edip Tekrar dene'ye bas; indirme kaldığı yerden devam eder. Yine olursa: " + (Get-ClaudeCumlesi 'Dil modeli'))
    }
    Set-Adim $Id @{ bayt = [int64]$o.model_boyut_bayt; toplam = [int64]$o.model_boyut_bayt; yuzde = 100 }
    return New-Sonuc 'tamam' 'Yerel model indi ve hazır.'
}

function Adim-Anahtar {
    $id = 'anahtar'
    Set-Adim $id @{ mesaj = 'Ayar dosyasını hazırlıyorum.' } -GunlukGuncelle
    if (-not (Test-Path (Get-EnvYolu))) { New-EnvDosyasi }
    # Eski / elle yazilmis .env'de gerekli satirlar yoksa tamamla.
    if (-not (Read-EnvDeger 'LLM_PROVIDER')) { Set-EnvDeger 'LLM_PROVIDER' 'gemini' }
    if (-not (Read-EnvDeger 'GEMINI_MODEL')) { Set-EnvDeger 'GEMINI_MODEL' $script:Sabit.gemini.model }
    if (-not (Read-EnvDeger 'GEMINI_RPM')) { Set-EnvDeger 'GEMINI_RPM' ([string]$script:Sabit.gemini.rpm) }
    foreach ($d in @((Join-Path $script:Kok 'veri'), (Join-Path $script:Kok 'modeller'))) {
        if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
    }

    $isaret = Get-SaglayiciIsareti
    $secilen = $null
    # Kullanici onceden secim yapmis ve adim yarida kalmissa (ornegin model indirmesi) secim korunur.
    if (Test-Path $isaret) { $secilen = ([string](Read-MetinDosya $isaret)).Trim() }

    if (-not $secilen) {
        $saglayici = Read-EnvDeger 'LLM_PROVIDER'
        if ($saglayici -ceq 'gemini') {
            $var = Read-EnvDeger 'GEMINI_API_KEY'
            if ($var) {
                $t = Test-GeminiAnahtar $var
                if ($t.Tamam) { return New-Sonuc 'tamam' 'Gemini anahtarı zaten kayıtlı ve çalışıyor.' }
                if ($t.Neden -eq 'ag') {
                    return New-Sonuc 'kullanici' '' $t.Mesaj "İnternetini kontrol edip Tekrar dene'ye bas."
                }
                Write-Log 'Kayitli anahtar kabul edilmedi; yenisi isteniyor.'
                Set-EnvDeger 'GEMINI_API_KEY' ''
            }
        } elseif ($saglayici -ceq 'anthropic') {
            $var = Read-EnvDeger 'ANTHROPIC_API_KEY'
            if ($var) {
                $t = Test-AnthropicAnahtar $var
                if ($t.Tamam) { return New-Sonuc 'tamam' 'Claude anahtarı zaten kayıtlı ve çalışıyor.' }
                if ($t.Neden -eq 'ag') {
                    return New-Sonuc 'kullanici' '' $t.Mesaj "İnternetini kontrol edip Tekrar dene'ye bas."
                }
                Write-Log 'Kayitli Claude anahtari kabul edilmedi; yenisi isteniyor.'
                Set-EnvDeger 'ANTHROPIC_API_KEY' ''
            }
        }
        Set-Adim $id @{ durum = 'kullanici'; mesaj = 'Dil modelini seçmeni bekliyorum.' }
        $sinir = (Get-Date).AddHours(8)
        while ((Get-Date) -lt $sinir) {
            Start-Sleep -Milliseconds 1500
            if (Test-Path $isaret) { $secilen = ([string](Read-MetinDosya $isaret)).Trim() }
            if ($secilen) { break }
        }
        if (-not $secilen) {
            return New-Sonuc 'hata' '' 'Dil modeli seçimi uzun süre gelmedi.' "Tekrar dene'ye basıp bir seçenek seç."
        }
    }

    Set-Adim $id @{ durum = 'suruyor'; mesaj = 'Seçimini aldım.' }
    if ($secilen -ceq 'ollama') { return (Confirm-YerelModel $id) }
    if ($secilen -ceq 'anthropic') { return New-Sonuc 'tamam' 'Claude anahtarı kaydedildi ve çalışıyor.' }
    return New-Sonuc 'tamam' 'Gemini anahtarı kaydedildi ve çalışıyor.'
}

# --- 4. Film arsivi --------------------------------------------------------------------------

function Get-ArsivYolu { return (Join-Path $script:IndirmeDir $script:Sabit.yedek_dosya) }

function Adim-Arsiv {
    $id = 'arsiv'
    $adim = 'Film arşivi'
    Set-Adim $id @{ mesaj = 'GitHub''a bağlanıyorum.' } -GunlukGuncelle
    $hedef = Get-ArsivYolu
    $rk = Get-ReleaseVeKimlik
    if ($rk.Neden -ne 'tamam') {
        if ($rk.Http -eq 404) {
            return New-Sonuc 'hata' '' 'Film arşivi (veri paketi) GitHub''da bulunamadı.' "Proje sahibine 'veri paketi görünmüyor' diye haber ver; sonra Tekrar dene'ye bas."
        }
        if ($rk.Http -eq 401 -or $rk.Http -eq 403) {
            return New-Sonuc 'hata' '' 'GitHub şu an arşive izin vermedi (çok sık istek ya da erişim kısıtı olabilir).' ("Birkaç dakika bekleyip Tekrar dene'ye bas. Yine olursa: " + (Get-ClaudeCumlesi $adim))
        }
        return New-Sonuc 'hata' '' "GitHub'a şu an ulaşamadım." "İnternet bağlantını kontrol edip Tekrar dene'ye bas."
    }
    $asset = @($rk.Release.assets | Where-Object { $_.name -eq $script:Sabit.yedek_dosya }) | Select-Object -First 1
    if (-not $asset) {
        return New-Sonuc 'hata' '' 'Veri paketinde film arşivi dosyası yok.' "Proje sahibine 'veri paketinde arşiv dosyası yok' diye haber ver."
    }
    $boyut = [int64]$asset.size
    $indir = {
        Start-Ilerleme $id $boyut
        Set-Adim $id @{ mesaj = 'Film arşivini indiriyorum.'; toplam = $boyut; bayt = 0; yuzde = 0; kalan_sn = $null }
        return (Save-ReleaseDosya -Token $rk.Token -Asset $asset -Hedef $hedef -Tik { param($b) Update-Ilerleme $b })
    }
    $bildir = {
        Set-Adim $id @{ mesaj = 'İndirilen dosyayı kontrol ediyorum.'; yuzde = $null; bayt = $null; toplam = $null; kalan_sn = $null } -GunlukGuncelle
    }
    $sonuc = Confirm-DosyaOzeti -Yol $hedef -Beklenen $script:Sabit.yedek_sha256 -BeklenenBoyut ([int64]$script:Sabit.yedek_boyut_bayt) -Indir $indir -Bildir $bildir
    if ($sonuc -eq 'indirme') {
        return New-Sonuc 'hata' '' 'İndirme yarıda kesildi.' "İnternet bağlantını kontrol edip Tekrar dene'ye bas; indirme kaldığı yerden devam eder."
    }
    if ($sonuc -eq 'bozuk') {
        return New-Sonuc 'hata' '' 'İndirilen dosya bozuk çıktı.' 'İnternet bağlantını kontrol edip tekrar dene.'
    }
    Set-Adim $id @{ bayt = $boyut; toplam = $boyut; yuzde = 100 }
    return New-Sonuc 'tamam' 'Film arşivi indi ve doğrulandı.'
}

# --- 5. Uygulamanin hazirlanmasi (docker compose build) --------------------------------------

function Adim-Uygulama {
    $id = 'uygulama'
    $log = Get-AdimLogu $id
    $t0 = Get-Date
    Set-Adim $id @{ mesaj = 'Başlıyorum.'; yuzde = $null } -GunlukGuncelle
    $tik = {
        $son = Get-DosyaSonSatirlar $log 40
        $katman = ''
        foreach ($s in $son) { if ($s -match '^#\d+\s+\[') { $katman = $s } }
        $m = 'Hazırlık sürüyor.'
        if ($katman) {
            $katman = ($katman -replace '^#\d+\s+', '')
            if ($katman.Length -gt 70) { $katman = $katman.Substring(0, 70) }
            $m = 'Şu an: ' + $katman
        }
        Set-Adim $id @{ mesaj = $m } -GunlukGuncelle
    }
    $kod = Invoke-DockerLog 'compose --progress=plain build' $log $tik 3000
    if ($kod -ne 0) {
        return New-Sonuc 'hata' '' 'Uygulamayı hazırlarken bir sorun çıktı (genelde internet kesintisi ya da disk dolması).' "İnternetini ve diskteki boş yeri kontrol edip Tekrar dene'ye bas. Yine olursa: $(Get-ClaudeCumlesi 'Uygulamanın hazırlanması')"
    }
    return New-Sonuc 'tamam' 'Uygulama ortamı hazır.'
}

# --- 6. Arama modelleri ----------------------------------------------------------------------

# Modellerin tam oldugu KONTEYNER ICINDE dogrulanir (adimlar\model_indir.py); sonuc modeller\hazir.json'a yazilir.
# Windows tarafinda snapshot altindaki Linux baglari 0 bayt gorunur: dosya boyutlarina GUVENILMEZ, yalniz bu isaret dosyasina bakilir.
function Test-ModellerHazir {
    $f = Join-Path $script:Kok 'modeller\hazir.json'
    $h = Read-JsonDosya $f
    if (-not $h -or -not $h.modeller) { return $false }
    foreach ($b in @($script:Sabit.modeller)) {
        $m = @($h.modeller | Where-Object { $_.model -ceq $b.model -and $_.surum -ceq $b.surum }) | Select-Object -First 1
        if (-not $m) { return $false }
        if ([int]$m.dosya_sayisi -ne [int]$b.dosya_sayisi -or [int64]$m.bayt -le 0) { return $false }
    }
    return $true
}

# Indirilen gercek bayt: modeller\ altindaki dosyalar (yarim .incomplete dahil, simgesel baglar HARIC) ile
# konteynerin gunluge yazdigi ILERLEME satirindan buyuk olani (bind mount'ta buyuyen dosya Windows'ta gec gorunebilir).
function Get-ModelBayt([string]$Log) {
    $bayt = [int64]0
    $kok = Join-Path $script:Kok 'modeller'
    if (Test-Path $kok) {
        $dosyalar = Get-ChildItem -LiteralPath $kok -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object { -not ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -and $_.Name -cne 'hazir.json' }
        $olc = $dosyalar | Measure-Object -Property Length -Sum
        if ($olc.Sum) { $bayt = [int64]$olc.Sum }
    }
    foreach ($s in (Get-DosyaSonSatirlar $Log 6)) {
        if ($s -cmatch '^ILERLEME (\d+)\s*$') {
            $k = [int64]$Matches[1]
            if ($k -gt $bayt) { $bayt = $k }
        }
    }
    return $bayt
}

function Adim-Modeller {
    $id = 'modeller'
    $adim = 'Arama modelleri'
    $toplam = [int64]$script:Sabit.modeller_toplam_bayt
    Set-Adim $id @{ mesaj = 'Modeller zaten inmiş mi bakıyorum.' } -GunlukGuncelle
    if (Test-ModellerHazir) { return New-Sonuc 'tamam' 'Modeller zaten inmiş ve doğrulanmış.' }
    if (-not (Test-Path (Join-Path $script:Kok 'modeller'))) { New-Item -ItemType Directory -Force -Path (Join-Path $script:Kok 'modeller') | Out-Null }
    $log = Get-AdimLogu $id
    Start-Ilerleme $id $toplam
    Set-Adim $id @{ mesaj = 'Modelleri indiriyorum (daha önce inmiş dosyalar varsa yalnızca doğruluyorum).'; toplam = $toplam; bayt = 0; yuzde = 0 }
    $adimKlasoru = ((Join-Path $script:KurulumDir 'adimlar') -replace '\\', '/')
    $tik = {
        Update-Ilerleme (Get-ModelBayt $log)
        $script:GecerliLog = $log
        Set-Adim $id @{} -GunlukGuncelle
    }
    # --no-deps: model indirme veritabanina ihtiyac duymaz; db'yi ilk kez (bos volume) baslatip sagligini beklemesin.
    $arg = 'compose run --rm --no-deps -T -e HF_HUB_OFFLINE=0 -e HF_HUB_DISABLE_XET=1 -e SEARCH_WARMUP=0 -v "' + $adimKlasoru + ':/kurulum:ro" backend python -I /kurulum/model_indir.py'
    $kod = Invoke-DockerLog $arg $log $tik 3000
    $metin = ''
    if (Test-Path $log) { $metin = [string](Read-MetinDosya $log) }
    $hazir = Test-ModellerHazir
    if ($kod -eq 0 -and $hazir) {
        Set-Adim $id @{ bayt = $toplam; toplam = $toplam; yuzde = 100 }
        return New-Sonuc 'tamam' 'Modeller indi ve doğrulandı.'
    }
    Write-Log ('model_indir cikis kodu ' + $kod + '; hazir.json ' + $hazir)
    if ($metin -cmatch 'unhealthy|dependency failed') {
        return New-Sonuc 'hata' '' 'Veritabanı açılamadı.' ("Docker Desktop'ın açık olduğundan emin olup Tekrar dene'ye bas. Yine olursa: " + (Get-ClaudeCumlesi $adim))
    }
    if ($metin -cmatch 'Cannot connect to the Docker daemon|error during connect|failed to connect to the docker API') {
        return New-Sonuc 'hata' '' 'Docker şu an cevap vermiyor.' "Docker Desktop'ı açıp 'Engine running' yazmasını bekle, sonra Tekrar dene'ye bas."
    }
    if ($kod -eq 2) {
        return New-Sonuc 'hata' '' 'Modellerin indirilmesi yarıda kesildi (internet ya da Hugging Face tarafı).' "İnternet bağlantını kontrol edip Tekrar dene'ye bas; indirme kaldığı yerden devam eder."
    }
    if ($kod -eq 1 -or ($kod -eq 0 -and -not $hazir)) {
        return New-Sonuc 'hata' '' 'Modeller indi ama doğrulanamadı (bazı dosyalar eksik ya da yarım).' "Tekrar dene'ye bas; eksik dosyalar yeniden indirilir. Yine olursa: $(Get-ClaudeCumlesi $adim)"
    }
    return New-Sonuc 'hata' '' 'Modeller indirilemedi.' "Tekrar dene'ye bas. Yine olursa: $(Get-ClaudeCumlesi $adim)"
}

# --- 7. Arsivin yuklenmesi -------------------------------------------------------------------

function Adim-Yukleme {
    $id = 'yukleme'
    $adim = 'Arşivin yüklenmesi'
    $log = Get-AdimLogu $id
    Set-Adim $id @{ mesaj = 'Veritabanını açıyorum.'; yuzde = $null } -GunlukGuncelle
    $kod = Invoke-DockerLog 'compose up -d db' $log $null
    if ($kod -ne 0) {
        return New-Sonuc 'hata' '' 'Veritabanı açılamadı.' "Docker Desktop'ın açık olduğundan emin olup Tekrar dene'ye bas. Yine olursa: $(Get-ClaudeCumlesi $adim)"
    }
    $cid = Get-DbKonteyner
    if (-not $cid) { return New-Sonuc 'hata' '' 'Veritabanı kabını bulamadım.' (Get-ClaudeCumlesi $adim) }

    # Bos volume ile ilk acilis (initdb) compose'un saglik denetimi suresine sigmayabilir; burada en cok 5 dk beklenir.
    # TCP uzerinden (-h 127.0.0.1) sorulur: initdb'nin gecici sunucusu yalnizca unix soketinde dinler, onu "hazir" saymamak icin.
    $saglikli = $false
    $bekleBasi = Get-Date
    while ((((Get-Date) - $bekleBasi).TotalSeconds) -lt 300) {
        $h = Invoke-Komut 'docker' @('exec', $cid, 'sh', '-c', 'pg_isready -h 127.0.0.1 -U $POSTGRES_USER -d $POSTGRES_DB') 30
        if ($h.Kod -eq 0) { $saglikli = $true; break }
        $sn = [int](((Get-Date) - $bekleBasi).TotalSeconds)
        Set-Adim $id @{ mesaj = ('Veritabanı ilk kez açılıyor, hazır olmasını bekliyorum (' + $sn + ' sn). İlk açılış birkaç dakika sürebilir.') } -GunlukGuncelle
        Start-Sleep -Seconds 4
    }
    if (-not $saglikli) {
        return New-Sonuc 'hata' '' 'Veritabanı 5 dakikada açılmadı.' "Tekrar dene'ye bas. Yine olursa: $(Get-ClaudeCumlesi $adim)"
    }

    # Kurulu bir sistemin uzerine yazmayi onle: sohbet tablosunda kayit varsa arsiv zaten yuklenmistir.
    $tabloVar = Invoke-Sql $cid "select to_regclass('public.chats_chat') is not null;"
    if ($tabloVar.Kod -ne 0) {
        return New-Sonuc 'hata' '' 'Veritabanına soru soramadım.' "Tekrar dene'ye bas. Yine olursa: $(Get-ClaudeCumlesi $adim)"
    }
    $sohbet = 0
    if (([string]$tabloVar.Cikti).Trim() -eq 't') {
        $sorgu = Invoke-Sql $cid 'select count(*) from chats_chat;'
        if ($sorgu.Kod -ne 0) {
            return New-Sonuc 'hata' '' 'Veritabanına soru soramadım.' "Tekrar dene'ye bas. Yine olursa: $(Get-ClaudeCumlesi $adim)"
        }
        [int]::TryParse(([string]$sorgu.Cikti).Trim(), [ref]$sohbet) | Out-Null
    }
    if ($sohbet -gt 0) {
        Write-Log 'Veritabaninda sohbet kayitlari var; arsiv yeniden yuklenmeyecek.'
        return New-Sonuc 'tamam' 'Arşiv zaten yüklü (üzerine yazmadım).'
    }

    $dump = Get-ArsivYolu
    if (-not (Test-Path $dump)) {
        return New-Sonuc 'hata' '' 'İndirilen film arşivi dosyasını bulamadım.' "Önceki 'Film arşivi' adımını yeniden çalıştırmak gerekiyor: $(Get-ClaudeCumlesi $adim)"
    }
    Set-Adim $id @{ mesaj = 'Eski yarım kalmış izleri temizliyorum.' } -GunlukGuncelle
    $tem = Invoke-Sql $cid 'drop schema public cascade; create schema public;'
    if ($tem.Kod -ne 0) { Write-Log ('Sema temizleme hatasi: ' + ([string]$tem.Hata).Trim()) }

    Set-Adim $id @{ mesaj = 'Arşivi veritabanı kabına taşıyorum.' } -GunlukGuncelle
    $kod = Invoke-DockerLog ('cp "' + $dump + '" ' + $cid + ':/tmp/reelsift-veri.dump') $log $null
    if ($kod -ne 0) {
        return New-Sonuc 'hata' '' 'Arşivi veritabanına taşıyamadım (disk dolmuş olabilir).' "Diskte yer açıp Tekrar dene'ye bas."
    }

    $t0 = Get-Date
    $tik = {
        $dk = [int](((Get-Date) - $t0).TotalMinutes)
        Set-Adim $id @{ mesaj = ('Film verisini yerleştiriyorum ve arama indekslerini kuruyorum (' + $dk + ' dakikadır sürüyor; bu adım uzun sürer).') } -GunlukGuncelle
    }
    $restore = 'exec ' + $cid + ' sh -c "PGOPTIONS=''-c maintenance_work_mem=1GB'' pg_restore -U $POSTGRES_USER -d $POSTGRES_DB --no-owner --no-acl /tmp/reelsift-veri.dump"'
    $kod = Invoke-DockerLog $restore $log $tik 5000
    Write-Log ('pg_restore cikis kodu ' + $kod + ' (sifirdan baska bir sey, veri sayimiyla dogrulanir)')

    Set-Adim $id @{ mesaj = 'Yüklenen veriyi kontrol ediyorum.' } -GunlukGuncelle
    $film = Invoke-Sql $cid 'select count(*) from films_film;'
    $parca = Invoke-Sql $cid 'select count(*) from films_filmchunk;'
    $indeks = Invoke-Sql $cid "select count(*) from pg_indexes where indexname in ('films_filmchunk_hnsw', 'films_film_card_hnsw');"
    $nf = 0; $np = 0; $ni = 0
    [int]::TryParse(([string]$film.Cikti).Trim(), [ref]$nf) | Out-Null
    [int]::TryParse(([string]$parca.Cikti).Trim(), [ref]$np) | Out-Null
    [int]::TryParse(([string]$indeks.Cikti).Trim(), [ref]$ni) | Out-Null
    Write-Log ('Dogrulama: film ' + $nf + ', parca ' + $np + ', hnsw indeks ' + $ni)
    if ($nf -lt 50000 -or $np -lt 1 -or $ni -lt 2) {
        return New-Sonuc 'hata' '' 'Film arşivi veritabanına tam yerleşmedi.' "Tekrar dene'ye bas (baştan yüklenir). Yine olursa: $(Get-ClaudeCumlesi $adim)"
    }

    Set-Adim $id @{ mesaj = 'Veritabanı düzenini güncelliyorum.' } -GunlukGuncelle
    $kod = Invoke-DockerLog 'compose run --rm -T -e SEARCH_WARMUP=0 backend python manage.py migrate --noinput' $log $null
    if ($kod -ne 0) {
        return New-Sonuc 'hata' '' 'Veritabanı düzenini güncelleyemedim.' "Tekrar dene'ye bas. Yine olursa: $(Get-ClaudeCumlesi $adim)"
    }

    $null = Invoke-Komut 'docker' @('exec', $cid, 'rm', '-f', '/tmp/reelsift-veri.dump') 60
    try { Remove-Item -Force $dump -ErrorAction SilentlyContinue } catch {}
    return New-Sonuc 'tamam' 'Film arşivi yüklendi.'
}

# --- 8. Arama dizini -------------------------------------------------------------------------
# Karar: dizin yerinde kurulur (kod: apps/search/services/lexical.py build_index; ~1,5 dk), arsive konmaz.

function Adim-Dizin {
    $id = 'dizin'
    $log = Get-AdimLogu $id
    Set-Adim $id @{ mesaj = 'Dizini kuruyorum; birkaç dakika sürebilir.'; yuzde = $null } -GunlukGuncelle
    $tik = { Set-Adim $id @{} -GunlukGuncelle }
    $kod = Invoke-DockerLog 'compose run --rm -T -e SEARCH_WARMUP=0 backend python manage.py build_search_index' $log $tik 4000
    if ($kod -ne 0) {
        return New-Sonuc 'hata' '' 'Arama dizinini kuramadım.' "Tekrar dene'ye bas. Yine olursa: $(Get-ClaudeCumlesi 'Arama dizini')"
    }
    return New-Sonuc 'tamam' 'Arama dizini hazır.'
}

# --- 9. Kullanici ----------------------------------------------------------------------------

function Adim-Kullanici {
    $id = 'kullanici'
    $log = Get-AdimLogu $id
    Set-Adim $id @{ mesaj = 'Hesabını açıyorum.' } -GunlukGuncelle
    # Sifre bu kurulumda rastgele uretilir ve yalniz kurulum\.durum\hesap.json'da (git disinda) tutulur.
    # Adim yeniden denenirse ayni sifre kullanilir.
    $hesap = Get-Hesap
    if (-not $hesap) {
        $hesap = [pscustomobject]@{ kullanici = [string]$script:Sabit.kimlik.kullanici; sifre = (New-Parola 14) }
        Write-MetinAtomik (Get-HesapYolu) (ConvertTo-Json -InputObject $hesap -Compress) -Zorunlu
    }
    $adimKlasoru = ((Join-Path $script:KurulumDir 'adimlar') -replace '\\', '/')
    # Degerler komut satirina yazilmaz: -e AD (degersiz) ortam degiskenini bu surecten alir.
    $env:KURULUM_KULLANICI = $hesap.kullanici
    $env:KURULUM_SIFRE = $hesap.sifre
    try {
        $arg = 'compose run --rm -T -e SEARCH_WARMUP=0 -e KURULUM_KULLANICI -e KURULUM_SIFRE -v "' + $adimKlasoru + ':/kurulum:ro" backend python manage.py shell -c "exec(open(''/kurulum/kullanici.py'').read())"'
        $kod = Invoke-DockerLog $arg $log $null
    } finally {
        Remove-Item Env:\KURULUM_KULLANICI -ErrorAction SilentlyContinue
        Remove-Item Env:\KURULUM_SIFRE -ErrorAction SilentlyContinue
    }
    $metin = ''
    if (Test-Path $log) { $metin = [string](Read-MetinDosya $log) }
    if ($kod -ne 0 -or $metin -cnotmatch 'KULLANICI_TAMAM') {
        return New-Sonuc 'hata' '' 'Hesabını açamadım.' "Tekrar dene'ye bas. Yine olursa: $(Get-ClaudeCumlesi 'Kullanıcı')"
    }
    return New-Sonuc 'tamam' ("Hesabın hazır: " + $hesap.kullanici)
}

# --- 10. Baslatma ----------------------------------------------------------------------------

function Adim-Baslatma {
    $id = 'baslatma'
    $adim = 'Başlatma'
    $log = Get-AdimLogu $id
    Set-Adim $id @{ mesaj = 'Uygulamayı başlatıyorum.'; yuzde = $null } -GunlukGuncelle
    $kod = Invoke-DockerLog 'compose up -d' $log $null
    if ($kod -ne 0) {
        return New-Sonuc 'hata' '' 'Uygulama başlamadı.' "Tekrar dene'ye bas. Yine olursa: $(Get-ClaudeCumlesi $adim)"
    }
    $sinir = (Get-Date).AddMinutes(20)
    $saglikli = $false
    $hazir = $false
    while ((Get-Date) -lt $sinir) {
        if (-not $saglikli) {
            $r = Invoke-Curl -Argumanlar @('-m', '10', '-o', 'NUL', '-w', '%{http_code}', $script:Sabit.adresler.saglik)
            if (([string]$r.Cikti).Trim() -eq '200') { $saglikli = $true }
        }
        if ($saglikli) {
            Set-Adim $id @{ mesaj = 'Uygulama açıldı; arama modelleri ısınıyor (2-4 dakika).' } -GunlukGuncelle
            $l = Invoke-Komut 'docker' @('compose', 'logs', '--no-color', '--tail', '400', 'backend') 40 $null $script:Kok
            $metin = [string]$l.Cikti
            if ($metin -cmatch 'Arama hazır') { $hazir = $true; break }
            if ($metin -cmatch 'Arama ısındırması başarısız') {
                return New-Sonuc 'hata' '' 'Arama modelleri ısınamadı.' "Tekrar dene'ye bas. Yine olursa: $(Get-ClaudeCumlesi $adim)"
            }
        } else {
            Set-Adim $id @{ mesaj = 'Uygulamanın açılmasını bekliyorum.' } -GunlukGuncelle
        }
        Start-Sleep -Seconds 6
    }
    if (-not $hazir) {
        return New-Sonuc 'hata' '' 'Uygulama beklediğimden uzun sürdü.' "Tekrar dene'ye bas; bilgisayar yoğunsa birkaç dakika bekleyip bir daha dene."
    }
    return New-Sonuc 'tamam' 'Uygulama ve arama hazır.'
}

# --- 11. Son kontrol -------------------------------------------------------------------------

function Adim-Son {
    $id = 'son'
    $adim = 'Son kontrol'
    $api = $script:Sabit.adresler.giris_api
    $jar = Join-Path $script:DurumDir 'cj.txt'
    if (Test-Path $jar) { Remove-Item -Force $jar }
    Set-Adim $id @{ mesaj = 'Giriş deniyorum.' } -GunlukGuncelle
    try {
        $null = Invoke-Curl -Argumanlar @('-m', '20', '-c', $jar, '-b', $jar, '-o', 'NUL', ($api + '/auth/me'))
        $csrf = ''
        if (Test-Path $jar) {
            foreach ($satir in [System.IO.File]::ReadAllLines($jar)) {
                if ($satir -match 'csrftoken\s+(\S+)\s*$') { $csrf = $Matches[1] }
            }
        }
        if (-not $csrf) {
            return New-Sonuc 'hata' '' 'Uygulama giriş için gerekli çerezi vermedi.' ("Tekrar dene'ye bas. Yine olursa: " + (Get-ClaudeCumlesi $adim))
        }
        $hesap = Get-Hesap
        if (-not $hesap) {
            return New-Sonuc 'hata' '' 'Hesap bilgisi bulunamadı.' "Tekrar dene'ye basıp 'Kullanıcı' adımını yeniden yap; gerekirse: $(Get-ClaudeCumlesi 'Kullanıcı')"
        }
        $govde = ConvertTo-Json -InputObject @{ username = [string]$hesap.kullanici; password = [string]$hesap.sifre } -Compress
        $r = Invoke-Curl -Argumanlar @('-m', '30', '-c', $jar, '-b', $jar, '-X', 'POST', '-H', 'Content-Type: application/json', '-H', ('X-CSRFToken: ' + $csrf), '-H', ('Origin: ' + $script:Sabit.adresler.uygulama), '-d', $govde, '-o', 'NUL', '-w', '%{http_code}', ($api + '/auth/login'))
        $http = ([string]$r.Cikti).Trim()
        Write-Log ('Giris denemesi -> ' + $http)
        if ($http -ne '200') {
            return New-Sonuc 'hata' '' 'Hesabınla giriş yapamadım.' ("Tekrar dene'ye bas. Yine olursa: " + (Get-ClaudeCumlesi $adim))
        }
    } finally {
        if (Test-Path $jar) { Remove-Item -Force $jar }
    }

    $saglayici = Read-EnvDeger 'LLM_PROVIDER'
    if ($saglayici -ceq 'ollama') {
        Set-Adim $id @{ mesaj = 'Yerel modelin hazır olup olmadığına bakıyorum.' } -GunlukGuncelle
        $d = Test-OllamaDurum $script:Sabit.ollama.model
        if (-not $d.Calisiyor) {
            return New-Sonuc 'hata' '' 'Ollama şu an çalışmıyor.' "Ollama'yı açıp Tekrar dene'ye bas (https://ollama.com/download)."
        }
        if (-not $d.ModelVar) {
            return New-Sonuc 'hata' '' 'Yerel model Ollama''da görünmüyor.' "Tekrar dene'ye basıp 'Dil modeli' adımını yeniden yap; gerekirse: $(Get-ClaudeCumlesi 'Dil modeli')"
        }
        return New-Sonuc 'tamam' 'Her şey çalışıyor.'
    }
    if ($saglayici -ceq 'anthropic') {
        Set-Adim $id @{ mesaj = 'Claude anahtarını deniyorum.' } -GunlukGuncelle
        $ak = Read-EnvDeger 'ANTHROPIC_API_KEY'
        if (-not $ak) {
            return New-Sonuc 'hata' '' 'Claude anahtarı kayıtlı görünmüyor.' "Tekrar dene'ye basıp 'Dil modeli' adımını yeniden yap; gerekirse: $(Get-ClaudeCumlesi 'Dil modeli')"
        }
        $t = Test-AnthropicAnahtar $ak
        if (-not $t.Tamam) {
            return New-Sonuc 'hata' '' $t.Mesaj "Tekrar dene'ye bas. Olmazsa 'Dil modeli' adımını yeniden yapıp anahtarı yeniden gir."
        }
        return New-Sonuc 'tamam' 'Her şey çalışıyor.'
    }

    Set-Adim $id @{ mesaj = "Yapay zekâya kısa bir soru soruyorum (anahtar ve kota deneniyor)." } -GunlukGuncelle
    $anahtar = Read-EnvDeger 'GEMINI_API_KEY'
    $model = Read-EnvDeger 'GEMINI_MODEL'
    if (-not $model) { $model = $script:Sabit.gemini.model }
    if (-not $anahtar) {
        return New-Sonuc 'hata' '' 'Gemini anahtarı kayıtlı görünmüyor.' "Tekrar dene'ye basıp 'Dil modeli' adımını yeniden yap; gerekirse: $(Get-ClaudeCumlesi 'Dil modeli')"
    }
    $cfg = 'header = "x-goog-api-key: ' + $anahtar + '"' + "`n"
    $govdeDosya = Join-Path $script:DurumDir 'gemini-deneme.json'
    [System.IO.File]::WriteAllText($govdeDosya, '{"contents":[{"parts":[{"text":"Tek kelimeyle selam ver."}]}],"generationConfig":{"maxOutputTokens":64}}', $script:Utf8)
    $http = 0
    try {
        for ($i = 0; $i -lt 3; $i++) {
            $r = Invoke-Curl -Argumanlar @('-m', '60', '-X', 'POST', '-H', 'Content-Type: application/json', '--data-binary', ('@' + $govdeDosya), '-w', "`n%{http_code}", ('https://generativelanguage.googleapis.com/v1beta/models/' + $model + ':generateContent')) -Yapilandirma $cfg
            $c = Split-HttpCevap $r
            $http = $c.Http
            Write-Log ('Gemini denemesi (' + $model + ') -> ' + $http)
            if ($http -eq 200) { break }
            if ($http -eq 400 -or $http -eq 401 -or $http -eq 403 -or $http -eq 404) { break }
            Start-Sleep -Seconds 6
        }
    } finally {
        if (Test-Path $govdeDosya) { Remove-Item -Force $govdeDosya }
    }
    if ($http -eq 429) {
        return New-Sonuc 'hata' '' "Google'ın ücretsiz kullanım sınırı şu an dolu görünüyor." "Bir iki dakika bekleyip Tekrar dene'ye bas. Her gün sınır yenilenir."
    }
    if ($http -eq 503 -or $http -eq 500 -or $http -eq 0) {
        return New-Sonuc 'hata' '' "Google'ın yapay zekâ servisi şu an yoğun ya da ulaşılamıyor." "Birkaç dakika bekleyip Tekrar dene'ye bas."
    }
    if ($http -ne 200) {
        return New-Sonuc 'hata' '' 'Gemini anahtarın ya da model adı kabul edilmedi.' ("Tekrar dene'ye basıp anahtarı yeniden gir; olmazsa: " + (Get-ClaudeCumlesi $adim))
    }
    return New-Sonuc 'tamam' 'Her şey çalışıyor.'
}
