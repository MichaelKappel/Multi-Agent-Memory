$body = @{ label = "Example Agent Workspace" } | ConvertTo-Json
Invoke-RestMethod `
  -Method Post `
  -Uri "https://memoryendpoints.com/api/matm/agent-setup/free-account" `
  -ContentType "application/json" `
  -Body $body
