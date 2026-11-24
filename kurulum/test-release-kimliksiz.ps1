<#
  Kimliksiz Release sorgusu ve indirmesi denemesi (herkese acik bir repoyla; ReelSift reposu degil).
    powershell -NoProfile -ExecutionPolicy Bypass -File kurulum\test-release-kimliksiz.ps1 -Repo sharkdp/hyperfine -Etiket v1.19.0 -Asset hyperfine-v1.19.0-i686-pc-windows-msvc.zip
  Ek olarak var olmayan bir etiketle 404 yolunu ve (saklanan kimlik varsa) kimlikli yeniden denemeyi dener; kimlik yazdirilmaz.
#>
param(
    [string]$Repo = 'sharkdp/hyperfine',
    [string]$Etiket = 'v1.19.0',
    [string]$Asset = 'hyperfine-v1.19.0-i686-pc-windows-msvc.zip'
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'adimlar\ortak.ps1')
. (Join-Path $PSScriptRoot 'adimlar\adimlar.ps1')
$gecici = Join-Path ([System.IO.Path]::GetTempPath()) ('rs-kimliksiz-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $gecici | Out-Null
$kurKlasor = Join-Path $gecici 'kurulum'
New-Item -ItemType Directory -Path $kurKlasor | Out-Null
Copy-Item (Join-Path $PSScriptRoot 'sabitler.json') $kurKlasor
$bitti = 0
try {
    Initialize-Ortam $kurKlasor
    $script:Sabit.repo = $Repo
    $script:Sabit.etiket = $Etiket
    $rk = Get-ReleaseVeKimlik
    Write-Output ('1. kimliksiz sorgu: neden=' + $rk.Neden + ' http=' + $rk.Http + ' kimlik_kullanildi=' + [bool]$rk.Token)
    if ($rk.Neden -ne 'tamam' -or $rk.Token) { throw 'kimliksiz sorgu basarisiz' }
    $a = @($rk.Release.assets | Where-Object { $_.name -ceq $Asset }) | Select-Object -First 1
    if (-not $a) { throw 'asset bulunamadi' }
    $hedef = Join-Path $script:IndirmeDir $Asset
    $ok = Save-ReleaseDosya -Token $rk.Token -Asset $a -Hedef $hedef -Tik $null
    $boyut = 0
    if (Test-Path $hedef) { $boyut = (Get-Item $hedef).Length }
    Write-Output ('2. kimliksiz indirme: ok=' + $ok + ' bayt=' + $boyut + ' beklenen=' + $a.size)
    if (-not $ok -or $boyut -ne [int64]$a.size) { throw 'kimliksiz indirme basarisiz' }

    # 404 yolu: var olmayan etiket; kimlik yoksa hata (Neden=release), varsa bir kez kimlikli denenir.
    $script:ReleaseOnbellek = $null
    $script:Sabit.etiket = 'yok-boyle-bir-etiket-0000'
    $rk2 = Get-ReleaseVeKimlik
    Write-Output ('3. var olmayan etiket: neden=' + $rk2.Neden + ' http=' + $rk2.Http + ' saklanan_kimlik_bulundu=' + $rk2.KimlikVardi)
    if ($rk2.Neden -ne 'release' -or $rk2.Http -ne 404) { throw '404 yolu beklenmedik' }
    $bitti = 1
} finally {
    Remove-Item -Recurse -Force $gecici -ErrorAction SilentlyContinue
}
if ($bitti -eq 1) { Write-Output 'KIMLIKSIZ RELEASE: GECTI'; exit 0 }
exit 1
