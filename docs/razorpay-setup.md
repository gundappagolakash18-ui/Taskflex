# Razorpay payments setup (real money)

TaskFlex takes payments through **Razorpay** hosted checkout with **manual
capture**: confirming a task opens an order and the customer pays in Razorpay's
checkout widget; the money is held, then captured and paid out to the runner
only when the customer confirms completion. Cancellations refund automatically.

Money flow inside TaskFlex:

```
customer confirms task ──▶ Razorpay order created (payment INITIATED)
customer pays in checkout ──▶ POST /payments/verify checks the signature
                              (payment AUTHORIZED — money held)
worker completes + customer confirms ──▶ funds CAPTURED,
                              90% credited to runner wallet, 10% commission
task cancelled before completion ──▶ automatic refund (REFUNDED)
```

While `PAYMENT_PROVIDER=mock` (the default in development) everything works
end-to-end but no real money moves — the mock provider authorizes and refunds
instantly and `POST /payments/verify` is disabled. Switch to `razorpay` when
you are ready to collect real payments.

## 1. Create a Razorpay account

1. Sign up at <https://dashboard.razorpay.com/signup> (business details + KYC
   are required before live payments; **test mode works immediately**).
2. Open **Account & Settings → API Keys → Generate Test Keys**.
   Copy the **Key ID** (`rzp_test_...`) and the **Key Secret**.

> Razorpay's test mode is a full sandbox: real checkout UI, real signature
> flow, no real money. Use it to practise the whole flow below.

## 2. Configure the backend

**Local** — `backend/.env`:

```
PAYMENT_PROVIDER=razorpay
RAZORPAY_KEY_ID=rzp_test_XXXXXXXXXXXXXX
RAZORPAY_KEY_SECRET=<test key secret>
RAZORPAY_WEBHOOK_SECRET=<any long random string you choose>
```

**Production** — same three values in the `.env` next to
`docker-compose.prod.yml` (see `.env.prod.example`), then:

```bash
docker compose -f docker-compose.prod.yml up -d backend
```

The backend **refuses to boot** in production when `PAYMENT_PROVIDER=razorpay`
but the keys are missing — payments are never silently simulated in production.

## 3. Create the webhook

Webhooks keep payment records correct even if the customer closes the browser
mid-payment.

1. Razorpay dashboard → **Account & Settings → Webhooks → Add New Webhook**.
2. **Webhook URL:** `https://yourdomain.com/api/v1/payments/webhook/razorpay`
   (for local testing use a tunnel like `ngrok http 8000` and use the ngrok URL).
3. **Secret:** type the same random string as `RAZORPAY_WEBHOOK_SECRET`.
4. **Active events:** tick `payment.authorized`, `payment.captured`,
   `payment.failed`.
5. Save. The endpoint returns 200 for every validly-signed event; TaskFlex
   refuses unsigned or mis-signed payloads with 400 and unrecognised events are
   acknowledged and ignored.

## 4. Try it (test mode)

Register any customer account, create a task and confirm it — the pay sheet
opens Razorpay checkout. Use Razorpay's test instruments:

| Method | How to succeed | How to fail |
| --- | --- | --- |
| Card | `4111 1111 1111 1111`, any future expiry, any CVV | `4000 0000 0000 0002` |
| UPI | `success@razorpay` | `failure@razorpay` |

After a successful payment the task shows **“Authorised — held in escrow”**.
Cancel the task to see the automatic refund, or complete it to see the runner's
wallet credited (90% of the budget).

## 5. Go live

1. Complete Razorpay KYC/activation.
2. **Account & Settings → API Keys → Generate Live Keys**; replace the three
   values with the live key id (`rzp_live_...`), live secret, and your webhook
   secret; restart the backend.
3. Re-create the webhook with your production URL if you had only a test one.
4. Make one small real payment yourself end-to-end, then refund it from the
   Razorpay dashboard to see the flow from both sides.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Backend won't start: “Razorpay is configured but unavailable” | Key id/secret missing or wrong in `.env`. |
| Checkout opens but payment never registers | Signature mismatch — check `RAZORPAY_KEY_SECRET` matches the key id's secret. |
| Webhook returns 400 | `RAZORPAY_WEBHOOK_SECRET` differs from the secret set on the webhook. |
| Webhook returns 503 | `RAZORPAY_WEBHOOK_SECRET` is empty. |
| Refund says “Gateway refund failed” | The task had no completed checkout (nothing to refund) or keys are wrong; check backend logs. |
