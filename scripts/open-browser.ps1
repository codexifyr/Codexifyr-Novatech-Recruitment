param(
    [string]$Url = "http://localhost:3000",
    [int]$TimeoutSeconds = 180
)

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
            Start-Process $Url
            exit 0
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}

Write-Host "NovaTech did not become ready within $TimeoutSeconds seconds."
Write-Host "Check the Backend and Frontend terminal windows for the exact error."
exit 1
