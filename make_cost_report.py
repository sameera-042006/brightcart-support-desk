"""Builds 09_Cost_Analysis.xlsx from results/cost_log.csv and results/evaluation_results.csv."""
import json
import pathlib

import pandas as pd

R = pathlib.Path(__file__).resolve().parent / "results"
cost = pd.read_csv(R / "cost_log.csv")
res = pd.read_csv(R / "evaluation_results.csv")
summary = json.loads((R / "summary.json").read_text())
pr = summary["pricing"]

per_task = cost.groupby(["system", "agent"], as_index=False).sum(numeric_only=True)
per_query = cost.groupby(["system", "test_id"], as_index=False).sum(numeric_only=True)
totals = cost.groupby("system", as_index=False).agg(
    queries=("test_id", "nunique"), llm_calls=("llm_calls", "sum"), input_tokens=("input_tokens", "sum"),
    output_tokens=("output_tokens", "sum"), total_cost_usd=("cost_usd", "sum"))
totals["cost_per_query_usd"] = totals["total_cost_usd"] / totals["queries"]
pricing_df = pd.DataFrame(list(pr.items()), columns=["item", "value"])

with pd.ExcelWriter("09_Cost_Analysis.xlsx") as xw:
    cost.to_excel(xw, "PerCall_Agent", index=False)
    per_task.to_excel(xw, "PerAgent_Total", index=False)
    per_query.to_excel(xw, "PerQuery", index=False)
    totals.to_excel(xw, "Totals", index=False)
    pricing_df.to_excel(xw, "Pricing", index=False)
    res.to_excel(xw, "EvalResults", index=False)
print(totals.to_string(index=False))
