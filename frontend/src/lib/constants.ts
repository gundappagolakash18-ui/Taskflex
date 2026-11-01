import type { TaskStatus, TaskType, Urgency } from "@/types";

export const TASK_STATUS_FLOW: TaskStatus[] = [
  "DRAFT",
  "PENDING_CONFIRMATION",
  "CONFIRMED",
  "SEARCHING_WORKER",
  "OFFERED",
  "ACCEPTED",
  "WORKER_ON_THE_WAY",
  "ARRIVED_AT_LOCATION",
  "IN_PROGRESS",
  "COMPLETION_REQUESTED",
  "COMPLETED",
];

export const TASK_STATUS_LABELS: Record<TaskStatus, string> = {
  DRAFT: "Draft",
  PENDING_CONFIRMATION: "Awaiting confirmation",
  CONFIRMED: "Confirmed",
  SEARCHING_WORKER: "Finding workers",
  OFFERED: "Offer sent",
  ACCEPTED: "Accepted",
  WORKER_ON_THE_WAY: "Worker on the way",
  ARRIVED_AT_LOCATION: "Worker arrived",
  IN_PROGRESS: "In progress",
  COMPLETION_REQUESTED: "Completion requested",
  COMPLETED: "Completed",
  CANCELLED: "Cancelled",
  DISPUTED: "Disputed",
  EMERGENCY_ALERT: "Emergency alert",
  QUEUED_NEXT: "Queued next",
  SCHEDULED_OPEN: "Scheduled — open to reserve",
  SCHEDULED_ASSIGNED: "Scheduled — reserved",
};

export const TASK_STATUS_STYLES: Record<TaskStatus, string> = {
  DRAFT: "bg-slate-100 text-slate-600",
  PENDING_CONFIRMATION: "bg-amber-100 text-amber-800",
  CONFIRMED: "bg-blue-100 text-blue-800",
  SEARCHING_WORKER: "bg-indigo-100 text-indigo-800",
  OFFERED: "bg-indigo-100 text-indigo-800",
  ACCEPTED: "bg-teal-100 text-teal-800",
  WORKER_ON_THE_WAY: "bg-cyan-100 text-cyan-800",
  ARRIVED_AT_LOCATION: "bg-sky-100 text-sky-800",
  IN_PROGRESS: "bg-purple-100 text-purple-800",
  COMPLETION_REQUESTED: "bg-violet-100 text-violet-800",
  COMPLETED: "bg-emerald-100 text-emerald-800",
  CANCELLED: "bg-red-100 text-red-700",
  DISPUTED: "bg-orange-100 text-orange-800",
  EMERGENCY_ALERT: "bg-red-600 text-white",
  QUEUED_NEXT: "bg-blue-100 text-blue-800",
  SCHEDULED_OPEN: "bg-amber-100 text-amber-800",
  SCHEDULED_ASSIGNED: "bg-teal-100 text-teal-800",
};

// Statuses where live tracking / public share links make sense.
export const TRACKABLE_STATUSES: TaskStatus[] = [
  "ACCEPTED",
  "WORKER_ON_THE_WAY",
  "ARRIVED_AT_LOCATION",
  "IN_PROGRESS",
  "COMPLETION_REQUESTED",
  "EMERGENCY_ALERT",
];

export const SHAREABLE_STATUSES: TaskStatus[] = TRACKABLE_STATUSES;

export const PROOF_UPLOAD_STATUSES: TaskStatus[] = ["IN_PROGRESS", "COMPLETION_REQUESTED"];

export const EXPENSE_EDITABLE_STATUSES: TaskStatus[] = [
  "WORKER_ON_THE_WAY",
  "ARRIVED_AT_LOCATION",
  "IN_PROGRESS",
  "COMPLETION_REQUESTED",
];

export const SOS_STATUSES: TaskStatus[] = [
  "ACCEPTED",
  "WORKER_ON_THE_WAY",
  "ARRIVED_AT_LOCATION",
  "IN_PROGRESS",
  "COMPLETION_REQUESTED",
];

export const CLOSED_TASK_STATUSES: TaskStatus[] = [
  "COMPLETED",
  "CANCELLED",
  "DISPUTED",
  "EMERGENCY_ALERT",
];

export const TASK_TYPE_LABELS: Record<TaskType, string> = {
  document_submission: "Document submission",
  document_collection: "Document collection",
  queue_standing: "Queue standing",
  government_office: "Government office visit",
  courier_pickup: "Courier / document pickup",
  parcel_collection: "Parcel collection",
  form_submission: "Form submission",
  appointment_assistance: "Appointment assistance",
  local_errand: "Local errand",
  grocery_pickup: "Grocery / item pickup",
  office_errand: "Office errand",
  bank_assistance: "Bank assistance",
  college_work: "College / university work",
  other: "Other errand",
};

export const TASK_TYPE_ICONS: Record<TaskType, string> = {
  document_submission: "📄",
  document_collection: "📋",
  queue_standing: "🪑",
  government_office: "🏛️",
  courier_pickup: "🚚",
  parcel_collection: "📦",
  form_submission: "📝",
  appointment_assistance: "🏥",
  local_errand: "🏃",
  grocery_pickup: "🛒",
  office_errand: "💼",
  bank_assistance: "🏦",
  college_work: "🎓",
  other: "🧭",
};

export const URGENCY_LABELS: Record<Urgency, string> = {
  low: "Flexible",
  normal: "Normal",
  high: "High",
  urgent: "Urgent",
};

export const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

// Free-flow worker transitions only. Arrival → start and completion are
// OTP-gated and have their own endpoints, never a status PATCH.
export const WORKER_NEXT_STATUS: Partial<Record<TaskStatus, TaskStatus>> = {
  ACCEPTED: "WORKER_ON_THE_WAY",
  WORKER_ON_THE_WAY: "ARRIVED_AT_LOCATION",
};

export const EXPENSE_CATEGORY_LABELS: Record<string, string> = {
  PARKING: "Parking",
  GOVT_FEE: "Government fee",
  PURCHASE: "Purchase",
  PRINTING: "Printing / photocopy",
  OTHER: "Other",
};

export const EXPENSE_STATUS_LABELS: Record<string, string> = {
  PENDING_APPROVAL: "Awaiting approval",
  APPROVED: "Approved",
  REJECTED: "Rejected",
  REIMBURSED: "Reimbursed",
};

export const EXPENSE_STATUS_STYLES: Record<string, string> = {
  PENDING_APPROVAL: "bg-amber-100 text-amber-800",
  APPROVED: "bg-emerald-100 text-emerald-800",
  REJECTED: "bg-red-100 text-red-700",
  REIMBURSED: "bg-teal-100 text-teal-800",
};

export const WS_EVENTS = {
  NOTIFICATION: "notification",
  TASK_STATUS: "TASK_STATUS",
  TASK_OFFER: "TASK_OFFER",
  TASK_BID_RECEIVED: "TASK_BID_RECEIVED",
  TASK_BID_ACCEPTED: "TASK_BID_ACCEPTED",
  MESSAGE: "message",
  TRACKING: "tracking_update",
  READ_RECEIPT: "read_receipt",
  EMERGENCY_ALERT: "EMERGENCY_ALERT",
  RIDECHECK_ALERT: "RIDECHECK_ALERT",
  RIDECHECK_UPDATE: "RIDECHECK_UPDATE",
  RIDECHECK_ESCALATED: "RIDECHECK_ESCALATED",
  QUEST_COMPLETED: "QUEST_COMPLETED",
  TIER_UPGRADED: "TIER_UPGRADED",
  READINESS_REQUIRED: "READINESS_REQUIRED",
  RESERVATION_REVOKED: "RESERVATION_REVOKED",
  PAYOUT_PROCESSED: "PAYOUT_PROCESSED",
} as const;

export const TIER_LABELS: Record<string, string> = {
  SILVER: "Silver",
  GOLD: "Gold",
  PLATINUM: "Platinum",
};

export const TIER_STYLES: Record<string, string> = {
  SILVER: "bg-slate-100 text-slate-700 border-slate-200",
  GOLD: "bg-amber-50 text-amber-800 border-amber-200",
  PLATINUM: "bg-indigo-50 text-indigo-800 border-indigo-200",
};

export const TIER_ICONS: Record<string, string> = {
  SILVER: "🥈",
  GOLD: "🥇",
  PLATINUM: "💎",
};

export const STATEMENT_CATEGORY_LABELS: Record<string, string> = {
  base_earnings: "Base earnings",
  overtime_earnings: "Overtime",
  reimbursed_expenses: "Reimbursed expenses",
  tips: "Tips",
  quest_bonuses: "Quest bonuses",
  withdrawals: "Withdrawals",
  other_credits: "Other credits",
};

export const BID_WINDOW_SECONDS = 45;

export const SOS_RESOLVED_EVENT = "taskflex:sos-resolved";

export const CHAT_WS_EVENTS = {
  READY: "chat_ready",
  CLOSED: "chat_closed",
  MESSAGE_SENT: "message_sent",
  READ: "read",
  READ_RECEIPT: "read_receipt",
  ERROR: "chat_error",
} as const;
