import csv
import hashlib
import os
import requests
import boto3
from datetime import datetime, timedelta, timezone

API_KEY = os.environ["TB_API_KEY"]
SECRET_KEY = os.environ["TB_SECRET_KEY"]
BASE_URL = "https://api.transactbridge.com"

AWS_ACCESS_KEY_ID = os.environ["AWS_ACCESS_KEY_ID"]
AWS_SECRET_ACCESS_KEY = os.environ["AWS_SECRET_ACCESS_KEY"]
S3_BUCKET = os.environ["S3_BUCKET"]
S3_PREFIX = "transact_bridge/raw"
AWS_REGION = "ap-southeast-1"


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
        "isSettled": tx.get("isSettled", ""),
        "referenceId": tx.get("referenceId", ""),
        "billingSessionId": tx.get("billingSessionId", ""),
        "paymentDetails.payMethod": (tx.get("paymentDetails") or {}).get("payMethod", ""),
        "paymentDetails.upiChannel": (tx.get("paymentDetails") or {}).get("upiChannel", ""),
        "meta.param1": (tx.get("meta") or {}).get("param1", ""),
        "meta.param2": (tx.get("meta") or {}).get("param2", ""),
        "meta.param3": (tx.get("meta") or {}).get("param3", ""),
        "txSubType": tx.get("txSubType", ""),
        "gstInclusive": tx.get("gstInclusive", ""),
        "isMandate": tx.get("isMandate", ""),
        "isBanned": tx.get("isBanned", ""),
        "createdDate": tx.get("createdDate", ""),
        "updatedDate": tx.get("updatedDate", ""),
        "clientReferenceId": tx.get("clientReferenceId", ""),
        "quoteAmt": tx.get("quoteAmt", ""),
        "quoteAmount": tx.get("quoteAmount", ""),
        "totalTax": tx.get("totalTax", ""),
        "totalQuoteAmount": tx.get("totalQuoteAmount", ""),
        "totalAmount": tx.get("totalAmount", ""),
        "txQuoteFee": tx.get("txQuoteFee", ""),
        "txCostQuoteFee": tx.get("txCostQuoteFee", ""),
        "rrQuoteFee": tx.get("rrQuoteFee", ""),
        "settleQuoteAmount": tx.get("settleQuoteAmount", ""),
        "mandateRegQuoteFee": tx.get("mandateRegQuoteFee", ""),
        "mandateExcQuoteFee": tx.get("mandateExcQuoteFee", ""),
        "successDate": tx.get("successDate", ""),
        "failedDate": tx.get("failedDate", ""),
        "subscriptionId": tx.get("subscriptionId", ""),
        "discount": tx.get("discount", ""),
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


def upload_to_s3(local_path: str, s3_key: str) -> None:
    s3 = boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )
    s3.upload_file(local_path, S3_BUCKET, s3_key)
    print(f"Uploaded to s3://{S3_BUCKET}/{s3_key}")


def main():
    today = datetime.now(timezone.utc)
    from_date = (today - timedelta(days=10)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    signature = generate_signature(API_KEY, SECRET_KEY)
    headers = get_headers(signature)

    print("Fetching merchants...")
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

    if all_transactions:
        filename = f"transactions_{from_date}_to_{to_date}.csv"
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_transactions[0].keys())
            writer.writeheader()
            writer.writerows(all_transactions)
        print(f"Saved locally: {filename}")

        s3_key = f"{S3_PREFIX}/{filename}"
        upload_to_s3(filename, s3_key)


if __name__ == "__main__":
    main()
