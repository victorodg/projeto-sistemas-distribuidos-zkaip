# Orquestra a demonstracao do zKAIP em janelas de terminal separadas, para
# gravacao de tela. Abre a janela da Alice (roda do inicio ao fim), a
# janela do Bob "antes" (roda ate simular uma falha/crash), espera o sinal
# de que a Alice mandou mensagens com o Bob offline, e entao abre uma NOVA
# janela do Bob "depois" (mesma identidade/porta) para mostrar a reconexao
# automatica e a recuperacao das mensagens perdidas.
#
# Uso: abra um PowerShell nesta pasta (demo/) e rode:  .\run_demo.ps1

$ErrorActionPreference = "Stop"
$demoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Split-Path -Parent $demoDir

Write-Host "Limpando estado de execucoes anteriores..."
Remove-Item -Recurse -Force "$demoDir\alice" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "$demoDir\bob" -ErrorAction SilentlyContinue
Remove-Item -Force "$demoDir\.signal_*" -ErrorAction SilentlyContinue

function Start-DemoWindow($title, $dataDir, $port, $username, $script) {
    $cmd = "`$host.ui.RawUI.WindowTitle = '$title'; Set-Location '$demoDir'; python demo_runner.py --data-dir '$dataDir' --port $port --username $username --script '$script'"
    Start-Process powershell -ArgumentList @("-NoExit", "-Command", $cmd)
}

Write-Host "Abrindo janela da Alice..."
Start-DemoWindow "zKAIP - Alice" "$demoDir\alice\data" 6001 "Alice" "$demoDir\script_alice.txt"

Start-Sleep -Seconds 2

Write-Host "Abrindo janela do Bob (antes da falha)..."
Start-DemoWindow "zKAIP - Bob (antes)" "$demoDir\bob\data" 6002 "Bob" "$demoDir\script_bob_before.txt"

$signalFile = "$demoDir\.signal_offline_msgs_sent"
Write-Host "Aguardando a Alice terminar de mandar mensagens com o Bob offline..."
while (-not (Test-Path $signalFile)) {
    Start-Sleep -Milliseconds 500
}
Remove-Item $signalFile -ErrorAction SilentlyContinue

Write-Host "Reabrindo o Bob (reconectando)..."
Start-DemoWindow "zKAIP - Bob (depois)" "$demoDir\bob\data" 6002 "Bob" "$demoDir\script_bob_after.txt"

Write-Host ""
Write-Host "Pronto. As tres janelas continuam abertas ate voce fecha-las manualmente."
Write-Host "Pode comecar a gravacao de tela antes de rodar este script, para capturar tudo."
