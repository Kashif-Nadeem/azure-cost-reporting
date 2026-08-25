import logging

import azure.functions as func

from reporting import run_monthly_report


app = func.FunctionApp()


@app.function_name(name="monthly_invoice_report")
@app.schedule(
    schedule="%MONTHLY_REPORT_SCHEDULE%",
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def monthly_invoice_report(timer: func.TimerRequest) -> None:
    if timer.past_due:
        logging.warning("Monthly invoice report timer is past due.")

    result = run_monthly_report()

    logging.info(
        "Monthly invoice report completed: "
        "month=%s subscriptions=%s invoices=%s total=%s",
        result["report_month"],
        result["subscriptions_queried"],
        result["invoice_count"],
        result["total_amount"],
    )
