[CmdletBinding()]
param(
    [string]$BaseUrl = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    [string]$Model = "qwen-plus",
    [int]$BatchSize = 12
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$collector = Join-Path $PSScriptRoot "collect_event_aware_qwen_responses.py"
$evaluator = Join-Path $PSScriptRoot "evaluate_event_aware_cascade.py"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project Python environment not found: $python"
}

Write-Host "Qwen blind evaluation" -ForegroundColor Cyan
Write-Host "Base URL: $BaseUrl"
Write-Host "Model:    $Model"
Write-Host "The API key is hidden, kept only in this process, and cleared after the run."

$secureKey = Read-Host "Paste the Alibaba Cloud Model Studio API key" -AsSecureString
$keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)

try {
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer).Trim()
    if ([string]::IsNullOrWhiteSpace($plainKey)) {
        throw "API key cannot be empty."
    }
    if ($plainKey.Contains("*")) {
        throw "The pasted value is a masked key. Create or reset the key and copy the full plaintext value from the one-time dialog."
    }
    if (-not $plainKey.StartsWith("sk-")) {
        throw "This does not look like a Model Studio API key (expected a value beginning with sk-)."
    }
    if ($plainKey.StartsWith("sk-sp-")) {
        throw "A Token/Coding Plan key cannot use the pay-as-you-go DashScope endpoint. Create a standard pay-as-you-go Model Studio API key (normally sk-ws-...)."
    }

    $env:LLM_BASE_URL = $BaseUrl
    $env:LLM_MODEL = $Model
    $env:LLM_API_KEY = $plainKey
    $env:LLM_TIMEOUT_SECONDS = "90"
    $env:LLM_MAX_ATTEMPTS = "3"

    Push-Location $projectRoot
    try {
        Write-Host "[1/3] Collecting blind validation predictions..." -ForegroundColor Yellow
        & $python $collector --split validation --batch-size $BatchSize
        if ($LASTEXITCODE -ne 0) {
            throw "Validation collection failed with exit code $LASTEXITCODE."
        }

        Write-Host "[2/3] Collecting blind test predictions..." -ForegroundColor Yellow
        & $python $collector --split test --batch-size $BatchSize
        if ($LASTEXITCODE -ne 0) {
            throw "Test collection failed with exit code $LASTEXITCODE."
        }

        Write-Host "[3/3] Evaluating the event-aware cascade..." -ForegroundColor Yellow
        & $python $evaluator
        if ($LASTEXITCODE -ne 0) {
            throw "Cascade evaluation failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($keyPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
    }
    $plainKey = $null
    Remove-Item Env:LLM_API_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:LLM_BASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:LLM_MODEL -ErrorAction SilentlyContinue
    Remove-Item Env:LLM_TIMEOUT_SECONDS -ErrorAction SilentlyContinue
    Remove-Item Env:LLM_MAX_ATTEMPTS -ErrorAction SilentlyContinue
}

Write-Host "Blind evaluation completed." -ForegroundColor Green
