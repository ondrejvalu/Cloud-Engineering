import azure.functions as func
import logging
import requests
import os
import datetime
from datetime import timezone

app = func.FunctionApp()

# Scaleway API Configuration (Paris region is standard)
SCW_ZONE = "fr-par-1"
SCW_API_URL = f"https://api.scaleway.com/instance/v1/zones/{SCW_ZONE}"

def get_scw_headers():
    """Generates standard headers for Scaleway API authentication"""
    return {
        "X-Auth-Token": os.environ["SCALEWAY_SECRET_KEY"],
        "Content-Type": "application/json"
    }

# ---------------------------------------------------------
# 1. ORCHESTRATOR: Start the Sandbox (HTTP Trigger)
# ---------------------------------------------------------
@app.route(route="StartSandbox", auth_level=func.AuthLevel.ANONYMOUS)
def StartSandbox(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('StartSandbox trigger activated.')
    
    project_id = os.environ["SCALEWAY_PROJECT_ID"]
    headers = get_scw_headers()
    
    gh_url = "https://raw.githubusercontent.com/ondrejvalu/Cloud-Engineering/main/scripts/bootstrap.sh"
    resp = requests.get(gh_url)
    if resp.status_code != 200:
        logging.error("Failed to fetch bootstrap.sh from GitHub")
        return func.HttpResponse("Failed to load infrastructure template.", status_code=500)
    
    bootstrap_script = resp.text
    
    # 2. Inject Secrets safely into memory (Zero-Trust)
    bootstrap_script = bootstrap_script.replace("{{AZURE_CLIENT_ID}}", os.environ["ENTRA_CLIENT_ID"])
    bootstrap_script = bootstrap_script.replace("{{AZURE_TENANT_ID}}", os.environ["ENTRA_TENANT_ID"])
    bootstrap_script = bootstrap_script.replace("{{AZURE_CLIENT_SECRET}}", os.environ["ENTRA_CLIENT_SECRET"])
    bootstrap_script = bootstrap_script.replace("{{COOKIE_SECRET}}", os.environ["OAUTH_COOKIE_SECRET"])

    # 3. Create the Server on Scaleway (DEV1-S is the standard cheap instance)
    server_payload = {
        "name": "showcase-ephemeral-sandbox",
        "project": project_id,
        "commercial_type": "DEV1-S",
        "image": "ubuntu_jammy", # Standard Ubuntu 22.04 LTS
        "tags": ["showcase-ephemeral"] # Crucial tag for the Budget Guard
    }
    
    create_res = requests.post(f"{SCW_API_URL}/servers", headers=headers, json=server_payload)
    if create_res.status_code not in (200, 201):
        logging.error(f"Failed to create server: {create_res.text}")
        return func.HttpResponse("Failed to provision cloud resources.", status_code=500)
        
    server_id = create_res.json()["server"]["id"]
    
    # 4. Upload Cloud-Init (User Data) script
    headers_plain = {"X-Auth-Token": os.environ["SCALEWAY_SECRET_KEY"], "Content-Type": "text/plain"}
    requests.patch(
        f"{SCW_API_URL}/servers/{server_id}/user_data/cloud-init", 
        headers=headers_plain, 
        data=bootstrap_script.encode('utf-8')
    )
    
    # 5. Power On the Server
    requests.post(f"{SCW_API_URL}/servers/{server_id}/action", headers=headers, json={"action": "poweron"})
    
    return func.HttpResponse("Sandbox provisioning initiated successfully.", status_code=200)


# ---------------------------------------------------------
# 2. BUDGET GUARD: 10-Minute Kill Switch (Timer Trigger)
# ---------------------------------------------------------
# Runs every 5 minutes (CRON expression: 0 */5 * * * *)
@app.timer_trigger(schedule="0 */5 * * * *", arg_name="myTimer", run_on_startup=False)
def BudgetGuard(myTimer: func.TimerRequest) -> None:
    logging.info('BudgetGuard timer activated.')
    
    headers = get_scw_headers()
    
    # List all servers with our specific tag
    res = requests.get(f"{SCW_API_URL}/servers?tags=showcase-ephemeral", headers=headers)
    if res.status_code != 200:
        logging.error("Failed to fetch servers from Scaleway")
        return
        
    servers = res.json().get("servers", [])
    now = datetime.datetime.now(timezone.utc)
    
    for server in servers:
        created_str = server["creation_date"]
        # Format string to be strictly compatible with Python's fromisoformat
        created_str = created_str.replace('Z', '+00:00') 
        
        try:
            created_at = datetime.datetime.fromisoformat(created_str)
        except Exception as e:
            logging.error(f"Date parse error: {e}")
            continue
            
        # Calculate age in minutes
        delta_minutes = (now - created_at).total_seconds() / 60
        
        if delta_minutes >= 10:
            logging.info(f"Terminating server {server['id']} (Age: {delta_minutes} min). Budget protected.")
            # 'terminate' action forcefully deletes the server and its attached volumes
            requests.post(f"{SCW_API_URL}/servers/{server['id']}/action", headers=headers, json={"action": "terminate"})