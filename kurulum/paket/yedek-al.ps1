<#
  Temiz veritabani yedegi (pg_dump -Fc) alir. Calisan "db" konteynerinden SALT OKUNUR.
  Film / arama verisi ve migration kayitlari VERIYLE; baska her tablo yalniz SEMA (guvenli varsayilan:
  listede olmayan tablo veri tasimaz). Gizli bilgi okunmaz: veritabani kullanici adi / sifresi
  konteynerin kendi ortam degiskenlerinden konteyner icinde kullanilir.

  Kullanim:  powershell -NoProfile -File kurulum\paket\yedek-al.ps1 -Konteyner <db-konteyner-adi>

  Yeni yedek alinca kurulum\sabitler.json'daki boyut ve SHA256 ozeti de guncellenmeli (kurulum indirdigi
  dosyayi bununla dogrular). Tek komut (docker gerekmez; yedegi ve .sha256 dosyasini okur):
    powershell -NoProfile -File kurulum\paket\yedek-al.ps1 -SadeceSabitler
  (Baska bir yedek yolu icin: -Cikti <yol>.)
#>
param(
    [string]$Konteyner = '',
    [string]$Cikti = 'D:\reelsift-data\yayin\reelsift-veri-2026-11-18.dump',
    [string]$Kok = '',
    [switch]$SadeceSabitler
)
$ErrorActionPreference = 'Stop'

# Veriyle gelecek tablolar (film / arama verisi + migration kayitlari).
$veriyle = @(
    'films_film', 'films_filmchunk', 'films_filmprofile', 'films_filmreview',
    'django_migrations', 'checkpoint_migrations'
)

function Fail([string]$m) { Write-Output ('HATA: ' + $m); exit 1 }

if (-not $Kok) { $Kok = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }

# sabitler.json'daki yedek boyutunu ve SHA256 ozetini yedegin kendisinden / .sha256 dosyasindan gunceller.
function Update-Sabitler {
    $sabit = Join-Path (Split-Path -Parent $PSScriptRoot) 'sabitler.json'
    if (-not (Test-Path $Cikti)) { Fail ('Yedek dosyasi yok: ' + $Cikti) }
    if (-not (Test-Path ($Cikti + '.sha256'))) { Fail ('Ozet dosyasi yok: ' + $Cikti + '.sha256 (yedek-al.ps1 onu da uretir)') }
    $kayitli = (([System.IO.File]::ReadAllText($Cikti + '.sha256').Trim() -split '\s+')[0]).ToLower()
    if ($kayitli -notmatch '^[0-9a-f]{64}$') { Fail 'Ozet dosyasi beklenen bicimde degil.' }
    $gercek = (Get-FileHash -Algorithm SHA256 -LiteralPath $Cikti).Hash.ToLower()
    if ($gercek -ne $kayitli) { Fail 'Yedegin ozeti .sha256 dosyasiyla uyusmuyor; dosya degismis olabilir.' }
    $boyut = (Get-Item $Cikti).Length
    $utf8 = New-Object System.Text.UTF8Encoding $false
    $t = [System.IO.File]::ReadAllText($sabit, $utf8)
    if ($t -notmatch '"yedek_boyut_bayt":\s*\d+' -or $t -notmatch '"yedek_sha256":\s*"[0-9a-f]*"') { Fail 'sabitler.json icinde yedek_boyut_bayt / yedek_sha256 satirlari bulunamadi.' }
    $t = [regex]::Replace($t, '("yedek_boyut_bayt":\s*)\d+', ('${1}' + $boyut))
    $t = [regex]::Replace($t, '("yedek_sha256":\s*")[0-9a-f]*(")', ('${1}' + $gercek + '${2}'))
    [System.IO.File]::WriteAllText($sabit, $t, $utf8)
    Write-Output ('sabitler.json guncellendi: yedek_boyut_bayt=' + $boyut + ' yedek_sha256=' + $gercek)
}

if ($SadeceSabitler) { Update-Sabitler; exit 0 }

if (-not $Konteyner) {
    Push-Location $Kok
    try { $Konteyner = (docker compose ps -q db | Select-Object -First 1) } finally { Pop-Location }
    if (-not $Konteyner) { Fail 'db konteyneri bulunamadi; -Konteyner <ad> ver.' }
}
$null = docker inspect $Konteyner --format '{{.State.Running}}'
if ($LASTEXITCODE -ne 0) { Fail "Konteyner bulunamadi: $Konteyner" }

# Tablo listesi (konteynerin kendi ortami; sifre gerekmez).
$tablolar = "select tablename from pg_tables where schemaname = 'public' order by 1;" | docker exec -i $Konteyner sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -At'
if ($LASTEXITCODE -ne 0 -or -not $tablolar) { Fail 'Tablo listesi alinamadi.' }
$tablolar = @($tablolar | Where-Object { $_ })

$sadeceSema = @($tablolar | Where-Object { $veriyle -notcontains $_ })
$hariç = ($sadeceSema | ForEach-Object { '--exclude-table-data=public.' + $_ }) -join ' '
$eksikVeri = @($veriyle | Where-Object { $tablolar -notcontains $_ })
if ($eksikVeri.Count -gt 0) { Fail ('Veriyle gelmesi beklenen tablo yok: ' + ($eksikVeri -join ', ')) }

Write-Output '--- Tablo siniflandirmasi ---'
foreach ($t in $tablolar) {
    if ($veriyle -contains $t) { Write-Output ('VERIYLE      ' + $t) } else { Write-Output ('YALNIZ SEMA  ' + $t) }
}

$gecici = '/tmp/reelsift-veri.dump'
$komut = 'pg_dump -U $POSTGRES_USER -d $POSTGRES_DB -Fc ' + $hariç + ' -f ' + $gecici
Write-Output '--- pg_dump basliyor ---'
$basla = Get-Date
docker exec $Konteyner sh -c $komut
if ($LASTEXITCODE -ne 0) { Fail 'pg_dump basarisiz.' }
Write-Output ('pg_dump suresi: ' + [int]((Get-Date) - $basla).TotalSeconds + ' sn')

# Icerik dogrulamasi (konteyner icinde, dosya henuz orada).
$toc = docker exec $Konteyner pg_restore -l $gecici
if ($LASTEXITCODE -ne 0) { Fail 'pg_restore -l basarisiz; yedek bozuk olabilir.' }
$veriSatirlari = @($toc | Where-Object { $_ -match 'TABLE DATA public ' })
$veriTablolari = @($veriSatirlari | ForEach-Object { ($_ -split '\s+')[-2] })
Write-Output ('TOC satiri: ' + @($toc).Count + '; TABLE DATA girisi: ' + $veriTablolari.Count)
Write-Output ('Veri giren tablolar: ' + ($veriTablolari -join ', '))
foreach ($t in $sadeceSema) {
    if ($veriTablolari -contains $t) { Fail "Yalniz sema olmasi gereken tabloda veri var: $t" }
}
foreach ($t in $veriyle) {
    if ($veriTablolari -notcontains $t) { Fail "Veri bekleniyordu ama yok: $t" }
}

$klasor = Split-Path -Parent $Cikti
if (-not (Test-Path $klasor)) { New-Item -ItemType Directory -Force -Path $klasor | Out-Null }
if (Test-Path $Cikti) { Remove-Item -Force $Cikti }
docker cp ($Konteyner + ':' + $gecici) $Cikti
if ($LASTEXITCODE -ne 0) { Fail 'docker cp basarisiz.' }
docker exec $Konteyner rm -f $gecici | Out-Null

$boyut = (Get-Item $Cikti).Length
$sinir = 2GB
Write-Output ('Yedek: ' + $Cikti)
Write-Output ('Boyut: ' + $boyut + ' bayt (' + [math]::Round($boyut / 1GB, 3) + ' GiB); GitHub Release dosya siniri 2 GiB: ' + $(if ($boyut -ge $sinir) { 'ASILDI' } else { 'altinda' }))
$ozet = (Get-FileHash -Algorithm SHA256 $Cikti).Hash.ToLower()
Write-Output ('SHA256: ' + $ozet)
[System.IO.File]::WriteAllText(($Cikti + '.sha256'), ($ozet + '  ' + (Split-Path -Leaf $Cikti) + "`n"), (New-Object System.Text.UTF8Encoding $false))
if ($boyut -ge $sinir) { Write-Output 'UYARI: dosya 2 GiB sinirini asiyor; yayin yapma, bolme karari gerekir.'; exit 2 }
Write-Output 'SONRAKI ADIM: kurulumun yeni yedegi dogrulayabilmesi icin sabitler.json guncelle (tek komut):'
Write-Output ('  powershell -NoProfile -File kurulum\paket\yedek-al.ps1 -SadeceSabitler' + $(if ($Cikti -ne 'D:\reelsift-data\yayin\reelsift-veri-2026-11-18.dump') { ' -Cikti "' + $Cikti + '"' } else { '' }))
