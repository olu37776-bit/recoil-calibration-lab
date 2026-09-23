# Existing-repository push helper; never creates a repository or rewrites history.
param([string]$Repository = "olu37776-bit/recoil-calibration-lab")
$ErrorActionPreference = "Stop"
if (!(Test-Path .git)) { throw "请先 git clone 目标仓库，在克隆目录提交变更；本工具不创建替代历史。" }
$Remote = git remote get-url origin
if ($LASTEXITCODE -ne 0) { throw "缺少 origin；请从指定仓库正常克隆。" }
if ($Remote -ne "https://github.com/$Repository.git" -and $Remote -ne "git@github.com:$Repository.git") {
    throw "origin 与指定仓库不一致，拒绝推送。"
}
if (git status --porcelain) { throw "存在未提交变更；先检查并提交，不自动扩大写入范围。" }
git push origin HEAD
if ($LASTEXITCODE -ne 0) { throw "推送失败；检查远端变化与权限，不要使用 --force。" }
