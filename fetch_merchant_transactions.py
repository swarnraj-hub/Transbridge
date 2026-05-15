import hashlib
import os
import requests
from datetime import datetime, timedelta, timezone

API_KEY = os.environ["TB_API_KEY"]
SECRET_KEY = os.environ["TB_SECRET_KEY"]
BASE_URL = "https://api.transactbridge.com"


def generate_signature(api_key: str, secret_key: str) -> str:
    raw = f"{api_key}:{secret_key}"
    return hashlib.sha512(raw.encode()).hexdigest()


def get_headers(signature: str) -> dict:
    return {
        "Content-Type": "application/json",
        "x-api-key": API_KEY,
        "x-signature": signature,
    }


def get_all_merchants(headers: dict) -> list:
    url = f"{BASE_URL}/user/v1.0/getAllUsers"
    resp = requests.post(url, headers=headers, json={}, timeout=60)
    resp.raise_for_status()
    body = resp.json()
    return body.get("data", [])


def get_deposit_txs_page(merchant_id: str, headers: dict, from_date: str, to_date: str, page: int) -> tuple[list, bool]:
    """Returns (records, has_more) for a single page."""
    url = f"{BASE_URL}/transaction/v1.0/getDepositTxs"
    payload = {
        "userId": merchant_id,
        "filter": {
            "fromDate": from_date,
            "toDate": to_date,
        },
        "page": page,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    body = resp.json()
    data = body.get("data", [])
    has_more = bool(body.get("hasMore", False))
    return data, has_more


def get_all_deposit_txs(merchant_id: str, headers: dict, from_date: str, to_date: str) -> list:
    """Loops through every page using hasMore flag and returns all transactions for one merchant."""
    all_txs = []
    page = 1

    while True:
        txs, has_more = get_deposit_txs_page(merchant_id, headers, from_date, to_date, page)
        all_txs.extend(txs)
        print(f"      page {page} -> {len(txs)} records (hasMore={has_more})")

        if not has_more:
            break
        page += 1

    return all_txs


def flatten_transaction(tx: dict) -> dict:
    return {
        "_id": tx.get("_id", ""),
        "merchantId": tx.get("merchantId", ""),
        "customerId": tx.get("customerId", ""),
        "status": tx.get("status", ""),
        "type": tx.get("type", ""),
        "txSubStatus": tx.get("txSubStatus", ""),
        "code": tx.get("code", ""),
        "quoteCurrCode": tx.get("quoteCurrCode", ""),
        "isSettled": tx.get("isSettled", False),
        "referenceId": tx.get("referenceId", ""),
        "billingSessionId": tx.get("billingSessionId", ""),
        "paymentDetails.payMethod": (tx.get("paymentDetails") or {}).get("payMethod", ""),
        "paymentDetails.upiChannel": (tx.get("paymentDetails") or {}).get("upiChannel", ""),
        "meta.param1": (tx.get("meta") or {}).get("param1", ""),
        "meta.param2": (tx.get("meta") or {}).get("param2", ""),
        "meta.param3": (tx.get("meta") or {}).get("param3", ""),
        "txSubType": tx.get("txSubType", ""),
        "gstInclusive": tx.get("gstInclusive", False),
        "isMandate": tx.get("isMandate", False),
        "isBanned": tx.get("isBanned", False),
        "createdDate": tx.get("createdDate", ""),
        "updatedDate": tx.get("updatedDate", ""),
        "clientReferenceId": tx.get("clientReferenceId", ""),
        "quoteAmt": tx.get("quoteAmt", 0),
        "quoteAmount": tx.get("quoteAmount", 0),
        "totalTax": tx.get("totalTax", 0),
        "totalQuoteAmount": tx.get("totalQuoteAmount", 0),
        "totalAmount": tx.get("totalAmount", 0),
        "txQuoteFee": tx.get("txQuoteFee", 0),
        "txCostQuoteFee": tx.get("txCostQuoteFee", 0),
        "rrQuoteFee": tx.get("rrQuoteFee", 0),
        "settleQuoteAmount": tx.get("settleQuoteAmount", 0),
        "mandateRegQuoteFee": tx.get("mandateRegQuoteFee", 0),
        "mandateExcQuoteFee": tx.get("mandateExcQuoteFee", 0),
        "successDate": tx.get("successDate", ""),
        "failedDate": tx.get("failedDate", ""),
        "subscriptionId": tx.get("subscriptionId", ""),
        "discount": tx.get("discount", 0),
        "refund_txnId": tx.get("refund_txnId", ""),
        "refund_initiatedDate": tx.get("refund_initiatedDate", ""),
        "refund_successDate": tx.get("refund_successDate", ""),
        "refund_status": tx.get("refund_status", ""),
        "chargeback_txnId": tx.get("chargeback_txnId", ""),
        "chargeback_initiatedDate": tx.get("chargeback_initiatedDate", ""),
        "chargeback_successDate": tx.get("chargeback_successDate", ""),
        "chargeback_status": tx.get("chargeback_status", ""),
        "banDate": tx.get("banDate", ""),
        "email": tx.get("email", ""),
        "browserIp": tx.get("browserIp", ""),
    }


def main():
    today = datetime.now(timezone.utc)
    from_date = (today - timedelta(days=10)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    signature = generate_signature(API_KEY, SECRET_KEY)
    headers = get_headers(signature)

    print(f"Fetching merchants...")
    merchants = get_all_merchants(headers)
    print(f"Found {len(merchants)} merchants")

    all_transactions = []

    for merchant in merchants:
        merchant_id = merchant.get("_id") or merchant.get("userId") or merchant.get("id")
        if not merchant_id:
            print(f"  Skipping merchant with no ID: {merchant}")
            continue

        print(f"  Fetching transactions for merchant {merchant_id}...")
        try:
            txs = get_all_deposit_txs(merchant_id, headers, from_date, to_date)
            flat_txs = [flatten_transaction(tx) for tx in txs]
            all_transactions.extend(flat_txs)
            print(f"    -> {len(flat_txs)} total transactions")
        except requests.HTTPError as e:
            print(f"    -> HTTP error for {merchant_id}: {e}")
        except Exception as e:
            print(f"    -> Error for {merchant_id}: {e}")

    print(f"\nTotal transactions fetched: {len(all_transactions)}")

    # Save to CSV
    if all_transactions:
        import csv
        output_file = f"transactions_{from_date}_to_{to_date}.csv"
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_transactions[0].keys())
            writer.writeheader()
            writer.writerows(all_transactions)
        print(f"Saved to {output_file}")

    return all_transactions


if __name__ == "__main__":
    main()
