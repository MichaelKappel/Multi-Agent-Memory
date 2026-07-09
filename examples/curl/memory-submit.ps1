$workspaceId = "<WORKSPACE_ID>"
$token = "<WORKSPACE_KEY>"
$body = @{
  workspaceId = $workspaceId
  actorAgentId = "example-agent"
  title = "Example decision"
  summary = "Use docs-backed memory until hosted MATM storage is verified."
  tags = @("example", "bootstrap")
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "https://memoryendpoints.com/api/matm/memory-events/submit" `
  -Headers @{
    Authorization = "Bearer $token"
    "Idempotency-Key" = "example-memory-submit-001"
  } `
  -ContentType "application/json" `
  -Body $body
