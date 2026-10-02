param(
    [string]$EnvFile = ".env",
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Install and start Docker Desktop with Linux containers first."
    }
    if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
        Copy-Item -LiteralPath ".env.compose.example" -Destination $EnvFile
        throw "Created $EnvFile. Fill AWS/S3, Gemini and Modal credentials and replace YOUR_NAME, then rerun."
    }
    $localConfig = @{}
    foreach ($line in Get-Content -LiteralPath $EnvFile) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
            $localConfig[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'")
        }
    }
    $requiredKeys = @("POSTGRES_PASSWORD", "APP_API_KEY", "S3_BUCKET", "S3_KEY_PREFIX",
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "GEMINI_API_KEY", "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET")
    $missingKeys = @($requiredKeys | Where-Object { [string]::IsNullOrWhiteSpace($localConfig[$_]) })
    if ($missingKeys.Count) { throw "Missing configuration keys: $($missingKeys -join ', ')" }
    if ($localConfig["S3_KEY_PREFIX"] -match "YOUR_NAME") { throw "Replace YOUR_NAME in S3_KEY_PREFIX with your own namespace." }
    if ($localConfig["POSTGRES_PASSWORD"] -match '[@:/?#%]') { throw "POSTGRES_PASSWORD must not contain URL-reserved characters (@ : / ? # %)." }
    $composeArgs = @("compose", "--env-file", (Resolve-Path -LiteralPath $EnvFile).Path,
        "-f", "deploy/compose/compose.yaml", "-f", "deploy/compose/compose.dev.yaml",
        "--profile", "test", "--profile", "setup")
    function Invoke-LocalCompose([string[]]$CommandArgs) {
        & docker @composeArgs @CommandArgs
        if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed (exit $LASTEXITCODE)." }
    }
    Invoke-LocalCompose -CommandArgs @("config", "--quiet")
    if ($ValidateOnly) {
        Write-Host "Configuration valid. No containers started and no external AI calls made."
        return
    }
    Invoke-LocalCompose -CommandArgs @("build", "backend")
    Invoke-LocalCompose -CommandArgs @("up", "-d", "--wait", "postgres")
    Invoke-LocalCompose -CommandArgs @("run", "--rm", "--no-deps", "migrate")
    Invoke-LocalCompose -CommandArgs @("run", "--rm", "--no-deps", "rag-init")
    Invoke-LocalCompose -CommandArgs @("up", "-d", "--no-build", "backend", "worker", "streamlit", "test-ui")
    Write-Host "Main UI: http://localhost:8501 | E2E UI: http://localhost:8502 | API docs: http://localhost:8000/docs"
    Write-Host "Upload a short MP4 to start a real analysis (S3/Modal/Gemini charges may apply)."
} finally {
    Pop-Location
}
