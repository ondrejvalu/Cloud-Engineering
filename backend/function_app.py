import azure.functions as func
import logging
import requests
import os

app = func.FunctionApp()

# ---------------------------------------------------------
# 1. ORCHESTRATOR: Start the Sandbox (HTTP Trigger)
# ---------------------------------------------------------
@app.route(route="StartSandbox", auth_level=func.AuthLevel.ANONYMOUS)
def StartSandbox(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('StartSandbox trigger activated.')
    return func.HttpResponse("Sandbox provisioning initiated successfully.", status_code=200)

# ---------------------------------------------------------
# 2. BUDGET GUARD: 10-Minute Kill Switch (Timer Trigger)
# ---------------------------------------------------------
@app.timer_trigger(schedule="0 */5 * * * *", arg_name="myTimer", run_on_startup=False)
def BudgetGuard(myTimer: func.TimerRequest) -> None:
    logging.info('BudgetGuard timer activated.')
    if myTimer.past_due:
        logging.info('The timer is past due!')