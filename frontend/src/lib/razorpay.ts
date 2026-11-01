/** Loads the Razorpay hosted checkout and opens it with server-issued order details. */

const CHECKOUT_SCRIPT = "https://checkout.razorpay.com/v1/checkout.js";

export interface RazorpaySuccessPayload {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

interface RazorpayCheckoutInstance {
  open: () => void;
  on: (event: "payment.failed", handler: (response: { error?: { description?: string } }) => void) => void;
}

interface RazorpayOptions {
  key: string;
  order_id: string;
  amount: number;
  currency: string;
  name?: string;
  description?: string;
  prefill?: { name?: string; email?: string };
  theme?: { color?: string };
  handler: (payload: RazorpaySuccessPayload) => void;
  modal?: { ondismiss?: () => void };
}

declare global {
  interface Window {
    Razorpay?: new (options: RazorpayOptions) => RazorpayCheckoutInstance;
  }
}

let scriptPromise: Promise<void> | null = null;

function loadCheckoutScript(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  if (!scriptPromise) {
    scriptPromise = new Promise<void>((resolve, reject) => {
      const el = document.createElement("script");
      el.src = CHECKOUT_SCRIPT;
      el.async = true;
      el.onload = () => resolve();
      el.onerror = () => {
        scriptPromise = null;
        reject(new Error("Could not load the payment gateway. Check your internet connection and try again."));
      };
      document.body.appendChild(el);
    });
  }
  return scriptPromise;
}

export interface RazorpayCheckoutRequest {
  key_id: string;
  order_id: string;
  amount: number;
  currency: string;
  name?: string;
  description?: string;
  prefill?: { name?: string; email?: string };
  onSuccess: (payload: RazorpaySuccessPayload) => void;
  onDismiss?: () => void;
  onFailure?: (message: string) => void;
}

export async function openRazorpayCheckout(request: RazorpayCheckoutRequest): Promise<void> {
  await loadCheckoutScript();
  if (!window.Razorpay) {
    throw new Error("The payment gateway script did not initialise. Please retry.");
  }
  const checkout = new window.Razorpay({
    key: request.key_id,
    order_id: request.order_id,
    amount: request.amount,
    currency: request.currency,
    name: request.name,
    description: request.description,
    prefill: request.prefill,
    theme: { color: "#3b6cf6" },
    handler: request.onSuccess,
    modal: { ondismiss: request.onDismiss },
  });
  checkout.on("payment.failed", (response) => {
    request.onFailure?.(response.error?.description ?? "The payment failed. Please try again.");
  });
  checkout.open();
}
