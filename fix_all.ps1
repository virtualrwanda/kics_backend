# fix_all.ps1 - Complete project cleanup for KICS Ticketing
Write-Host "🔧 Cleaning up KICS Ticketing project..." -ForegroundColor Cyan

# --- STEP 1: Delete duplicate/misplaced folders ---
Write-Host "`n📦 Removing misplaced files..." -ForegroundColor Yellow

$toDelete = @(
    "app\core\core",           # duplicate core
    "app\models\schemas",      # schemas wrongly nested in models
    "app\api\auth.py",         # wrong level
    "app\api\tickets.py",      # wrong level
    "app\api\dashboard.py"     # wrong level
)

foreach ($path in $toDelete) {
    if (Test-Path $path) {
        Remove-Item $path -Recurse -Force
        Write-Host "  ❌ Deleted $path"
    }
}

# --- STEP 2: Create proper folder structure ---
Write-Host "`n📁 Creating folder structure..." -ForegroundColor Yellow

$folders = @(
    "app",
    "app\core",
    "app\models",
    "app\schemas",
    "app\services",
    "app\utils",
    "app\api",
    "app\api\v1",
    "app\api\v1\routes",
    "scripts"
)

foreach ($f in $folders) {
    New-Item -Path $f -ItemType Directory -Force | Out-Null
    New-Item -Path "$f\__init__.py" -ItemType File -Force | Out-Null
}
Write-Host "  ✅ Folders created"

# --- STEP 3: Verify core files exist ---
Write-Host "`n🔍 Checking core files..." -ForegroundColor Yellow

$required = @(
    "app\main.py",
    "app\core\config.py",
    "app\core\database.py",
    "app\core\security.py",
    "app\core\dependencies.py",
    "app\models\user.py",
    "app\models\ticket.py",
    "app\models\comment.py",
    "app\schemas\user.py",
    "app\schemas\ticket.py",
    "app\schemas\comment.py",
    "app\api\v1\router.py",
    "app\api\v1\routes\auth.py",
    "app\api\v1\routes\tickets.py",
    "app\api\v1\routes\users.py",
    "app\api\v1\routes\dashboard.py"
)

$missing = @()
foreach ($f in $required) {
    if (-not (Test-Path $f)) {
        $missing += $f
        Write-Host "  ❌ MISSING: $f" -ForegroundColor Red
    } else {
        Write-Host "  ✅ $f" -ForegroundColor Green
    }
}

Write-Host ""
if ($missing.Count -gt 0) {
    Write-Host "⚠️  $($missing.Count) files are missing!" -ForegroundColor Red
    Write-Host "Run the generator script to create them." -ForegroundColor Yellow
} else {
    Write-Host "🎉 All files present! Try running:" -ForegroundColor Green
    Write-Host "   python -m uvicorn app.main:app --reload" -ForegroundColor Cyan
}

Write-Host "`n📂 Final structure:" -ForegroundColor Yellow
Get-ChildItem -Recurse .\app | Where-Object { $_.Name -like "*.py" } | Select-Object FullName