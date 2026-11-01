import { api } from "./client";
import type { Paginated, PayoutRequest, WalletStatement, WithdrawResult } from "@/types";

export const walletApi = {
  setUpi: (upiId: string) =>
    api.put<{ upi_id: string }>("/wallet/upi", { upi_id: upiId }).then((r) => r.data),

  withdraw: (amount: number, upiId?: string | null) =>
    api.post<WithdrawResult>("/wallet/withdraw", { amount, upi_id: upiId || null }).then((r) => r.data),

  payouts: (page = 1, pageSize = 20) =>
    api
      .get<Paginated<PayoutRequest>>("/wallet/payouts", {
        params: { page, page_size: pageSize },
      })
      .then((r) => r.data),

  statement: (days = 30) =>
    api
      .get<{ statement: WalletStatement }>("/wallet/statement", { params: { format: "json", days } })
      .then((r) => r.data.statement),

  statementCsv: (days = 30) =>
    api
      .get<Blob>("/wallet/statement", {
        params: { format: "csv", days },
        responseType: "blob",
      })
      .then((r) => r.data),
};
