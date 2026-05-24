"""Drive traffic across all agent paths to populate Grafana dashboards."""
from __future__ import annotations

import asyncio
import httpx

CHAT    = "http://localhost:8000/chat"
INVOKE  = "http://localhost:8000/agent/invoke"
APPROVALS = "http://localhost:8000/approvals"

QUERIES = [
    "What is the current stock level for M-1042?",
    "What is the current stock level for M-1001?",
    "What is the current stock level for M-1003?",
    "Do I need to reorder M-1042 for next quarter?",
    "Do I need to reorder M-1001?",
    "Recommend a reorder for M-1042 we need urgent replenishment",
    "What is our policy on emergency procurement?",
    "What are the approval thresholds for purchase orders?",
    "Which vendors are preferred for precision components?",
    "What is the SOP for reordering below safety stock?",
    "Give me an inventory and forecast summary for M-1042",
    "What does the procurement policy say about vendor selection?",
]


async def post_chat(client: httpx.AsyncClient, msg: str, n: int) -> None:
    try:
        r = await client.post(CHAT, json={"message": msg}, timeout=90)
        reply = r.json().get("reply", "")[:55] if r.status_code == 200 else "ERR"
        print(f"  [{n:02d}] {r.status_code}  {reply}")
    except Exception as e:
        print(f"  [{n:02d}] EXC  {str(e)[:60]}")


async def post_invoke(client: httpx.AsyncClient, task: str, label: str) -> None:
    try:
        r = await client.post(INVOKE, json={"task": task}, timeout=90)
        reply = r.json().get("reply", "")[:55] if r.status_code == 200 else "ERR"
        print(f"  [{label}] {r.status_code}  {reply}")
    except Exception as e:
        print(f"  [{label}] EXC  {str(e)[:60]}")


async def get_approvals(client: httpx.AsyncClient) -> None:
    try:
        r = await client.get(APPROVALS, timeout=10)
        count = r.json().get("count", "?")
        print(f"  [approvals] {r.status_code}  pending={count}")
    except Exception as e:
        print(f"  [approvals] EXC  {str(e)[:60]}")


async def main() -> None:
    print("\n=== Populating dashboards — 3 rounds of traffic ===\n")
    async with httpx.AsyncClient() as client:
        for rnd in range(1, 4):
            print(f"--- Round {rnd} ---")
            for i, q in enumerate(QUERIES, 1):
                await post_chat(client, q, i)
            await post_invoke(client, "Compute daily inventory health KPIs", "kpi-1")
            await post_invoke(client, "Generate procurement analytics report", "kpi-2")
            await get_approvals(client)
            if rnd < 3:
                print("  (waiting 15s before next round...)")
                await asyncio.sleep(15)

    print()
    print("=== Done. Metrics export every 30s — dashboards will populate shortly ===")
    print("    https://muthuraj1.grafana.net/dashboards")


if __name__ == "__main__":
    asyncio.run(main())
